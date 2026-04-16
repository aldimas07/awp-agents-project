#!/bin/bash

# setup.sh - Initial setup script for AWP Agents Project
# This script is designed to be run from the project root: ./scripts/setup.sh
# This script prepares the environment, builds Rust binaries, and installs Python dependencies.

# Define paths relative to this script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
RUST_PREDICT_SKILL_DIR="$PROJECT_ROOT/src/rust/prediction-skill"
PYTHON_VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON_REQUIREMENTS="$PROJECT_ROOT/src/python/requirements.txt"
AWP_WALLET_INSTALL_DIR="$HOME/.local/bin" # Where awp-wallet will be installed
LOCAL_BIN_DIR="$HOME/.local/bin" # Where predict-agent will be copied

echo "=== AWP Agents Project Setup ==="

# 1. Build Rust predict-agent binary
echo "\n--- Building Rust predict-agent binary ---"
if [ -d "$RUST_PREDICT_SKILL_DIR" ]; then
    cd "$RUST_PREDICT_SKILL_DIR" || { echo "Error: Could not change to Rust project directory."; exit 1; }
    cargo build --release
    if [ $? -eq 0 ]; then
        echo "Rust predict-agent built successfully."
        # Ensure ~/.local/bin exists and copy the binary there
        mkdir -p "$LOCAL_BIN_DIR"
        cp "target/release/predict-agent" "$LOCAL_BIN_DIR/predict-agent"
        # Add LOCAL_BIN_DIR to PATH for current session if not already there
        if [[ ":$PATH:" != *":$LOCAL_BIN_DIR:"* ]]; then
            export PATH="$LOCAL_BIN_DIR:$PATH"
        fi
        echo "predict-agent copied to $LOCAL_BIN_DIR/"
    else
        echo "Error: Rust predict-agent build failed. Please check Rust installation and project configuration."
        exit 1
    fi
    cd "$PROJECT_ROOT" || exit 1
else
    echo "Warning: Rust prediction-skill directory not found at $RUST_PREDICT_SKILL_DIR. Skipping Rust build."
fi

# 2. Setup Python Virtual Environment and install dependencies
echo "\n--- Setting up Python Virtual Environment ---"
if [ ! -d "$PYTHON_VENV_DIR" ]; then
    echo "Creating Python virtual environment at $PYTHON_VENV_DIR..."
    python3 -m venv "$PYTHON_VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create Python virtual environment. Ensure python3-venv is installed."
        exit 1
    fi
else
    echo "Python virtual environment already exists at $PYTHON_VENV_DIR."
fi

echo "Activating virtual environment..."
source "$PYTHON_VENV_DIR/bin/activate"

echo "Installing Python dependencies..."
pip install --no-cache-dir -r "$PYTHON_REQUIREMENTS"
if [ $? -eq 0 ]; then
    echo "Python dependencies installed successfully."
else
    echo "Error: Failed to install Python dependencies. Please check $PYTHON_REQUIREMENTS."
    exit 1
fi

# 3. Install awp-wallet CLI dependency
echo "\n--- Installing AWP Wallet CLI ---"
if ! command -v awp-wallet &> /dev/null; then
    echo "awp-wallet not found. Installing from github.com/awp-core/awp-wallet..."
    TEMP_WALLET_INSTALL_DIR="/tmp/awp-wallet-install"
    rm -rf "$TEMP_WALLET_INSTALL_DIR"
    git clone https://github.com/awp-core/awp-wallet.git "$TEMP_WALLET_INSTALL_DIR"
    if [ $? -eq 0 ]; then
        cd "$TEMP_WALLET_INSTALL_DIR" || { echo "Error: Could not change to temporary wallet install directory."; exit 1; }
        bash install.sh # This script typically installs to ~/.local/bin
        if [ $? -eq 0 ]; then
            echo "AWP Wallet CLI installed successfully."
            # Ensure AWP_WALLET_INSTALL_DIR is in PATH for current session
            if [[ ":$PATH:" != *":$AWP_WALLET_INSTALL_DIR:"* ]]; then
                export PATH="$AWP_WALLET_INSTALL_DIR:$PATH"
                echo "Added $AWP_WALLET_INSTALL_DIR to PATH for this session."
            fi
        else
            echo "Error: AWP Wallet install.sh failed. Please check its repository for troubleshooting."
            exit 1
        fi
        cd "$PROJECT_ROOT" || exit 1
        rm -rf "$TEMP_WALLET_INSTALL_DIR"
    else
        echo "Error: Failed to clone awp-core/awp-wallet. Check your network connection."
        exit 1
    fi
else
    echo "AWP Wallet CLI is already installed."
    # Ensure it's in PATH for current session
    if command -v awp-wallet &> /dev/null; then
        AWP_WALLET_PATH=$(command -v awp-wallet)
        if [[ ":$PATH:" != *":$(dirname "$AWP_WALLET_PATH"):"* ]]; then
            export PATH="$(dirname "$AWP_WALLET_PATH"):$PATH"
            echo "Added $(dirname "$AWP_WALLET_PATH") to PATH for this session."
        fi
    fi
fi

# 4. Check for jq (required by hive.sh and other scripts)
echo "\n--- Checking for jq ---"
if ! command -v jq &> /dev/null
then
    echo "Warning: 'jq' is not installed. It is required by some scripts. Please install it (e.g., sudo apt install jq)."
else
    echo "'jq' is installed."
fi

# 5. Check for awp-wallet (required by init_agents.sh)
echo "\n--- Checking for awp-wallet ---"
if ! command -v awp-wallet &> /dev/null
then
    echo "Warning: 'awp-wallet' CLI not found. It is required by init_agents.sh to generate/manage agent wallets. Please install it if needed."
    echo "  Installation instructions can be found in the AWP documentation."
else
    echo "'awp-wallet' CLI is installed."
fi

echo "\n=== Setup Complete ==="
echo "To activate the Python virtual environment in a new shell, run: source $PYTHON_VENV_DIR/bin/activate"
