#!/bin/bash

# Wrapper for direct prediction loop that injects hint generator
# Usage: ./agent_wrapper.sh <agent_id> <interval>

AGENT_ID=$1
INTERVAL=$2

# Load local .env if exists
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Activate virtual environment
if [ -f "/home/losbanditos/_code/awp-agents-project/.venv/bin/activate" ]; then
  source "/home/losbanditos/_code/awp-agents-project/.venv/bin/activate"
fi

# Loop forever
while true; do
  echo "[Wrapper] Starting iteration for $AGENT_ID at $(date)"
  
  # 1. Run hint generator (Python)
  python3 /home/losbanditos/_code/awp-agents-project/src/python/prediction_tracker/hint_generator.py --agent "$AGENT_ID"
  
  # 2. Run prediction (Rust) - single iteration
  predict-agent loop --agent-id "$AGENT_ID" --interval "$INTERVAL" --max-iterations 1
  
  echo "[Wrapper] Iteration complete, sleeping for ${INTERVAL}s..."
  sleep "$INTERVAL"
done
