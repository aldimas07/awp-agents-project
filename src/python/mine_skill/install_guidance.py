from __future__ import annotations


def awp_wallet_install_steps() -> list[str]:
    """Return the single supported manual install path for awp-wallet."""
    return [
        "git clone https://github.com/awp-core/awp-wallet.git",
        "cd awp-wallet",
        "npm install",
        "npm install -g .",
    ]


def awp_wallet_install_hint() -> str:
    return "Install awp-wallet from GitHub (not @aspect/awp-wallet)"
