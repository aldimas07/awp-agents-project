#!/usr/bin/env python3
"""Post-install check and auto-fix for mine skill.

This script runs after skill installation to ensure all dependencies
are properly installed, including awp-wallet.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import (
    DEFAULT_MINER_ID,
    DEFAULT_PLATFORM_BASE_URL,
    format_wallet_bin_display,
    resolve_awp_registration,
    resolve_runtime_readiness,
    resolve_signature_config,
    resolve_wallet_bin,
    resolve_wallet_config,
)
from install_guidance import awp_wallet_install_steps


def check_python_version() -> tuple[bool, str]:
    """Check Python version (needs 3.11+)."""
    major, minor = sys.version_info.major, sys.version_info.minor
    if major < 3 or (major == 3 and minor < 11):
        return False, f"Python {major}.{minor} found, but 3.11+ required"
    return True, f"Python {major}.{minor}"


def check_node_installed() -> tuple[bool, str]:
    """Check if Node.js is installed."""
    node_bin = shutil.which("node") or shutil.which("nodejs")
    if not node_bin:
        return False, "Node.js not found"

    try:
        result = subprocess.run([node_bin, "--version"], capture_output=True, text=True, timeout=5)
        version = result.stdout.strip()
        return True, f"Node.js {version}"
    except Exception as e:
        return False, f"Node.js check failed: {e}"


def check_npm_installed() -> tuple[bool, str]:
    """Check if npm is installed."""
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return False, "npm not found"

    try:
        result = subprocess.run([npm_bin, "--version"], capture_output=True, text=True, timeout=5)
        version = result.stdout.strip()
        return True, f"npm {version}"
    except Exception as e:
        return False, f"npm check failed: {e}"


def check_awp_wallet_installed() -> tuple[bool, str]:
    """Check if awp-wallet is installed."""
    wallet_bin = resolve_wallet_bin()

    if not (shutil.which(wallet_bin) or Path(wallet_bin).exists()):
        return False, "awp-wallet not found"

    try:
        result = subprocess.run([wallet_bin, "--version"], capture_output=True, text=True, timeout=5)
        version = result.stdout.strip()
        return True, f"{format_wallet_bin_display(wallet_bin)} {version}"
    except Exception as e:
        return False, f"awp-wallet check failed: {e}"


def check_venv_exists() -> tuple[bool, str]:
    """Check if Python virtualenv exists."""
    venv_dir = Path(".venv")
    if not venv_dir.exists():
        return False, "Virtual environment not found"

    if sys.platform == "win32":
        python_bin = venv_dir / "Scripts" / "python.exe"
    else:
        python_bin = venv_dir / "bin" / "python"

    if not python_bin.exists():
        return False, "Virtual environment incomplete"

    return True, f"Virtual environment at {venv_dir}"


def check_env_vars() -> tuple[bool, str, list[str]]:
    """Check effective environment/runtime defaults using unified readiness contract.

    Aligned with mine_setup semantics: success = can_start (registration can be deferred).
    """
    readiness = resolve_runtime_readiness()
    signature_config = readiness.get("signature_config", {})
    registration = readiness.get("registration", {})

    notes = [
        f"state={readiness['state']}",
        f"can_start={readiness['can_start']}",
        f"can_mine={readiness['can_mine']}",
        f"PLATFORM_BASE_URL={readiness['platform_base_url']}",
        f"MINER_ID={readiness['miner_id']}",
        f"wallet_bin={format_wallet_bin_display(readiness['wallet_bin'])}",
        f"signature_config={readiness['signature_config_origin']}:{signature_config.get('domain_name')}/{signature_config.get('chain_id')}",
        f"registration={registration.get('status')}",
    ]

    # Add warnings from unified readiness
    if readiness.get("warnings"):
        notes.extend(readiness["warnings"])

    # Aligned with mine_setup: success = can_start (registration is deferred)
    if readiness["can_start"]:
        return True, ", ".join(notes), []

    # Not ready - determine what's missing
    missing = []
    if not readiness["wallet_found"]:
        missing.append("AWP_WALLET")
    elif not readiness["wallet_session_ready"]:
        missing.append("AWP_WALLET_SESSION")

    return False, ", ".join(notes), missing


def _resolve_awp_wallet_version(git_bin: str) -> str:
    """Resolve awp-wallet version: env override > latest tag > main."""
    version = os.environ.get("AWP_WALLET_VERSION", "").strip()
    if version:
        return version
    try:
        result = subprocess.run(
            [git_bin, "ls-remote", "--tags", "--sort=-v:refname",
             "https://github.com/awp-core/awp-wallet.git"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            import re
            match = re.search(r"v\d+\.\d+\.\d+", result.stdout)
            if match:
                return match.group(0)
    except Exception:
        pass
    return "main"


def attempt_install_awp_wallet() -> tuple[bool, str]:
    """Try to install awp-wallet from the supported GitHub source with version pinning."""
    npm_bin = shutil.which("npm")
    git_bin = shutil.which("git")
    if not npm_bin:
        return False, "npm not available - cannot install awp-wallet"
    if not git_bin:
        return False, "git not available - cannot install awp-wallet"

    try:
        version = _resolve_awp_wallet_version(git_bin)
        print(f"  Installing awp-wallet {version} from GitHub...")
        with tempfile.TemporaryDirectory(prefix="awp-wallet-install-") as temp_dir:
            clone_result = subprocess.run(
                [git_bin, "clone", "--branch", version, "--depth", "1",
                 "https://github.com/awp-core/awp-wallet.git", temp_dir],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if clone_result.returncode != 0:
                return False, f"git clone failed: {clone_result.stderr.strip()}"

            install_result = subprocess.run(
                [npm_bin, "install"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=temp_dir,
            )
            if install_result.returncode != 0:
                return False, f"npm install failed: {install_result.stderr.strip()}"

            global_result = subprocess.run(
                [npm_bin, "install", "-g", "."],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=temp_dir,
            )
            if global_result.returncode != 0:
                return False, f"npm install -g . failed: {global_result.stderr.strip()}"

        ok, msg = check_awp_wallet_installed()
        if ok:
            return True, f"awp-wallet {version} installed successfully from GitHub"
        return False, f"Installation completed but verification failed: {msg}"

    except subprocess.TimeoutExpired:
        return False, "awp-wallet installation timed out"
    except Exception as e:
        return False, f"Installation failed: {e}"


def attempt_create_venv() -> tuple[bool, str]:
    """Try to create Python virtualenv."""
    venv_dir = Path(".venv")
    if venv_dir.exists():
        return True, "Virtual environment already exists"

    try:
        print("  Creating Python virtual environment...")

        # Try uv first
        uv_bin = shutil.which("uv")
        if uv_bin:
            result = subprocess.run([uv_bin, "venv", "--seed", str(venv_dir)], capture_output=True, timeout=60)
            if result.returncode == 0:
                return True, "Virtual environment created with uv"

        # Fall back to python -m venv
        python_bin = sys.executable
        result = subprocess.run([python_bin, "-m", "venv", str(venv_dir)], capture_output=True, timeout=60)

        if result.returncode == 0:
            return True, "Virtual environment created"
        else:
            return False, f"venv creation failed: {result.stderr.decode()}"

    except Exception as e:
        return False, f"Failed to create venv: {e}"


def attempt_install_python_deps() -> tuple[bool, str]:
    """Try to install Python dependencies."""
    venv_dir = Path(".venv")
    if not venv_dir.exists():
        return False, "Virtual environment not found"

    if sys.platform == "win32":
        python_bin = venv_dir / "Scripts" / "python.exe"
    else:
        python_bin = venv_dir / "bin" / "python"

    if not python_bin.exists():
        return False, "Python binary not found in venv"

    try:
        print("  Installing Python dependencies...")
        result = subprocess.run(
            [str(python_bin), "-m", "pip", "install", "-r", "requirements-core.txt"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            return True, "Python dependencies installed"
        else:
            return False, f"pip install failed: {result.stderr}"

    except Exception as e:
        return False, f"Failed to install dependencies: {e}"


def set_default_env_vars() -> tuple[bool, str, list[str]]:
    """Set process-local defaults aligned with runtime behavior."""
    set_vars = []

    if not os.environ.get("PLATFORM_BASE_URL"):
        default_url = DEFAULT_PLATFORM_BASE_URL
        os.environ["PLATFORM_BASE_URL"] = default_url
        set_vars.append(f"PLATFORM_BASE_URL={default_url}")

    if not os.environ.get("MINER_ID"):
        default_id = DEFAULT_MINER_ID
        os.environ["MINER_ID"] = default_id
        set_vars.append(f"MINER_ID={default_id}")

    if set_vars:
        return True, f"Set: {', '.join(set_vars)}", set_vars

    return True, "No defaults needed", []


def main():
    """Run post-install checks and auto-fix."""
    print("=" * 80)
    print("Mine Skill - Post-Install Check")
    print("=" * 80)
    print()

    checks = []
    fixes_needed = []

    # Check 1: Python version
    ok, msg = check_python_version()
    checks.append({"name": "Python version", "ok": ok, "message": msg})
    if not ok:
        print(f"❌ Python version: {msg}")
        print("   FIX: Install Python 3.11+ from https://python.org")
        sys.exit(1)
    else:
        print(f"✓ Python version: {msg}")

    # Check 2: Node.js
    ok, msg = check_node_installed()
    checks.append({"name": "Node.js", "ok": ok, "message": msg})
    if not ok:
        print(f"⚠ Node.js: {msg}")
        print("   FIX: Install Node.js from https://nodejs.org")
        fixes_needed.append("install_nodejs")
    else:
        print(f"✓ Node.js: {msg}")

    # Check 3: npm
    ok, msg = check_npm_installed()
    checks.append({"name": "npm", "ok": ok, "message": msg})
    if not ok:
        print(f"⚠ npm: {msg}")
        fixes_needed.append("install_npm")
    else:
        print(f"✓ npm: {msg}")

    # Check 4: awp-wallet
    ok, msg = check_awp_wallet_installed()
    checks.append({"name": "awp-wallet", "ok": ok, "message": msg})
    if not ok:
        print(f"⚠ awp-wallet: {msg}")
        fixes_needed.append("install_awp_wallet")
    else:
        print(f"✓ awp-wallet: {msg}")

    # Check 5: Virtual environment
    ok, msg = check_venv_exists()
    checks.append({"name": "Virtual environment", "ok": ok, "message": msg})
    if not ok:
        print(f"⚠ Virtual environment: {msg}")
        fixes_needed.append("create_venv")
    else:
        print(f"✓ Virtual environment: {msg}")

    # Check 6: Environment variables
    ok, msg, missing = check_env_vars()
    checks.append({"name": "Environment variables", "ok": ok, "message": msg})
    if not ok:
        print(f"⚠ Environment variables: {msg}")
        fixes_needed.append("set_env_vars")
    else:
        print(f"✓ Environment variables: {msg}")

    print()

    # Auto-fix
    if fixes_needed:
        print("=" * 80)
        print("Attempting Auto-Fix")
        print("=" * 80)
        print()

        fixes_applied = []
        fixes_failed = []

        # Fix: Install awp-wallet
        if "install_awp_wallet" in fixes_needed:
            print("→ Installing awp-wallet...")
            ok, msg = attempt_install_awp_wallet()
            if ok:
                fixes_applied.append(f"awp-wallet: {msg}")
                print(f"  ✓ {msg}")
            else:
                fixes_failed.append(f"awp-wallet: {msg}")
                print(f"  ✗ {msg}")

        # Fix: Create venv
        if "create_venv" in fixes_needed:
            print("→ Creating virtual environment...")
            ok, msg = attempt_create_venv()
            if ok:
                fixes_applied.append(f"venv: {msg}")
                print(f"  ✓ {msg}")

                # Also install dependencies
                ok2, msg2 = attempt_install_python_deps()
                if ok2:
                    fixes_applied.append(f"dependencies: {msg2}")
                    print(f"  ✓ {msg2}")
                else:
                    fixes_failed.append(f"dependencies: {msg2}")
                    print(f"  ✗ {msg2}")
            else:
                fixes_failed.append(f"venv: {msg}")
                print(f"  ✗ {msg}")

        # Fix: Set defaults / auto-managed session
        if "set_env_vars" in fixes_needed:
            print("→ Applying runtime defaults and restoring wallet session...")
            ok, msg, set_vars = set_default_env_vars()
            if ok:
                fixes_applied.append(f"env: {msg}")
                print(f"  ✓ {msg}")
                for var in set_vars:
                    print(f"    {var}")
            else:
                fixes_failed.append(f"env: {msg}")
                print(f"  ✗ {msg}")

        print()

        # Summary
        if fixes_applied:
            print("✓ Fixes applied:")
            for fix in fixes_applied:
                print(f"  - {fix}")
            print()

        if fixes_failed:
            print("✗ Fixes failed:")
            for fix in fixes_failed:
                print(f"  - {fix}")
            print()
            print("=" * 80)
            print("Manual Fix Required")
            print("=" * 80)
            print()

            if "install_nodejs" in fixes_needed or "install_npm" in fixes_needed:
                print("1. Install Node.js:")
                print("   https://nodejs.org")
                print()

            if "install_awp_wallet" in fixes_needed and "awp-wallet" in str(fixes_failed):
                print("2. Install awp-wallet manually:")
                for step in awp_wallet_install_steps():
                    print(f"   {step}")
                print()

            print("Then re-run:")
            print("   python scripts/post_install_check.py")
            print()

            sys.exit(1)

    print("=" * 80)
    print("✓ All checks passed!")
    print("=" * 80)
    print()
    print("Next steps:")
    print("  1. Check readiness:  python scripts/run_tool.py agent-status")
    print("  2. Start mining:     python scripts/run_tool.py agent-start")
    print("  3. Inspect status:   python scripts/run_tool.py agent-control status")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
