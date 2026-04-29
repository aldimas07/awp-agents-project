#!/bin/bash

# Wrapper for direct prediction loop that injects hint generator
# Usage: ./agent_wrapper.sh <agent_id> <interval>

AGENT_ID=$1
INTERVAL=$2

# Derive project root dynamically using git for robustness
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && git rev-parse --show-toplevel)"

# 1. Load global config/.env (API keys, model, platform URL)
if [ -f "$PROJECT_ROOT/config/.env" ]; then
  set -a
  source "$PROJECT_ROOT/config/.env"
  set +a
fi

# 2. Load agent-specific .env (wallet keys, overrides)
AGENT_ENV="$PROJECT_ROOT/agents/$AGENT_ID/.env"
if [ -f "$AGENT_ENV" ]; then
  set -a
  source "$AGENT_ENV"
  set +a
fi

# 3. Export HOME for wallet operations
export HOME="$PROJECT_ROOT/agents/$AGENT_ID/home"

# Activate virtual environment
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
  source "$PROJECT_ROOT/.venv/bin/activate"
fi
printenv | grep OPENAI

# Loop forever
while true; do
  echo "[Wrapper] Starting iteration for $AGENT_ID at $(date)"
  
  # 1. Run hint generator (Python)
  python3 "$PROJECT_ROOT/src/python/prediction_tracker/hint_generator.py" --agent "$AGENT_ID"
  
  # 2. Run prediction (Rust) - single iteration
  "$PROJECT_ROOT"/predict-agent loop --agent-id "$AGENT_ID" --interval "$INTERVAL" --max-iterations 1
  
  echo "[Wrapper] Iteration complete, sleeping for ${INTERVAL}s..."
  sleep "$INTERVAL"
done
