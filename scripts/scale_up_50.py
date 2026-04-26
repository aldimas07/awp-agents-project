import os
import json
import subprocess
import time
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"
HIVE_SCRIPT = PROJECT_ROOT / "scripts" / "hive.sh"
EXPORT_FILE = PROJECT_ROOT / "agents_21_50_keys.txt"

NEW_PERSONAS = {
    21: "arb_hunter",
    22: "delta_neutral",
    23: "gamma_scalper",
    24: "liquidity_provider",
    25: "order_flow_analyst",
    26: "hft_strategy",
    27: "macro_economist",
    28: "sentiment_bot",
    29: "news_trader",
    30: "correlation_expert",
    31: "basis_trader",
    32: "funding_farmer",
    33: "vix_watcher",
    34: "options_theta",
    35: "dark_pool_tracker",
    36: "flash_boy",
    37: "statistical_arb",
    38: "mean_reversionist",
    39: "fibonacci_pro",
    40: "ichimoku_master",
    41: "rsi_divergent",
    42: "volume_profile_pro",
    43: "elliott_waver",
    44: "breakout_trader",
    45: "trap_detective",
    46: "liquidation_sniper",
    47: "defi_degen",
    48: "l2_specialist",
    49: "cross_chain_arb",
    50: "alpha_generator"
}

OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_API_KEY = "REDACTED"
PREDICT_MODEL = "nousresearch/hermes-4-70b"

# Ensure PATH includes cargo/local bins
BIN_PATH = f"{os.environ.get('HOME')}/.cargo/bin:{os.environ.get('HOME')}/.local/bin"
os.environ["PATH"] = f"{BIN_PATH}:{os.environ.get('PATH', '')}"

def run_cmd(cmd, env=None):
    if env is None:
        env = os.environ.copy()
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)

def main():
    if EXPORT_FILE.exists():
        EXPORT_FILE.unlink()

    print(f"🚀 Scaling up AWP Fleet to 50 Agents (Adding 21-50)...")
    
    # Header for export file
    with open(EXPORT_FILE, "a") as f:
        f.write("AGENT ID | ADDRESS | PRIVATE KEY | PERSONA\n")
        f.write("-" * 80 + "\n")

    for i in range(21, 51):
        agent_id = f"agent-{i:02d}"
        persona = NEW_PERSONAS[i]
        agent_path = AGENTS_DIR / agent_id
        home_dir = agent_path / "home"
        state_dir = agent_path / "state"
        logs_dir = agent_path / "logs"
        env_file = agent_path / ".env"

        print(f"\n📦 Setting up {agent_id} ({persona})...")

        # Create directories
        for d in [home_dir, state_dir, logs_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Generate Wallet
        env = os.environ.copy()
        env["HOME"] = str(home_dir)
        
        print(f"  🔑 Initializing wallet...")
        run_cmd("awp-wallet init", env=env)
        
        export_res = run_cmd("awp-wallet export-private-key", env=env)
        if export_res.returncode != 0:
            print(f"  ❌ Error exporting key: {export_res.stderr}")
            continue
            
        try:
            creds = json.loads(export_res.stdout)
            priv_key = creds["privateKey"]
            address = creds["address"]
            print(f"  ✅ Wallet: {address}")
        except Exception as e:
            print(f"  ❌ Parse error: {e}")
            continue

        # Create .env
        env_content = f"""AWP_PRIVATE_KEY="{priv_key}"
AWP_ADDRESS="{address}"
WORKER_STATE_ROOT="{state_dir}"
PLATFORM_BASE_URL="https://api.minework.net"
MINER_ID="{agent_id}"
WORKER_MAX_PARALLEL="3"
DATASET_REFRESH_SECONDS="15"
OPENAI_BASE_URL="{OPENAI_BASE_URL}"
OPENAI_API_KEY="{OPENAI_API_KEY}"
PREDICT_MODEL="{PREDICT_MODEL}"
OPENAI_MODEL="{PREDICT_MODEL}"
ENABLE_MINER="false"
persona="{persona}"
"""
        env_file.write_text(env_content)

        # Registration (Preflight)
        print(f"  📝 Registering agent on AWP network...")
        env["AWP_PRIVATE_KEY"] = priv_key
        env["AWP_ADDRESS"] = address
        # Ensure we use the right server
        env["PREDICT_SERVER_URL"] = "https://api.agentpredict.work"
        
        pre_res = run_cmd("predict-agent preflight", env=env)
        if pre_res.returncode != 0:
            print(f"  ⚠️ Preflight warning: {pre_res.stderr.strip() or pre_res.stdout.strip()}")
        else:
            print(f"  ✅ Preflight/Registration success.")

        # Set Persona
        print(f"  👤 Setting persona to {persona}...")
        set_res = run_cmd(f"predict-agent set-persona {persona}", env=env)
        if set_res.returncode != 0:
             print(f"  ⚠️ Set-persona warning: {set_res.stderr.strip() or set_res.stdout.strip()}")

        # Export to file
        with open(EXPORT_FILE, "a") as f:
            f.write(f"{agent_id} | {address} | {priv_key} | {persona}\n")

        # Start Agent
        print(f"  🐝 Starting agent via hive...")
        start_res = run_cmd(f"bash {HIVE_SCRIPT} start {agent_id}")
        if start_res.returncode == 0:
            print(f"  🟢 {agent_id} is RUNNING.")
        else:
            print(f"  🔴 Failed to start {agent_id}: {start_res.stderr}")
        
        # Small sleep to be nice to the API
        time.sleep(1)

    print(f"\n✨ Scale-up complete! Details saved to {EXPORT_FILE}")

if __name__ == "__main__":
    main()
