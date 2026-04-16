import os
import subprocess
import time
import signal
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv # For loading agent-specific .env

# --- Configuration & Paths ---
CHECK_INTERVAL = 60  # seconds

# Define paths relative to the script's location (src/python/watchdog/)
PROJECT_ROOT = Path(__file__).resolve().parents[3] # awp-agents-project/

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
AGENTS_BASE_DIR = PROJECT_ROOT / "agents" # All agent folders (agent-01 to agent-06)
PIDS_DIR = PROJECT_ROOT / "data" / "pids"

# Path to other relevant components (these should be in PATH or managed by scripts)
# predict-agent binary is assumed to be in $HOME/.local/bin/ or PATH after setup.sh
PYTHON_VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python" # For running Python scripts
RUN_MINE_TOOL_SCRIPT = SCRIPTS_DIR / "run_mine_tool.py" # Centralized miner management script
HIVE_AGENT_MANAGER = SCRIPTS_DIR / "hive.sh" # Centralized agent manager

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.environ.get("WATCHDOG_LOG_FILE", "/tmp/awp-watchdog.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("watchdog")

# Ensure PID directory exists
PIDS_DIR.mkdir(parents=True, exist_ok=True)

def is_pid_running(name: str) -> bool:
    pid_file = PIDS_DIR / f"{name}.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0) # Signal 0 doesn't kill but checks if process exists
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        # PID is not running or file is corrupted
        return False

def save_pid(name: str, pid: int):
    (PID_DIR / f"{name}.pid").write_text(str(pid))

def restart_hive_agent(agent_id: str):
    log.info(f"Attempting to restart agent: {agent_id}")
    try:
        # hive.sh start handles sourcing agent's .env and setting up env vars
        # We don't specify interval here; it will default to 120s or use value from .env/agents.json if applicable
        cmd = [str(HIVE_AGENT_MANAGER), "start", agent_id]
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # Log the output from hive.sh for debugging
        log.info(f"hive.sh start output for {agent_id}: {result.stdout.decode().strip()}")
        log.info(f"Successfully started {agent_id}")
    except Exception as e:
        log.error(f"Failed to start Hive agent {agent_id}: {e}")

def run_check():
    log.info("Running health check...")
    
    # Check all agents (agent-01 to agent-06)
    for i in range(1, 7):
        agent_id = f"agent-0{i}"
        agent_env_file = AGENTS_BASE_DIR / agent_id / ".env"
        
        if not agent_env_file.exists():
            log.warning(f"Agent {agent_id} .env file not found: {agent_env_file}. Skipping health check for this agent.")
            continue

        # Load agent's .env to check ENABLE_MINER
        agent_config = {}
        with open(agent_env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    agent_config[key] = value.strip('\"\'')

        enable_miner = agent_config.get("ENABLE_MINER", "false").lower() == "true"

        # Check Predict loop
        if not is_pid_running(f"{agent_id}-predict"):
            log.warning(f"Agent {agent_id} predictor is missing! Attempting restart.")
            restart_hive_agent(agent_id) # hive.sh start handles both predict and mine

        # Check Mine loop (if enabled for this agent)
        if enable_miner:
            if not is_pid_running(f"{agent_id}-mine"):
                log.warning(f"Agent {agent_id} miner is missing (and enabled)! Attempting restart.")
                restart_hive_agent(agent_id) # hive.sh start handles both predict and mine
        elif is_pid_running(f"{agent_id}-mine"): # Miner is running but should be disabled
            log.warning(f"Agent {agent_id} miner is running but ENABLE_MINER=false. Stopping miner.")
            # To stop specific miner without affecting predict, use hive.sh stop then hive.sh start predict-only
            subprocess.run([str(HIVE_AGENT_MANAGER), "stop", agent_id], cwd=PROJECT_ROOT, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            subprocess.run([str(HIVE_AGENT_MANAGER), "start", agent_id], cwd=PROJECT_ROOT, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            log.info(f"Agent {agent_id} miner has been stopped.")

    log.info("Health check complete.")



def main():
    # Set WATCHDOG_LOG_FILE environment variable for logging.basicConfig
    os.environ["WATCHDOG_LOG_FILE"] = str(PROJECT_ROOT / "data" / "awp-watchdog.log")
    log.info("--- AWP Watchdog Started (PID Tracking Mode) ---")
    try:
        while True:
            run_check()
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        log.info("Watchdog stopping...")
    except Exception as e:
        log.critical(f"Watchdog crashed: {e}")

if __name__ == "__main__":
    # This part should be safe after refactoring paths
    # No need for the original _ensure_local_venv_python() as this is not a worker script.
    main()
