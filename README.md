# AWP Agent Project

This repository contains the code and scripts for running a multi-agent AWP prediction and mining system.
It is designed to be easy to set up and run on various environments, including Windows.

## Project Structure

```
awp-agents-project/
├── .gitignore                      # Git ignore file for runtime and sensitive data
├── README.md                       # This file: main documentation
│
├── config/                         # Configuration templates and global settings
│   ├── .env.example                # Example environment variables (copy to .env and fill)
│   └── agents.json.example         # Example for agent-specific configurations
│
├── scripts/                        # All portable helper scripts
│   ├── setup.sh                    # Initial setup (build, venv, install deps)
│   ├── init_agents.sh              # Creates agent directories and .env files
│   ├── start_all_agents.sh         # Starts all agents (predict & watchdog)
│   ├── stop_all_agents.sh          # Stops all agents & watchdog
│   ├── restart_all_agents.sh       # Restarts all agents with randomized intervals
│   ├── agent_wrapper.sh            # Wrapper for predict-agent (integrates hint generator)
│   └── run_mine_tool.py            # Script for standalone miner operations
│
├── src/                            # Source code for Python and Rust components
│   ├── python/                     
│   │   ├── watchdog/               # Python watchdog script
│   │   │   ├── awp-watchdog.py
│   │   │   └── requirements.txt    # Python dependencies for watchdog
│   │   ├── prediction_tracker/     # Prediction tracking system
│   │   │   ├── csv_logger.py
│   │   │   ├── hint_generator.py
│   │   │   └── README.md
│   │   │   └── requirements.txt    # Python dependencies for tracker
│   │   └── requirements.txt        # Combined Python dependencies
│   ├── rust/                       
│   │   └── prediction-skill/       # Source code for `predict-agent` (Rust)
│   │       ├── src/
│   │       └── Cargo.toml
│
├── data/                           # Runtime data (excluded from Git)
│   ├── predictions.csv             # Prediction results log
│   └── pids/                       # PID files for running processes
│
└── agents/                         # Agent-specific runtime directories (excluded from Git)
    ├── agent-01/                   # Created by `init_agents.sh`
    │   ├── .env                    # Agent-specific environment variables (e.g., private key)
    │   ├── home/                   # Wallet files, strategy_hint.md
    │   ├── state/                  # Agent's internal state
    │   └── logs/                   # Agent-specific log files
    ├── agent-0X/                   # (for other Hive agents)
    └── standalone-06/              # Standalone agent's data
        ├── .env
        ├── output/agent-runs/      # Logs, strategy_hint.md
        └── home/                   # Wallet files
```

## Getting Started (Native Setup)

### Prerequisites

Before you begin, ensure you have the following installed on your system:

*   **Git**: For cloning the repository.
*   **Python 3.x**: Including `venv` module.
*   **Rust Toolchain**: `rustup` recommended for easy installation.
*   **`jq`**: Command-line JSON processor (for `hive.sh`).
*   **Platform-specific tools**:
    *   **Linux/macOS**: `nohup`, `pkill` (usually pre-installed).
    *   **Windows**: Consider alternatives for `nohup` (`Start-Process`), `pkill` (`taskkill`), and `source` (`& .venv\Scripts\activate`).

### Installation Steps

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/awp-agents-project.git
    cd awp-agents-project
    ```

2.  **Initial Setup Script (Linux/macOS)**:
    Run the setup script to build Rust binaries, create Python virtual environments, and install dependencies.
    ```bash
    ./scripts/setup.sh
    ```
    *For Windows, you will need to manually execute the steps in `setup.sh` using PowerShell/CMD equivalents, or refer to detailed instructions in a `SETUP-WINDOWS.md` (to be created).* 

3.  **Configure Environment Variables**:
    Copy the example environment file and fill in your API keys.
    **CRITICAL**: You must set `OPENAI_API_KEY` and `OPENAI_BASE_URL` in `config/.env` to allow the prediction loop to directly interface with the LLM API without relying on external CLIs.
    ```bash
    cp config/.env.example config/.env
    # Edit config/.env with your actual values (e.g. LLM Keys)
    ```

4.  **Initialize Agents**: 
    This script will create the `agents/` directories and their respective `.env` files. You will be prompted to enter private keys for each agent, or they will be generated.
    ```bash
    ./scripts/init_agents.sh
    ```

## Running the Agents

*   **Start All Agents (Predict loops & Watchdog)**:
    ```bash
    ./scripts/start_all_agents.sh
    ```
*   **Stop All Agents**:
    ```bash
    ./scripts/stop_all_agents.sh
    ```
*   **Restart All Agents (with randomized intervals)**:
    ```bash
    ./scripts/restart_all_agents.sh
    ```

### Direct LLM Mode
By default, the prediction agent uses internal direct LLM mode. Using the OpenClaw CLI is no longer required as long as `OPENAI_API_KEY` and `OPENAI_BASE_URL` are defined in the configuration.

## Prediction Tracker

Detailed usage for the prediction tracker system can be found in `src/python/prediction_tracker/README.md`.

## Development

Refer to individual `src/python/.../README.md` and `src/rust/.../README.md` files for component-specific development guidelines.

## Contributing

See `CONTRIBUTING.md` (to be created) for guidelines on how to contribute to this project.

## License

This project is licensed under the MIT License.

(End of README.md)