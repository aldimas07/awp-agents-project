#!/bin/bash

# start_all_agents.sh - Starts all AWP agents (watchdog, logger, and predict agents).

# Define paths relative to this script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
SCRIPTS_DIR="$PROJECT_ROOT/scripts"
PIDS_DIR="$PROJECT_ROOT/data/pids"
DATA_DIR="$PROJECT_ROOT/data"
WATCHDOG_SCRIPT="$PROJECT_ROOT/src/python/watchdog/awp-watchdog.py"
CSV_LOGGER_SCRIPT="$PROJECT_ROOT/src/python/prediction_tracker/csv_logger.py"
HIVE_AGENT_MANAGER="$SCRIPTS_DIR/hive.sh"

# Log files for background processes
WATCHDOG_LOG_FILE="$PROJECT_ROOT/data/awp-watchdog.log"
CSV_LOGGER_LOG_FILE="$PROJECT_ROOT/data/csv_logger.log"

echo "=== Starting All AWP Agents (awp-agents-project) ==="

# Ensure PID directory exists
mkdir -p "$PIDS_DIR"

# 1. Source global .env for base settings
if [ -f "$PROJECT_ROOT/config/.env" ]; then
    source "$PROJECT_ROOT/config/.env"
    echo "Global configuration loaded from config/.env."
else
    echo "Warning: config/.env not found."
fi

# 2. Start Watchdog
echo -e "\n--- Starting Watchdog ---"
pkill -f "awp-watchdog.py" 2>/dev/null
nohup python3 "$WATCHDOG_SCRIPT" > "$WATCHDOG_LOG_FILE" 2>&1 &
WATCHDOG_PID=$!
echo "$WATCHDOG_PID" > "$PIDS_DIR/watchdog.pid"
echo "Watchdog started with PID: $WATCHDOG_PID"

# 3. Start CSV Logger
echo -e "\n--- Starting CSV Logger ---"
pkill -f "csv_logger.py" 2>/dev/null
nohup python3 "$CSV_LOGGER_SCRIPT" > "$CSV_LOGGER_LOG_FILE" 2>&1 &
CSV_LOGGER_PID=$!
echo "$CSV_LOGGER_PID" > "$PIDS_DIR/csv_logger.pid"
echo "CSV Logger started with PID: $CSV_LOGGER_PID"

# 4. Start All Agents
echo -e "\n--- Starting All AWP Agents (Predict & Mine) ---"

for i in $(seq -w 1 50); do
    AGENT_ID="agent-$i"

    # Skip if agent directory or .env doesn't exist
    if [ ! -f "$PROJECT_ROOT/agents/$AGENT_ID/.env" ]; then
        continue
    fi

    # Check MONITOR_AGENT flag
    MONITOR=$(grep "^MONITOR_AGENT=" "$PROJECT_ROOT/agents/$AGENT_ID/.env" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    if [ "$MONITOR" == "false" ]; then
        echo "  Skipping $AGENT_ID - MONITOR_AGENT=false"
        continue
    fi

    INTERVAL=$(shuf -i 110-125 -n 1)
    echo "  Starting $AGENT_ID with interval ${INTERVAL}s..."
    "$HIVE_AGENT_MANAGER" start "$AGENT_ID" "$INTERVAL"
    sleep 5
done

sleep 2
echo -e "\n=== All Agents Started ==="
"$HIVE_AGENT_MANAGER" status
