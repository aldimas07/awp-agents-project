import os
import shutil
import subprocess
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"
GLOBAL_ENV = PROJECT_ROOT / "config" / ".env"

PERSONAS = {
    "agent-07": "quant",
    "agent-08": "institutional",
    "agent-09": "scalper",
    "agent-10": "swing_trader",
    "agent-11": "momentum_junkie",
    "agent-12": "contrarian",
    "agent-13": "whale_watcher",
    "agent-14": "risk_manager",
    "agent-15": "chartist",
    "agent-16": "volatility_seeker",
    "agent-17": "fud_slayer",
    "agent-18": "moon_boy",
    "agent-19": "diamond_hands",
    "agent-20": "bot_expert"
}

OPENAPI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
OPENAPI_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("PREDICT_MODEL", "nousresearch/hermes-4-70b")

def run_cmd(cmd, cwd=None, env=None):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, env=env)

def main():
    print("🚀 Starting Batch Agent Creation (agent-07 to agent-20)...")
    
    for agent_id, persona in PERSONAS.items():
        agent_path = AGENTS_DIR / agent_id
        home_dir = agent_path / "home"
        state_dir = agent_path / "state"
        logs_dir = agent_path / "logs"
        env_file = agent_path / ".env"

        print(f"\n📦 Setting up {agent_id} (Persona: {persona})...")
        
        # Create directories
        for d in [home_dir, state_dir, logs_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Generate Wallet
        print(f"  🔑 Generating wallet via awp-wallet...")
        env = os.environ.copy()
        env["HOME"] = str(home_dir)
        
        # We assume awp-wallet is in PATH
        init_res = run_cmd("awp-wallet init", env=env)
        if init_res.returncode != 0:
            print(f"  ❌ Error initializing wallet for {agent_id}: {init_res.stderr}")
            continue
            
        export_res = run_cmd("awp-wallet export-private-key", env=env)
        if export_res.returncode != 0:
            print(f"  ❌ Error exporting key for {agent_id}: {export_res.stderr}")
            continue
            
        try:
            creds = json.loads(export_res.stdout)
            priv_key = creds["privateKey"]
            address = creds["address"]
            print(f"  ✅ Wallet created: {address}")
        except Exception as e:
            print(f"  ❌ Failed to parse wallet output: {e}")
            continue

        # Create .env
        env_content = f"""AWP_PRIVATE_KEY="{priv_key}"
AWP_ADDRESS="{address}"
WORKER_STATE_ROOT="{state_dir}"
PLATFORM_BASE_URL="https://api.minework.net"
MINER_ID="{agent_id}"
WORKER_MAX_PARALLEL="10"
DATASET_REFRESH_SECONDS="15"
OPENAI_BASE_URL="{OPENAPI_BASE_URL}"
OPENAI_API_KEY="{OPENAPI_KEY}"
PREDICT_MODEL="{MODEL}"
OPENAI_MODEL="{MODEL}"
ENABLE_MINER="true"
persona="{persona}"
"""
        env_file.write_text(env_content)
        print(f"  📝 .env created at {env_file}")

    print("\n✨ Batch creation complete! All 14 agents configured.")
    print("👉 Use 'scripts/hive.sh status' to check.")

if __name__ == "__main__":
    main()
