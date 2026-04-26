#!/bin/bash

# stop_all_agents.sh - Stops all running AWP agents and background processes.

# Define paths relative to this script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PIDS_DIR="$PROJECT_ROOT/data/pids"
SCRIPTS_DIR="$PROJECT_ROOT/scripts"
HIVE_AGENT_MANAGER="$SCRIPTS_DIR/hive.sh"

echo "=== Stopping All AWP Agents (awp-agents-project) ==="

# 1. Stop Watchdog
echo -e "\n--- Stopping Watchdog ---"
pkill -f "awp-watchdog.py" 2>/dev/null
echo "Watchdog stopped."

# 2. Stop CSV Logger
echo -e "\n--- Stopping CSV Logger ---"
pkill -f "csv_logger.py" 2>/dev/null
echo "CSV Logger stopped."

# 3. Stop All Agents
echo -e "\n--- Stopping All AWP Agents ---"

for i in $(seq -w 1 50); do
    AGENT_ID="agent-$i"
    if [ -d "$PROJECT_ROOT/agents/$AGENT_ID" ]; then
        echo "  Stopping $AGENT_ID..."
        "$HIVE_AGENT_MANAGER" stop "$AGENT_ID" 2>/dev/null
    fi
done

sleep 1
echo -e "\n=== All Agents Stopped ==="
rm -f "$PIDS_DIR"/*.pid 2>/dev/null
