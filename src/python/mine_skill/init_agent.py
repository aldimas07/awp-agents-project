#!/usr/bin/env python3
"""One-command initialization for Mine agent.

Usage:
    python scripts/init_agent.py [--mainnet]

This script:
1. Installs dependencies (if needed)
2. Installs awp-wallet (if needed)
3. Creates/unlocks wallet
4. Auto-detects and configures API (testnet/mainnet)
5. Attempts registration
6. Starts mining

Agent just needs to run this once and everything is ready.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Add parent to path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from common import (
    WALLET_SESSION_DURATION_SECONDS,
    resolve_awp_api_base_url,
    resolve_awp_registration,
    resolve_wallet_bin,
    resolve_wallet_config,
)


def print_step(msg: str) -> None:
    """Print a step message."""
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print('='*60)


def print_ok(msg: str) -> None:
    """Print success message."""
    print(f"✓ {msg}")


def print_warn(msg: str) -> None:
    """Print warning message."""
    print(f"⚠ {msg}")


def print_error(msg: str) -> None:
    """Print error message."""
    print(f"✗ {msg}")


def check_python_version() -> bool:
    """Check Python version >= 3.11."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print_error(f"Python 3.11+ required, found {version.major}.{version.minor}")
        return False
    print_ok(f"Python {version.major}.{version.minor}")
    return True


def run_bootstrap() -> bool:
    """Run bootstrap script."""
    print_step("Step 1: Installing dependencies")

    if os.name == 'nt':
        bootstrap = SCRIPT_DIR / "bootstrap.ps1"
        cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(bootstrap)]
    else:
        bootstrap = SCRIPT_DIR / "bootstrap.sh"
        cmd = ["bash", str(bootstrap)]

    try:
        subprocess.run(cmd, check=True, cwd=SKILL_ROOT)
        print_ok("Dependencies installed")
        return True
    except subprocess.CalledProcessError:
        print_error("Bootstrap failed")
        return False


def setup_wallet() -> tuple[str, str] | None:
    """Setup and unlock wallet. Returns (wallet_bin, session_token)."""
    print_step("Step 2: Setting up wallet")

    wallet_bin = resolve_wallet_bin()

    # Check if awp-wallet exists
    if not (Path(wallet_bin).exists() or subprocess.run(
        ["which", wallet_bin], capture_output=True
    ).returncode == 0):
        print_error("awp-wallet not found - bootstrap should have installed it")
        return None

    print_ok(f"awp-wallet found: {wallet_bin}")

    # Get wallet address
    try:
        result = subprocess.run(
            [wallet_bin, "receive"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            # Try to initialize
            subprocess.run([wallet_bin, "init"], check=True, timeout=30)
            result = subprocess.run(
                [wallet_bin, "receive"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True
            )

        wallet_data = json.loads(result.stdout)
        address = wallet_data.get("eoaAddress", "")
        print_ok(f"Wallet address: {address}")
    except Exception as e:
        print_error(f"Failed to get wallet address: {e}")
        return None

    # Unlock wallet
    try:
        result = subprocess.run(
            [wallet_bin, "unlock", "--duration", str(WALLET_SESSION_DURATION_SECONDS), "--scope", "full"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )
        unlock_data = json.loads(result.stdout)
        session_token = unlock_data.get("sessionToken", "")
        print_ok("Wallet unlocked (1 hour session)")
        return wallet_bin, session_token
    except Exception as e:
        print_warn(f"Wallet unlock warning: {e}")
        # Try to get existing session
        _, token = resolve_wallet_config()
        if token:
            print_ok("Using existing wallet session")
            return wallet_bin, token
        return None


def configure_api(use_mainnet: bool = False) -> str:
    """Configure API endpoint. Returns base URL."""
    print_step("Step 3: Configuring API endpoint")

    if use_mainnet:
        api_url = "https://api.awp.sh/api"
        print_ok("Using Mainnet API")
        print_warn("Mainnet requires AWP tokens for registration")
    else:
        api_url = "https://tapi.awp.sh/api"
        print_ok("Using Testnet API (free registration)")

    # Set environment variable
    os.environ["AWP_API_URL"] = api_url

    # Persist to .env if it exists
    env_file = SKILL_ROOT / ".env"
    if env_file.exists():
        lines = env_file.read_text().splitlines()
        new_lines = [l for l in lines if not l.startswith("AWP_API_URL=")]
        new_lines.append(f"AWP_API_URL={api_url}")
        env_file.write_text("\n".join(new_lines) + "\n")
        print_ok(f"Saved to .env: AWP_API_URL={api_url}")

    return api_url


def attempt_registration() -> dict:
    """Attempt AWP registration. Returns status dict."""
    print_step("Step 4: Registering on AWP")

    result = resolve_awp_registration(auto_register=True)

    if result.get("registered"):
        print_ok(f"Registered: {result.get('wallet_address')}")
        return result

    status = result.get("status", "")
    message = result.get("message", "")

    if "relayer has insufficient" in message.lower():
        print_warn("Testnet relayer is out of gas")
        print("  → AWP team needs to refill the relayer")
        print("  → Registration will auto-complete when relayer is restored")
        print("  → You can still start agent-start, it will retry registration")
    elif "insufficient AWP balance" in message:
        print_error("AWP token balance required for registration")
        print("  → Switch to testnet: python scripts/init_agent.py")
        print("  → Or get AWP tokens for mainnet")
    else:
        print_warn(f"Registration status: {status}")
        print(f"  → {message}")

    return result


def start_mining() -> bool:
    """Start the mining agent."""
    print_step("Step 5: Starting mining agent")

    try:
        # Use run_tool.py agent-start
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "run_tool.py"), "agent-start"],
            cwd=SKILL_ROOT,
            timeout=60
        )
        if result.returncode == 0:
            print_ok("Mining agent started")
            return True
        else:
            print_warn("Agent start returned non-zero exit code")
            print("  → Check status: python scripts/run_tool.py agent-control status")
            return False
    except subprocess.TimeoutExpired:
        print_ok("Mining agent started (running in background)")
        return True
    except Exception as e:
        print_error(f"Failed to start agent: {e}")
        return False


def main() -> int:
    """Main initialization flow."""
    use_mainnet = "--mainnet" in sys.argv

    print("\n" + "="*60)
    print("  Mine Agent - One-Command Initialization")
    print("="*60)

    # Step 0: Check Python version
    if not check_python_version():
        return 1

    # Step 1: Run bootstrap
    if not run_bootstrap():
        print_error("\nInitialization failed at bootstrap step")
        return 1

    # Step 2: Setup wallet
    wallet_setup = setup_wallet()
    if not wallet_setup:
        print_error("\nInitialization failed at wallet setup")
        return 1

    # Step 3: Configure API
    api_url = configure_api(use_mainnet)

    # Step 4: Attempt registration
    reg_result = attempt_registration()

    # Step 5: Start mining (even if registration pending)
    # Agent will retry registration automatically
    if not start_mining():
        print_warn("\nAgent started with warnings")
        print("\nNext steps:")
        print("  1. Check status: python scripts/run_tool.py agent-control status")
        print("  2. View logs: check output/agent-runs/ directory")
        return 0

    # Success summary
    print("\n" + "="*60)
    print("  ✓ Initialization Complete")
    print("="*60)
    print(f"\nWallet: {reg_result.get('wallet_address', 'N/A')}")
    print(f"API: {api_url}")
    print(f"Registered: {reg_result.get('registered', False)}")
    print("\nAgent is now running in background.")
    print("\nUseful commands:")
    print("  python scripts/run_tool.py agent-control status")
    print("  python scripts/run_tool.py agent-control pause")
    print("  python scripts/run_tool.py agent-control resume")
    print("  python scripts/run_tool.py agent-control stop")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
