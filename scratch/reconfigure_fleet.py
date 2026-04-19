import os
from pathlib import Path

PROJECT_ROOT = Path("/home/losbanditos/_code/awp-agents-project")
AGENTS_DIR = PROJECT_ROOT / "agents"

MODELS = [
    "qwen3-coder-480b-a35b-instruct",
    "qwen3.5-plus",
    "qwen3.5-plus-2026-02-15",
    "qwen3.6-35b-a3b",
    "qwen-plus-2025-07-14",
    "qwen3.6-plus-2026-04-02",
    "qwen3-next-80b-a3b-instruct",
    "qwen3-30b-a3b-thinking-2507",
    "qwen3-30b-a3b-instruct-2507",
    "qwen-plus-2025-04-28",
    "qwen3-30b-a3b",
    "qwen3.6-flash-2026-04-16",
    "qwen3-vl-235b-a22b-instruct",
    "qwen-plus-latest",
    "qwen3-vl-235b-a22b-thinking",
    "qwen2.5-vl-72b-instruct",
    "qwen3-vl-30b-a3b-thinking",
    "qwen2.5-32b-instruct",
    "qwen3.6-flash",
    "qwen3-vl-8b-thinking"
]

def reconfigure():
    agent_dirs = sorted([d for d in AGENTS_DIR.iterdir() if d.is_dir() and d.name.startswith("agent-")])
    
    for i, agent_dir in enumerate(agent_dirs):
        env_file = agent_dir / ".env"
        if not env_file.exists():
            continue
            
        with open(env_file, 'r') as f:
            lines = f.readlines()
            
        new_lines = []
        # Assign primary and fallback models in rotation
        primary_model = MODELS[i % len(MODELS)]
        fallback_model = MODELS[(i + 1) % len(MODELS)]
        
        updated_keys = {
            "PREDICT_MODEL": f'"{primary_model}"',
            "OPENAI_MODEL": f'"{fallback_model}"',
            "DATASET_REFRESH_SECONDS": "120",
            "ENABLE_MINER": "false", # Keep miner off as requested in previous sessions, but can be changed
        }
        
        seen_keys = set()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            
            if '=' in line:
                key = stripped.split('=', 1)[0]
                if key in updated_keys:
                    new_lines.append(f"{key}={updated_keys[key]}\n")
                    seen_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
                
        # Add missing keys
        for key, value in updated_keys.items():
            if key not in seen_keys:
                new_lines.append(f"{key}={value}\n")
                
        with open(env_file, 'w') as f:
            f.writelines(new_lines)
            
        print(f"Reconfigured {agent_dir.name} with {primary_model} (fallback: {fallback_model})")

if __name__ == "__main__":
    reconfigure()
