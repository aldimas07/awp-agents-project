#!/bin/bash

# stop_all_agents.sh - Stops all running AWP agents and background processes.

# Define paths relative to this script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PIDS_DIR="$PROJECT_ROOT/data/pids"
SCRIPTS_DIR="$PROJECT_ROOT/scripts"
DATA_DIR="$PROJECT_ROOT/data"
HIVE_AGENT_MANAGER="$SCRIPTS_DIR/hive.sh"
AGENT_CONFIG_EXAMPLE="$PROJECT_ROOT/config/agents.json.example"

echo "=== Stopping All AWP Agents ==="

# 1. Stop Watchdog
echo "\n--- Stopping Watchdog ---"
WATCHDOG_PID_FILE="$PIDS_DIR/watchdog.pid"
if [ -f "$WATCHDOG_PID_FILE" ]; then kill $(cat "$WATCHDOG_PID_FILE") 2>/dev/null; fi
pkill -f "awp-watchdog.py" 2>/dev/null # Ensure it's killed
echo "Watchdog stopped (if running)."

# 2. Stop CSV Logger
echo "\n--- Stopping CSV Logger ---"
CSV_LOGGER_PID_FILE="$PIDS_DIR/csv_logger.pid"
if [ -f "$CSV_LOGGER_PID_FILE" ]; then kill $(cat "$CSV_LOGGER_PID_FILE") 2>/dev/null; fi
pkill -f "csv_logger.py" 2>/dev/null # Ensure it's killed
echo "CSV Logger stopped (if running)."

# 3. Stop All Agents (Predict and Mine)
echo "\n--- Stopping All AWP Agents ---"
ALL_AGENT_IDS=$(jq -r '.[] | .agent_id' "$AGENT_CONFIG_EXAMPLE")
for AGENT_ID in $ALL_AGENT_IDS; do
    echo "  Stopping $AGENT_ID..."
    "$HIVE_AGENT_MANAGER" stop "$AGENT_ID"
done

sleep 1
echo "\n=== All Agents Stopped ==="
rm -f "$PIDS_DIR"/*.pid # Ensure all PID files are removed
