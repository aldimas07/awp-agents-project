#!/usr/bin/env python3
"""Mine Setup Wizard - Foolproof setup for any AI agent.

This script handles the entire setup process with:
1. Simple, structured JSON output
2. Auto-detection and auto-fix of common issues
3. Stateful progress tracking (can resume)
4. Single command for each step

Usage:
    python scripts/mine_setup.py              # Run full setup wizard
    python scripts/mine_setup.py --status     # Check current setup status
    python scripts/mine_setup.py --fix        # Auto-fix detected issues
    python scripts/mine_setup.py --step N     # Run specific step (1-5)
    python scripts/mine_setup.py --reset      # Reset setup state
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import (
    DEFAULT_MINER_ID,
    DEFAULT_PLATFORM_BASE_URL,
    WALLET_SESSION_DURATION_SECONDS,
    format_wallet_bin_display,
    resolve_awp_registration,
    persist_wallet_session,
    resolve_miner_id,
    resolve_platform_base_url,
    resolve_runtime_readiness,
    resolve_signature_config,
    resolve_wallet_bin,
    resolve_wallet_config,
)
from install_guidance import awp_wallet_install_steps
from post_install_check import attempt_install_awp_wallet

# Configuration
MIN_PYTHON_VERSION = (3, 11)
MIN_NODE_VERSION = 20
DEFAULT_URL = DEFAULT_PLATFORM_BASE_URL
STATE_FILE = Path(__file__).parent.parent / ".mine-setup.json"

# Output helpers - ALL outputs go through these for consistency


def output_success(message: str, **extra: Any) -> dict[str, Any]:
    """Output a success result."""
    result = {"status": "success", "message": message, **extra}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def output_error(message: str, fix_command: str | None = None, **extra: Any) -> dict[str, Any]:
    """Output an error result with optional fix command."""
    result = {"status": "error", "message": message, **extra}
    if fix_command:
        result["fix_command"] = fix_command
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def output_action_needed(message: str, next_command: str, **extra: Any) -> dict[str, Any]:
    """Output when user action is needed."""
    result = {"status": "action_needed", "message": message, "next_command": next_command, **extra}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def output_progress(step: int, total: int, step_name: str, status: str, **extra: Any) -> dict[str, Any]:
    """Output progress information."""
    result = {
        "status": status,
        "progress": {"step": step, "total": total, "step_name": step_name},
        **extra,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


@dataclass
class SetupState:
    """Tracks setup progress."""

    step: int = 0
    python_ok: bool = False
    node_ok: bool = False
    venv_ok: bool = False
    deps_ok: bool = False
    wallet_ok: bool = False
    wallet_token: str = ""
    wallet_token_expires_at: int = 0
    env_ok: bool = False
    platform_url: str = ""
    miner_id: str = ""
    last_error: str = ""
    completed: bool = False

    def save(self) -> None:
        """Save state to disk."""
        STATE_FILE.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "SetupState":
        """Load state from disk."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def reset(self) -> None:
        """Reset state."""
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, self.__dataclass_fields__[field_name].default)
        if STATE_FILE.exists():
            STATE_FILE.unlink()


# Step implementations


def step1_check_python() -> tuple[bool, str]:
    """Step 1: Check Python version."""
    version = sys.version_info[:2]
    version_str = f"{version[0]}.{version[1]}"

    if version >= MIN_PYTHON_VERSION:
        return True, f"Python {version_str} (>= {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}) ✓"

    fix_commands = {
        "win32": "Download Python 3.11+ from https://python.org",
        "darwin": "brew install python@3.13",
        "linux": "apt install python3.13 or pyenv install 3.13",
    }
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    fix = fix_commands.get(platform, fix_commands["linux"])

    return False, f"Python {version_str} is below {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}. Fix: {fix}"


def step2_check_node() -> tuple[bool, str]:
    """Step 2: Check Node.js version (for awp-wallet)."""
    node_bin = shutil.which("node")
    if not node_bin:
        return False, "Node.js not found. Install from https://nodejs.org (required for awp-wallet)"

    try:
        result = subprocess.run([node_bin, "--version"], capture_output=True, text=True, timeout=5)
        version_str = result.stdout.strip().lstrip("v")
        major = int(version_str.split(".")[0])

        if major >= MIN_NODE_VERSION:
            return True, f"Node.js v{version_str} (>= v{MIN_NODE_VERSION}) ✓"

        return False, f"Node.js v{version_str} is below v{MIN_NODE_VERSION}. Upgrade: nvm install 20"
    except Exception as e:
        return False, f"Could not check Node.js version: {e}"


def step3_setup_venv() -> tuple[bool, str]:
    """Step 3: Create virtualenv and install dependencies."""
    venv_dir = Path(__file__).parent.parent / ".venv"

    # Check if venv exists and has python
    venv_python = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    if sys.platform == "win32":
        venv_python = venv_python.with_suffix(".exe")

    if venv_dir.exists() and venv_python.exists():
        return True, "Virtualenv ready at .venv"

    # Create venv
    try:
        if shutil.which("uv"):
            subprocess.run(["uv", "venv", "--seed", str(venv_dir)], check=True, capture_output=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, capture_output=True)

        return True, "Virtualenv created at .venv"
    except subprocess.CalledProcessError as e:
        return False, f"Failed to create virtualenv: {e.stderr if e.stderr else e}"


def step4_install_deps() -> tuple[bool, str]:
    """Step 4: Install Python dependencies."""
    mine_root = Path(__file__).parent.parent
    venv_dir = mine_root / ".venv"
    venv_python = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    if sys.platform == "win32":
        venv_python = venv_python.with_suffix(".exe")

    if not venv_python.exists():
        return False, "Virtualenv not ready. Run step 3 first."

    requirements = mine_root / "requirements-core.txt"
    if not requirements.exists():
        return False, f"requirements-core.txt not found at {requirements}"

    try:
        # Install core requirements
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-q", "-r", str(requirements)],
            check=True,
            capture_output=True,
        )

        # Try browser requirements too
        browser_requirements = mine_root / "requirements-browser.txt"
        if browser_requirements.exists():
            subprocess.run(
                [str(venv_python), "-m", "pip", "install", "-q", "-r", str(browser_requirements)],
                capture_output=True,  # Don't fail on browser deps
            )

        return True, "Dependencies installed ✓"
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        return False, f"Failed to install dependencies: {stderr[:200]}"


def step5_setup_wallet() -> tuple[bool, str, dict[str, Any]]:
    """Step 5: Ensure awp-wallet exists and the local wallet session is ready."""
    wallet_bin = resolve_wallet_bin()
    extra: dict[str, Any] = {}

    # Check if awp-wallet is installed
    if not (shutil.which(wallet_bin) or Path(wallet_bin).exists()):
        # Try to find it via npm
        npm_bin = shutil.which("npm")
        if npm_bin:
            extra["fix_command"] = " && ".join(awp_wallet_install_steps())
        return False, "awp-wallet not found. Install it first.", extra

    extra["wallet_bin"] = format_wallet_bin_display(wallet_bin)

    # Check if wallet is initialized
    env = os.environ.copy()
    if not env.get("HOME") and env.get("USERPROFILE"):
        env["HOME"] = env["USERPROFILE"]

    try:
        # Check wallet status
        result = subprocess.run([wallet_bin, "receive"], capture_output=True, text=True, timeout=10, env=env)

        if result.returncode != 0:
            stderr = result.stderr.lower()
            if "not initialized" in stderr or "no wallet" in stderr or "init first" in stderr:
                init_result = subprocess.run([wallet_bin, "init"], capture_output=True, text=True, timeout=30, env=env)
                if init_result.returncode != 0:
                    return False, f"Wallet initialization failed: {init_result.stderr.strip()}", extra
                result = subprocess.run([wallet_bin, "receive"], capture_output=True, text=True, timeout=10, env=env)
                if result.returncode != 0:
                    return False, f"Wallet check failed after init: {result.stderr.strip()}", extra
            else:
                return False, f"Wallet check failed: {result.stderr.strip()}", extra

        # Parse address
        data = json.loads(result.stdout)
        address = data.get("address") or data.get("eoaAddress") or ""
        if not address:
            addresses = data.get("addresses", [])
            if addresses and isinstance(addresses[0], dict):
                address = addresses[0].get("address", "")

        extra["wallet_address"] = address

        duration = WALLET_SESSION_DURATION_SECONDS
        unlock_result = subprocess.run(
            [wallet_bin, "unlock", "--duration", str(duration), "--scope", "full"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        if unlock_result.returncode != 0:
            # Might need password - this is the only expected manual fallback
            if "password" in unlock_result.stderr.lower():
                extra["needs_password"] = True
                extra["manual_command"] = f"awp-wallet unlock --duration {duration} --scope full"
                return False, "Wallet needs interactive confirmation. Run awp-wallet unlock once, then rerun setup.", extra
            return False, f"Unlock failed: {unlock_result.stderr.strip()}", extra

        unlock_data = json.loads(unlock_result.stdout)
        session_token = str(unlock_data.get("sessionToken") or "").strip()

        if not session_token:
            return False, "Unlock succeeded but no sessionToken returned", extra

        issued_at = int(time.time())
        expires_at = issued_at + duration
        persist_wallet_session(session_token, expires_at=expires_at)

        extra["session_token"] = session_token
        extra["expires_at"] = expires_at
        extra["wallet_session"] = {
            "status": "ready",
            "managed": True,
            "expires_at": expires_at,
        }

        return True, f"Wallet session ready ✓ (address: {address[:10]}...)", extra

    except json.JSONDecodeError:
        return False, "Could not parse wallet response", extra
    except subprocess.TimeoutExpired:
        return False, "Wallet command timed out", extra
    except Exception as e:
        return False, f"Wallet error: {e}", extra


def step6_configure_env(state: SetupState) -> tuple[bool, str, dict[str, Any]]:
    """Step 6: Confirm effective runtime defaults using unified readiness contract."""
    extra: dict[str, Any] = {}

    # Use unified readiness contract
    readiness = resolve_runtime_readiness()
    signature_config = readiness.get("signature_config", {})
    registration = readiness.get("registration", {})

    extra["configured"] = {
        "state": readiness["state"],
        "can_diagnose": readiness["can_diagnose"],
        "can_start": readiness["can_start"],
        "can_mine": readiness["can_mine"],
        "warnings": readiness.get("warnings", []),
        "PLATFORM_BASE_URL": readiness["platform_base_url"],
        "MINER_ID": readiness["miner_id"],
        "wallet_session": readiness["wallet_session"],
        "auth_mode": "auto-managed wallet session",
        "signature_config_origin": readiness["signature_config_origin"],
        "signature_domain_name": signature_config.get("domain_name"),
        "signature_chain_id": signature_config.get("chain_id"),
        "registration_status": registration.get("status"),
        "wallet_address": registration.get("wallet_address"),
    }

    # Success = can_start (registration can be deferred to agent-start)
    if not readiness["can_start"]:
        extra["fix_command"] = "python scripts/run_tool.py doctor"
        return False, f"Not ready: {readiness['state']}", extra

    if not readiness["can_mine"]:
        return True, "Runtime ready ✓ (registration will be attempted on start)", extra

    return True, "Runtime ready ✓ (fully operational)", extra


def run_full_setup() -> dict[str, Any]:
    """Run the full setup wizard."""
    state = SetupState.load()

    steps = [
        ("Python Version", step1_check_python),
        ("Node.js Version", step2_check_node),
        ("Virtual Environment", step3_setup_venv),
        ("Dependencies", step4_install_deps),
        ("AWP Wallet", None),  # Special handling
        ("Environment", None),  # Special handling
    ]

    results = []
    all_ok = True
    current_step = 0

    for i, (name, func) in enumerate(steps, 1):
        current_step = i

        if name == "AWP Wallet":
            ok, msg, extra = step5_setup_wallet()
            if ok and extra.get("session_token"):
                state.wallet_token = extra["session_token"]
                state.wallet_token_expires_at = extra.get("expires_at", 0)
        elif name == "Environment":
            ok, msg, extra = step6_configure_env(state)
        else:
            ok, msg = func()
            extra = {}

        results.append({
            "step": i,
            "name": name,
            "ok": ok,
            "message": msg,
            **extra,
        })

        # Update state
        if name == "Python Version":
            state.python_ok = ok
        elif name == "Node.js Version":
            state.node_ok = ok
        elif name == "Virtual Environment":
            state.venv_ok = ok
        elif name == "Dependencies":
            state.deps_ok = ok
        elif name == "AWP Wallet":
            state.wallet_ok = ok
        elif name == "Environment":
            state.env_ok = ok

        if not ok:
            all_ok = False
            state.last_error = msg
            state.step = i
            state.save()

            # Return with info about what to fix
            fix_info = results[-1].get("fix_command") or results[-1].get("manual_command")
            return output_progress(
                i,
                len(steps),
                name,
                "error",
                message=msg,
                results=results,
                fix_command=fix_info,
                next_command=f"python scripts/mine_setup.py --step {i}" if fix_info else None,
            )

    # All steps passed!
    state.completed = True
    state.step = len(steps)
    state.save()

    final_command = "python scripts/run_tool.py first-load"

    return output_success(
        "Setup complete! Mine is ready to use.",
        results=results,
        next_command=final_command,
    )


def check_status() -> dict[str, Any]:
    """Check current setup status."""
    state = SetupState.load()

    checks = []

    # Quick checks
    py_ok, py_msg = step1_check_python()
    checks.append({"name": "Python", "ok": py_ok, "message": py_msg})

    node_ok, node_msg = step2_check_node()
    checks.append({"name": "Node.js", "ok": node_ok, "message": node_msg})

    venv_dir = Path(__file__).parent.parent / ".venv"
    venv_ok = venv_dir.exists()
    checks.append({"name": "Virtualenv", "ok": venv_ok, "message": ".venv" if venv_ok else "Not created"})

    wallet_bin = resolve_wallet_bin()
    wallet_ok = bool(shutil.which(wallet_bin) or Path(wallet_bin).exists())
    checks.append({
        "name": "awp-wallet",
        "ok": wallet_ok,
        "message": format_wallet_bin_display(wallet_bin) if wallet_ok else "Not found",
    })

    platform_url = resolve_platform_base_url()
    miner_id = resolve_miner_id()
    _wallet_bin, wallet_token = resolve_wallet_config()

    env_ok = bool(platform_url and miner_id)
    env_items = []
    if platform_url:
        env_items.append(f"PLATFORM_BASE_URL={platform_url}")
    if miner_id:
        env_items.append(f"MINER_ID={miner_id}")
    if wallet_token:
        env_items.append(f"wallet_session={wallet_token[:8]}...")
    else:
        env_items.append("wallet_session=auto-managed")

    checks.append({
        "name": "Environment",
        "ok": env_ok,
        "message": ", ".join(env_items) if env_items else "Not configured",
    })

    all_ok = all(c["ok"] for c in checks)

    if all_ok:
        return output_success("All checks passed!", checks=checks, next_command="python scripts/run_tool.py agent-start")
    else:
        failed = [c for c in checks if not c["ok"]]
        return output_action_needed(
            f"{len(failed)} check(s) failed",
            "python scripts/mine_setup.py",
            checks=checks,
        )


def auto_fix() -> dict[str, Any]:
    """Attempt to auto-fix common issues."""
    fixes_applied = []
    fixes_failed = []

    # Fix 1: Create venv if missing
    venv_dir = Path(__file__).parent.parent / ".venv"
    if not venv_dir.exists():
        ok, msg = step3_setup_venv()
        if ok:
            fixes_applied.append("Created virtualenv")
        else:
            fixes_failed.append(f"Virtualenv: {msg}")

    # Fix 2: Install deps if venv exists
    if venv_dir.exists():
        ok, msg = step4_install_deps()
        if ok:
            fixes_applied.append("Installed dependencies")
        else:
            fixes_failed.append(f"Dependencies: {msg}")

    # Fix 3: Try to install awp-wallet if missing
    if not shutil.which("awp-wallet") and shutil.which("npm"):
        ok, msg = attempt_install_awp_wallet()
        if ok:
            fixes_applied.append(msg)
        else:
            fixes_failed.append(f"awp-wallet: {msg}")

    # Fix 4: Set default env vars if missing
    env_fixed = []
    if not os.environ.get("PLATFORM_BASE_URL"):
        os.environ["PLATFORM_BASE_URL"] = DEFAULT_URL
        env_fixed.append(f"PLATFORM_BASE_URL={DEFAULT_URL}")

    if not os.environ.get("MINER_ID"):
        os.environ["MINER_ID"] = DEFAULT_MINER_ID
        env_fixed.append(f"MINER_ID={DEFAULT_MINER_ID}")

    if env_fixed:
        fixes_applied.append(f"Set env vars: {', '.join(env_fixed)}")

    if fixes_failed:
        return output_error(
            f"Some fixes failed: {'; '.join(fixes_failed)}",
            fix_command="python scripts/mine_setup.py",
            fixes_applied=fixes_applied,
        )

    if fixes_applied:
        return output_success(
            f"Applied {len(fixes_applied)} fix(es)",
            fixes_applied=fixes_applied,
            next_command="python scripts/mine_setup.py --status",
        )

    return output_success("Nothing to fix - everything looks good!", next_command="python scripts/run_tool.py agent-start")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Mine Setup Wizard")
    parser.add_argument("--status", action="store_true", help="Check current setup status")
    parser.add_argument("--fix", action="store_true", help="Auto-fix detected issues")
    parser.add_argument("--step", type=int, help="Run specific step (1-6)")
    parser.add_argument("--reset", action="store_true", help="Reset setup state")
    args = parser.parse_args()

    try:
        if args.reset:
            SetupState().reset()
            return output_success("Setup state reset.", next_command="python scripts/mine_setup.py").get("status") != "error"

        if args.status:
            result = check_status()
            return 0 if result.get("status") == "success" else 1

        if args.fix:
            result = auto_fix()
            return 0 if result.get("status") == "success" else 1

        if args.step:
            # Run specific step
            state = SetupState.load()
            steps = {
                1: ("Python", step1_check_python),
                2: ("Node.js", step2_check_node),
                3: ("Virtualenv", step3_setup_venv),
                4: ("Dependencies", step4_install_deps),
                5: ("Wallet", lambda: step5_setup_wallet()[:2]),
                6: ("Environment", lambda: step6_configure_env(state)[:2]),
            }
            if args.step not in steps:
                output_error(f"Invalid step {args.step}. Valid: 1-6")
                return 1
            name, func = steps[args.step]
            ok, msg = func()
            if ok:
                output_success(f"Step {args.step} ({name}): {msg}")
                return 0
            else:
                output_error(f"Step {args.step} ({name}): {msg}")
                return 1

        # Default: run full setup
        result = run_full_setup()
        return 0 if result.get("status") == "success" else 1

    except KeyboardInterrupt:
        output_error("Setup interrupted")
        return 130
    except Exception as e:
        output_error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
