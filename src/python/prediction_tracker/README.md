# Prediction Tracker System

This system is designed to track prediction results for all AWP agents, generate strategy hints, and integrate these hints into the agent's decision-making process.

## Components:

1.  **`csv_logger.py`**: Monitors agent prediction logs and records detailed results into a CSV file.
2.  **`hint_generator.py`**: Reads the CSV data, summarizes the last 5 prediction results for each agent, and creates a `strategy_hint.md` file in each agent's home directory.
3.  **`agent_wrapper.sh`**: A wrapper script that first runs `hint_generator.py` to ensure hints are up-to-date, and then executes the `predict-agent` command.

## Setup and Usage:

### 1. Start the CSV Logger

Run `csv_logger.py` in the background. It will continuously monitor agent logs and update `predictions.csv`.

```bash
nohup python3 /home/losbanditos/_code/prediction-tracker/csv_logger.py > /home/losbanditos/_code/prediction-tracker/csv_logger.log 2>&1 &
```

### 2. Restart Agents with Hint Integration

The `hive.sh` script and the standalone agent's startup now use `agent_wrapper.sh`. This means `hint_generator.py` will run *before* any agent starts, ensuring they have the latest hints.

To apply this to all running agents, use the provided restart script:

```bash
/home/losbanditos/_code/restart_agents_random.sh
```

This script will stop all current agents, generate fresh hints, and then restart them with randomized intervals, each agent loading its `strategy_hint.md`.

### 3. Accessing Strategy Hints

Each agent will have a `strategy_hint.md` file in its home directory:

*   **Hive Agents (agent-01 to agent-05)**: `/home/losbanditos/_code/awp-hive/agents/<agent_id>/home/strategy_hint.md`
*   **Standalone Agent (standalone-06)**: `/home/losbanditos/_code/mine-skill/output/agent-runs/strategy_hint.md`

Agents are expected to read and incorporate the advice from `strategy_hint.md` into their LLM prompts for future predictions.

### 4. Verify Operation

*   **Check CSV logs**: `tail -f /home/losbanditos/_code/prediction-tracker/predictions.csv`
*   **Check hint files**: `cat /home/losbanditos/_code/awp-hive/agents/agent-01/home/strategy_hint.md`
*   **Check agent logs**: Look for evidence in `predict.log` files that agents are considering the hints (this depends on the agent's internal prompt structure).

## Manual Hint Generation

If you need to manually refresh all hints without restarting agents (e.g., after editing `predictions.csv`):

```bash
python3 /home/losbanditos/_code/prediction-tracker/hint_generator.py
```
