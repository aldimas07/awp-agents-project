import os
import subprocess
import time
import signal
import sys
import logging
from pathlib import Path

# --- Configuration & Paths ---
CHECK_INTERVAL = 60  # seconds

# Define paths relative to the script's location (src/python/watchdog/)
PROJECT_ROOT = Path(__file__).resolve().parents[3] 

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
AGENTS_BASE_DIR = PROJECT_ROOT / "agents" 
PIDS_DIR = PROJECT_ROOT / "data" / "pids"

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.environ.get("WATCHDOG_LOG_FILE", str(PROJECT_ROOT / "data" / "awp-watchdog.log"))),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("watchdog")

# Ensure PID directory exists
PIDS_DIR.mkdir(parents=True, exist_ok=True)

HIVE_AGENT_MANAGER = SCRIPTS_DIR / "hive.sh"

def is_process_running(name: str) -> bool:
    """Check if a process with a specific tag is running using pgrep."""
    try:
        cmd = ["pgrep", "-f", name]
        result = subprocess.run(cmd, capture_output=True)
        return result.returncode == 0
    except Exception:
        return False

def restart_hive_agent(agent_id: str):
    log.info(f"Attempting to restart agent: {agent_id}")
    try:
        cmd = [str(HIVE_AGENT_MANAGER), "start", agent_id]
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log.info(f"hive.sh start output for {agent_id}: {result.stdout.decode().strip()}")
        log.info(f"Successfully started {agent_id}")
    except Exception as e:
        log.error(f"Failed to start Hive agent {agent_id}: {e}")

def run_check():
    log.info("Running health check...")
    
    # Check all agents dynamically
    if not AGENTS_BASE_DIR.exists():
        log.error(f"Agents directory not found: {AGENTS_BASE_DIR}")
        return

    agent_dirs = sorted([d for d in AGENTS_BASE_DIR.iterdir() if d.is_dir() and d.name.startswith("agent-")])
    
    for agent_dir in agent_dirs:
        agent_id = agent_dir.name
        agent_env_file = agent_dir / ".env"
        
        if not agent_env_file.exists():
            continue

        # Load agent's .env
        agent_config = {}
        try:
            with open(agent_env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            agent_config[key] = value.strip('\"\'')
        except Exception as e:
            log.error(f"Failed to read .env for {agent_id}: {e}")
            continue

        # Skip monitoring if MONITOR_AGENT is false
        if agent_config.get("MONITOR_AGENT", "true").lower() == "false":
            continue

        enable_miner = agent_config.get("ENABLE_MINER", "false").lower() == "true"

        # Check Predict loop (using pgrep -f for stability)
        if not is_process_running(f"agent_wrapper.sh {agent_id}"):
            log.warning(f"Agent {agent_id} predictor is missing! Attempting restart.")
            restart_hive_agent(agent_id)

        # Check Mine loop (if enabled for this agent)
        if enable_miner:
            # Check for either run-worker or run_mine_tool.py
            if not is_process_running(f"run-worker .* --name {agent_id}") and not is_process_running(f"run_mine_tool.py .* --name {agent_config.get('MINER_ID', agent_id)}"):
                log.warning(f"Agent {agent_id} miner is missing (and enabled)! Attempting restart.")
                restart_hive_agent(agent_id)

    log.info("Health check complete.")

def main():
    log.info("--- AWP Watchdog Started (Dynamic Mode) ---")
    try:
        while True:
            run_check()
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        log.info("Watchdog stopping...")
    except Exception as e:
        log.critical(f"Watchdog crashed: {e}")

if __name__ == "__main__":
    main()
