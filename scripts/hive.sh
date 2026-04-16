#!/bin/bash

# AWP Multi-Agent Hive Management Script
# Optimized for high-throughput isolation

# Define project roots relatively to this script
# This script assumes it's located in $PROJECT_ROOT/scripts/
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
AGENTS_BASE_DIR="$PROJECT_ROOT/agents"
PIDS_DIR="$PROJECT_ROOT/data/pids"
PYTHON_VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
RUN_MINE_TOOL_SCRIPT="$PROJECT_ROOT/scripts/run_mine_tool.py"
PREDICTION_TRACKER_WRAPPER="$PROJECT_ROOT/src/python/prediction_tracker/agent_wrapper.sh"

# Ensure predict-agent binary is in PATH or accessible.
# It should be installed to ~/.local/bin/predict-agent by setup.sh.
if ! command -v predict-agent &> /dev/null
then
    echo "Error: 'predict-agent' binary not found in PATH. Please run ./scripts/setup.sh."
    exit 1
fi 

function create_agent() {
    local name=$1 # e.g., agent-01, agent-06
    if [ -z "$name" ]; then echo "Usage: hive create <name>"; return 1; fi

    local agent_dir="$AGENTS_BASE_DIR/$name"
    mkdir -p "$agent_dir/home"
    mkdir -p "$agent_dir/state"
    mkdir -p "$agent_dir/logs"

    echo "[Hive] Agent directories created for $name."
    echo "[Hive] Wallet initialization and registration should be handled by 'init_agents.sh' or manually."
    echo "[Hive] Remember to create $agent_dir/.env with AWP_PRIVATE_KEY and AWP_ADDRESS."
    
    # Create initial .env with miner disabled by default
    cat <<EOF > "$agent_dir/.env"
AWP_PRIVATE_KEY="" # To be filled by init_agents.sh or manually
AWP_ADDRESS="" # To be filled by init_agents.sh or manually
WORKER_STATE_ROOT="$agent_dir/state"
MINER_ID="$name"
ENABLE_MINER="false" # Default: Miner is OFF
EOF
    echo "Initial .env created at $agent_dir/.env. Please configure it."
}

function start_agent() {
    local name=$1 # e.g., agent-01, agent-06
    local interval=${2:-120} # Predict loop interval
    if [ -z "$name" ]; then echo "Usage: hive start <name> [interval]"; return 1; fi

    local agent_dir="$AGENTS_BASE_DIR/$name"

    # Load agent's .env if it exists
    if [ -f "$agent_dir/.env" ]; then
        echo "[Hive] Loading configuration from $agent_dir/.env"
        # Export all variables from .env
        set -a
        source "$agent_dir/.env"
        set +a
    fi
    if [ ! -d "$agent_dir" ]; then echo "Agent $name not found in $AGENTS_BASE_DIR/"; return 1; fi

    # Source agent's specific .env file
    if [ -f "$agent_dir/.env" ]; then
        source "$agent_dir/.env"
    else
        echo "Error: .env file not found for $name at $agent_dir/.env. Cannot start agent."
        return 1
    fi

    # Export required environment variables for both predict-agent and run_mine_tool.py
    export HOME="$agent_dir/home" # Essential for wallet operations
    export AWP_PRIVATE_KEY
    export AWP_ADDRESS
    export WORKER_STATE_ROOT="$agent_dir/state" # Miner state root
    export MINER_ID="$name" # Miner ID is agent's name
    
    # Ensure global config vars are exported (these usually come from config/.env)
    export PLATFORM_BASE_URL
    export OPENAI_BASE_URL
    export OPENAI_API_KEY
    export PREDICT_MODEL
    export AWP_WALLET_BIN
    export OPENAI_MODEL # Fallback LLM if PREDICT_MODEL fails

    # Check ENABLE_MINER flag from agent's .env
    local enable_miner=${ENABLE_MINER:-"false"} # Default to false if not set

    # --- Start Mine WorkNet (if enabled) ---
    if [ "$enable_miner" = "true" ]; then
        echo "[Hive] Starting Mine WorkNet for $name..."
        # run_mine_tool.py expects PROJECT_ROOT as cwd
        nohup "$PYTHON_VENV_PYTHON" "$RUN_MINE_TOOL_SCRIPT" agent-start > "$agent_dir/logs/mine.log" 2>&1 &
        echo $! > "$PIDS_DIR/$name-mine.pid"
        echo "[Hive] Miner for $name started with PID $(cat "$PIDS_DIR/$name-mine.pid")."
    else
        echo "[Hive] Mine WorkNet for $name is DISABLED (ENABLE_MINER=false in .env)."
        # Ensure old PID file is removed if it exists
        rm -f "$PIDS_DIR/$name-mine.pid"
    fi

    # --- Start Predict WorkNet ---
    echo "[Hive] Starting Predict WorkNet loop for $name (interval=${interval}s)..."
    # Use agent_wrapper.sh to run hint_generator and then predict-agent
    # PATH is updated by global setup.sh to include $PROJECT_ROOT/src/rust/prediction-skill/target/release
    nohup "$PREDICTION_TRACKER_WRAPPER" "$name" "$interval" > "$agent_dir/logs/predict.log" 2>&1 &
    echo $! > "$PIDS_DIR/$name-predict.pid"
    echo "[Hive] Predictor for $name started with PID $(cat "$PIDS_DIR/$name-predict.pid")."
    
    echo "[Hive] $name is now active."
}

function stop_agent() {
    local name=$1 # e.g., agent-01, agent-06
    if [ -z "$name" ]; then echo "Usage: hive stop <name>"; return 1; fi

    local agent_dir="$AGENTS_BASE_DIR/$name"
    
    echo "[Hive] Stopping $name..."

    # Load agent's .env for miner control (e.g., to set HOME for run_mine_tool.py)
    if [ -f "$agent_dir/.env" ]; then
        source "$agent_dir/.env"
        export HOME="$agent_dir/home"
        export MINER_ID="$name" # Ensure MINER_ID is set for agent-control stop
    fi

    # --- Stop Mine WorkNet (if running) ---
    if [ -f "$PIDS_DIR/$name-mine.pid" ]; then
        echo "  Stopping miner for $name..."
        # Use run_mine_tool.py agent-control stop (expects PROJECT_ROOT as cwd)
        # Ensure python venv is active for this command
        if "$PYTHON_VENV_PYTHON" "$RUN_MINE_TOOL_SCRIPT" agent-control stop > /dev/null 2>&1; then
            echo "    Miner for $name stopped gracefully."
        else
            echo "    Failed to stop miner for $name gracefully. Attempting to kill PID..."
            kill $(cat "$PIDS_DIR/$name-mine.pid") 2>/dev/null && echo "    Miner PID killed." || echo "    Miner PID not found/killed."
        fi
        rm -f "$PIDS_DIR/$name-mine.pid"
    else
        echo "  No active miner PID found for $name."
    fi

    # --- Stop Predict WorkNet ---
    echo "  Stopping predictor for $name..."
    pkill -9 -f "agent_wrapper.sh $name" 2>/dev/null && echo "    Wrapper for $name killed."
    pkill -9 -f "predict-agent .* --agent-id $name" 2>/dev/null && echo "    Predictor for $name killed."
    if [ -f "$PIDS_DIR/$name-predict.pid" ]; then
        kill $(cat "$PIDS_DIR/$name-predict.pid") 2>/dev/null
        rm -f "$PIDS_DIR/$name-predict.pid"
    fi
    rm -f "$PIDS_DIR/$name-mine.pid" "$PIDS_DIR/$name-predict.pid" # Ensure both PID files are removed
    
    echo "[Hive] $name stopped."
}

function status_all() {
    echo "----------------------------------------------------------------------"
    printf "%-12s | %-42s | %-10s | %-10s\n" "AGENT" "WALLET ADDRESS" "PREDICT" "MINE"
    echo "----------------------------------------------------------------------"
    for dir in "$AGENTS_BASE_DIR"/*; do
        local agent_name=$(basename "$dir")
        if [ -d "$dir" ] && [ -f "$dir/.env" ]; then
            source "$dir/.env" # Load agent's .env for AWP_ADDRESS, etc.
            export HOME="$dir/home" # Set HOME for awp-wallet

            local awp_address=${AWP_ADDRESS:-"N/A"}
            if [ -z "$awp_address" ] || [ "$awp_address" = "\"\"" ]; then awp_address="N/A"; fi

            # Check predict process status
            local predict_pid_file="$PIDS_DIR/$agent_name-predict.pid"
            local predict_status="OFF"
            if [ -f "$predict_pid_file" ] && ps -p $(cat "$predict_pid_file") > /dev/null 2>&1; then
                predict_status="ON"
            fi

            # Check mine process status (and if enabled in .env)
            local enable_miner=${ENABLE_MINER:-"false"}
            local mine_pid_file="$PIDS_DIR/$agent_name-mine.pid"
            local mine_status="DISABLED" # Default if not enabled

            if [ "$enable_miner" = "true" ]; then
                if [ -f "$mine_pid_file" ] && ps -p $(cat "$mine_pid_file") > /dev/null 2>&1; then
                    mine_status="ON"
                else
                    mine_status="OFF"
                fi
            fi

            printf "%-12s | %-42s | %-10s | %-10s\n" "$agent_name" "$awp_address" "$predict_status" "$mine_status"
        fi
    done
    echo "----------------------------------------------------------------------"
}

case "$1" in
    create) create_agent "$2" ;;
    start)  start_agent "$2" "$3" ;;
    stop)   stop_agent "$2" ;;
    restart) stop_agent "$2" && start_agent "$2" "${3:-120}" ;;
    status) status_all ;;
    miner-on)
        AGENT_ID="$2"
        AGENT_ENV_FILE="$AGENTS_BASE_DIR/$AGENT_ID/.env"
        if [ -f "$AGENT_ENV_FILE" ]; then
            sed -i 's/^ENABLE_MINER="false"/ENABLE_MINER="true"/' "$AGENT_ENV_FILE"
            echo "[Hive] Miner enabled for $AGENT_ID. Restarting agent..."
            stop_agent "$AGENT_ID" && start_agent "$AGENT_ID" # Restart to apply change
        else
            echo "Error: Agent $AGENT_ID not found or .env file missing."
        fi
        ;;
    miner-off)
        AGENT_ID="$2"
        AGENT_ENV_FILE="$AGENTS_BASE_DIR/$AGENT_ID/.env"
        if [ -f "$AGENT_ENV_FILE" ]; then
            sed -i 's/^ENABLE_MINER="true"/ENABLE_MINER="false"/' "$AGENT_ENV_FILE"
            echo "[Hive] Miner disabled for $AGENT_ID. Restarting agent..."
            stop_agent "$AGENT_ID" && start_agent "$AGENT_ID" # Restart to apply change
        else
            echo "Error: Agent $AGENT_ID not found or .env file missing."
        fi
        ;;
    *) echo "Usage: hive {create|start|stop|restart|status|miner-on|miner-off} [name] [interval]" ;;
esac
