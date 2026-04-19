import os
import subprocess
import sys

def run_doctor(agent_id):
    env_file = f"agents/{agent_id}/.env"
    env = os.environ.copy()
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env[key.strip()] = val.strip().strip('"').strip("'")
    
    # Force HOME
    env["HOME"] = os.path.abspath(f"agents/{agent_id}/home")
    # Force PATH
    env["PATH"] = f"/home/losbanditos/.local/bin:{env.get('PATH', '')}"

    cmd = ["/home/losbanditos/_code/awp-agents-project/.venv/bin/python", "scripts/run_mine_tool.py", "doctor"]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    print(f"--- Agent {agent_id} ---")
    print(result.stdout)
    print(result.stderr)

for i in ["01", "02", "06"]:
    run_doctor(f"agent-{i}")
