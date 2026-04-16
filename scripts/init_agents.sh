#!/bin/bash

# init_agents.sh - Initializes agent specific directories and .env files.
# This script should be run after setup.sh.

# Define paths relative to this script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"

AGENTS_DIR="$PROJECT_ROOT/agents"
GLOBAL_CONFIG_ENV="$PROJECT_ROOT/config/.env"
AGENT_CONFIG_EXAMPLE="$PROJECT_ROOT/config/agents.json.example"

echo "=== Initializing AWP Agents ==="

# 1. Source global configuration
if [ -f "$GLOBAL_CONFIG_ENV" ]; then
    source "$GLOBAL_CONFIG_ENV"
    echo "Global configuration loaded from config/.env."
else
    echo "Warning: Global config file config/.env not found. Please copy config/.env.example to config/.env and fill it."
    exit 1
fi

# Ensure ~/.local/bin is in PATH for awp-wallet if needed (if installed globally)
export PATH=$HOME/.local/bin:$PATH

# 2. Read agent IDs from agents.json.example (or a proper agents.json)
AGENT_IDS=$(jq -r '.[] | .agent_id' "$AGENT_CONFIG_EXAMPLE")

if [ -z "$AGENT_IDS" ]; then # AGENT_IDS should be like "agent-01 agent-02 ..."
    echo "Error: No agent IDs found in $AGENT_CONFIG_EXAMPLE. Please check the file."
    exit 1
fi

# 3. Initialize each agent
for AGENT_ID in $AGENT_IDS; do
    AGENT_PATH="$AGENTS_DIR/$AGENT_ID"
    AGENT_ENV_FILE="$AGENT_PATH/.env"
    AGENT_HOME_DIR="$AGENT_PATH/home"
    AGENT_STATE_DIR="$AGENT_PATH/state"
    AGENT_LOGS_DIR="$AGENT_PATH/logs"

    echo "\n--- Setting up Agent: $AGENT_ID ---"
    rm -rf "$AGENT_HOME_DIR" # Clean up any existing wallet data
    mkdir -p "$AGENT_HOME_DIR"
    mkdir -p "$AGENT_STATE_DIR"
    mkdir -p "$AGENT_LOGS_DIR"

    echo "Agent directories created: $AGENT_PATH"

    PRIV_KEY=""
    AWP_ADDRESS=""

    # Check if awp-wallet CLI is available for key generation
    if command -v awp-wallet &> /dev/null; then
        read -p "Enter AWP Private Key for $AGENT_ID (or leave blank to GENERATE a new one): " USER_PRIV_KEY
        if [ -z "$USER_PRIV_KEY" ]; then
            echo "Generating new wallet for $AGENT_ID..."
            # Use agent-specific HOME for wallet generation
            TEMP_HOME="$AGENT_HOME_DIR" awp-wallet init > /dev/null 2>&1
            if [ $? -eq 0 ]; then
                EXPORT_JSON=$(TEMP_HOME="$AGENT_HOME_DIR" awp-wallet export-private-key)
                PRIV_KEY=$(echo "$EXPORT_JSON" | jq -r .privateKey)
                AWP_ADDRESS=$(echo "$EXPORT_JSON" | jq -r .address)
                echo "Generated Wallet Address: $AWP_ADDRESS"
            else
                echo "Error: awp-wallet init failed. Please check awp-wallet installation."
                exit 1
            fi
        else
            PRIV_KEY="$USER_PRIV_KEY"
            # Try to get address from provided key
            AWP_ADDRESS=$(AWP_PRIVATE_KEY="$PRIV_KEY" awp-wallet status 2>/dev/null | grep Address | awk '{print $2}' || echo "N/A")
            echo "Using provided Private Key. Address: $AWP_ADDRESS"
        fi
    else
        echo "Warning: 'awp-wallet' CLI not found. You will need to manually provide AWP_PRIVATE_KEY and AWP_ADDRESS."
        read -p "Enter AWP Private Key for $AGENT_ID: " PRIV_KEY
        read -p "Enter AWP Address for $AGENT_ID: " AWP_ADDRESS
    fi

    # Create agent-specific .env file
    cat <<EOF > "$AGENT_ENV_FILE"
AWP_PRIVATE_KEY="$PRIV_KEY"
AWP_ADDRESS="$AWP_ADDRESS"
WORKER_STATE_ROOT="$AGENT_STATE_DIR"
PLATFORM_BASE_URL="$PLATFORM_BASE_URL"
MINER_ID="$AGENT_ID"
WORKER_MAX_PARALLEL="$WORKER_MAX_PARALLEL"
DATASET_REFRESH_SECONDS="$DATASET_REFRESH_SECONDS"
OPENAI_BASE_URL="$OPENAI_BASE_URL"
OPENAI_API_KEY="$OPENAI_API_KEY"
PREDICT_MODEL="$PREDICT_MODEL"
OPENAI_MODEL="$OPENAI_MODEL"
ENABLE_MINER="false" # Miner is disabled by default for newly created agents
EOF
    echo "Agent .env file created at $AGENT_ENV_FILE"

done

echo "\n=== Agent Initialization Complete ==="
echo "Remember to register your new agents with the AWP platform if needed."
