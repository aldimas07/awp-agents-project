#!/bin/bash

# Define paths relative to this script
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
PIDS_DIR="$PROJECT_ROOT/data/pids"
SCRIPTS_DIR="$PROJECT_ROOT/scripts"
HIVE_AGENT_MANAGER="$SCRIPTS_DIR/hive.sh"
AGENT_CONFIG_EXAMPLE="$PROJECT_ROOT/config/agents.json.example"

# Generate random interval between 110-125
random_interval() {
    echo $((RANDOM % 16 + 110))
}

echo "=== Restarting All AWP Agents (Predict & Mine) with Randomized Intervals ==="
echo ""

# Stop all current agents gracefully if possible
echo "Stopping all agents..."
"$SCRIPTS_DIR/stop_all_agents.sh"
sleep 2

echo "\n"

# Source global .env for base settings (like OPENAI_API_KEY, PLATFORM_BASE_URL, PREDICT_MODEL)
# This ensures all agents inherit the global configuration.
if [ -f "$PROJECT_ROOT/config/.env" ]; then
    source "$PROJECT_ROOT/config/.env"
    echo "Global configuration loaded from config/.env."
else
    echo "Error: config/.env not found. Please copy config/.env.example to config/.env and fill it. Cannot restart agents."
    exit 1
fi

# Start Watchdog and CSV Logger (they were stopped by stop_all_agents.sh)
"$SCRIPTS_DIR/start_all_agents.sh"

echo "\n=== All Agents Restarted with Randomized Intervals ===\n"