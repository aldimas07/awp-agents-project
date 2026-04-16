#!/bin/bash

# start_all_agents.sh - Starts all AWP agents (watchdog, logger, and predict agents).

# Define paths relative to this script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
SCRIPTS_DIR="$PROJECT_ROOT/scripts"
PIDS_DIR="$PROJECT_ROOT/data/pids"
DATA_DIR="$PROJECT_ROOT/data"
WATCHDOG_SCRIPT="$PROJECT_ROOT/src/python/watchdog/awp-watchdog.py"
CSV_LOGGER_SCRIPT="$PROJECT_ROOT/src/python/prediction_tracker/csv_logger.py"
AGENT_CONFIG_EXAMPLE="$PROJECT_ROOT/config/agents.json.example"
HIVE_AGENT_MANAGER="$SCRIPTS_DIR/hive.sh"
# PREDICTION_TRACKER_WRAPPER is used internally by hive.sh and should not be directly called here.
STANDALONE_LOG_DIR="$PROJECT_ROOT/agents/agent-06/logs"
STANDALONE_HOME_DIR="$PROJECT_ROOT/agents/agent-06/home"
STANDALONE_ENV_FILE="$PROJECT_ROOT/agents/agent-06/.env"

# Log files for background processes
WATCHDOG_LOG_FILE="$PROJECT_ROOT/data/awp-watchdog.log"
CSV_LOGGER_LOG_FILE="$PROJECT_ROOT/data/csv_logger.log"

echo "=== Starting All AWP Agents ==="

# Ensure PID directory exists
mkdir -p "$PIDS_DIR"

# 1. Source global .env for base settings
if [ -f "$PROJECT_ROOT/config/.env" ]; then
    source "$PROJECT_ROOT/config/.env"
    echo "Global configuration loaded from config/.env."
else
    echo "Error: config/.env not found. Please copy config/.env.example to config/.env and fill it. Cannot start agents."
    exit 1
fi

# 2. Start Watchdog
echo "\n--- Starting Watchdog ---"
nohup python3 "$WATCHDOG_SCRIPT" > "$WATCHDOG_LOG_FILE" 2>&1 &
WATCHDOG_PID=$!
echo "$WATCHDOG_PID" > "$PIDS_DIR/watchdog.pid" # Save PID
echo "Watchdog started with PID: $WATCHDOG_PID, logging to $WATCHDOG_LOG_FILE"

# 3. Start CSV Logger
echo "\n--- Starting CSV Logger ---"
nohup python3 "$CSV_LOGGER_SCRIPT" > "$CSV_LOGGER_LOG_FILE" 2>&1 &
CSV_LOGGER_PID=$!
echo "$CSV_LOGGER_PID" > "$PIDS_DIR/csv_logger.pid" # Save PID
echo "CSV Logger started with PID: $CSV_LOGGER_PID, logging to $CSV_LOGGER_LOG_FILE"

# 4. Start All Agents (Predict and Mine based on their .env config)
echo "\n--- Starting All AWP Agents (Predict & Mine) ---"
# Get all agent IDs (agent-01 to agent-06)
ALL_AGENT_IDS=$(jq -r '.[] | .agent_id' "$AGENT_CONFIG_EXAMPLE")

for AGENT_ID in $ALL_AGENT_IDS; do
    # Get custom interval from agents.json.example, or use a random one if not defined
    CUSTOM_INTERVAL=$(jq -r ".[] | select(.agent_id==\"$AGENT_ID\") | .custom_interval // \"\"" "$AGENT_CONFIG_EXAMPLE")
    INTERVAL=${CUSTOM_INTERVAL:-$(shuf -i 110-125 -n 1)}

    echo "  Starting $AGENT_ID with interval ${INTERVAL}s..."
    # hive.sh will internally use agent_wrapper.sh and source agent-specific .env
    "$HIVE_AGENT_MANAGER" start "$AGENT_ID" "$INTERVAL"
    sleep 1 # Stagger start
done

sleep 2

echo "\n=== All Agents Started ==="

# Optional: Display initial status
"$HIVE_AGENT_MANAGER" status
