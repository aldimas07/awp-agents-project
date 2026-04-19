import os
import json
import re
from pathlib import Path

def remove_wikipedia_from_json(file_path):
    if not file_path.exists():
        return
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        changed = False
        
        # Handle maps (like dataset_cursors.json)
        if isinstance(data, dict):
            if "ds_wikipedia" in data:
                del data["ds_wikipedia"]
                changed = True
            
            # Handle session structure
            if "selected_dataset_ids" in data and isinstance(data["selected_dataset_ids"], list):
                if "ds_wikipedia" in data["selected_dataset_ids"]:
                    data["selected_dataset_ids"] = [ds for ds in data["selected_dataset_ids"] if ds != "ds_wikipedia"]
                    changed = True
            
            if "active_datasets" in data and isinstance(data["active_datasets"], list):
                new_active = []
                for ds in data["active_datasets"]:
                    if isinstance(ds, str):
                        if ds != "ds_wikipedia":
                            new_active.append(ds)
                        else:
                            changed = True
                    elif isinstance(ds, dict):
                        if ds.get("dataset_id") != "ds_wikipedia" and ds.get("id") != "ds_wikipedia":
                            new_active.append(ds)
                        else:
                            changed = True
                    else:
                        new_active.append(ds)
                data["active_datasets"] = new_active

            if "last_summary" in data and isinstance(data["last_summary"], dict):
                last_summary = data["last_summary"]
                if "current_batch" in last_summary and isinstance(last_summary["current_batch"], dict):
                    batch = last_summary["current_batch"]
                    if "dataset_ids" in batch and isinstance(batch["dataset_ids"], list):
                        if "ds_wikipedia" in batch["dataset_ids"]:
                            batch["dataset_ids"] = [ds for ds in batch["dataset_ids"] if ds != "ds_wikipedia"]
                            changed = True

        if changed:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"Updated {file_path}")
            
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def remove_wikipedia_from_env(file_path):
    if not file_path.exists():
        return
    
    try:
        content = file_path.read_text()
        if "ds_wikipedia" not in content:
            return

        # Replace ds_wikipedia in MINER_DATASETS
        # Handle cases: 
        # MINER_DATASETS="ds_wikipedia,ds_arxiv" -> MINER_DATASETS="ds_arxiv"
        # MINER_DATASETS="ds_arxiv,ds_wikipedia" -> MINER_DATASETS="ds_arxiv"
        # MINER_DATASETS="ds_wikipedia" -> MINER_DATASETS=""
        
        lines = content.splitlines()
        new_lines = []
        changed = False
        
        for line in lines:
            if line.startswith("MINER_DATASETS="):
                match = re.match(r'MINER_DATASETS="([^"]*)"', line)
                if match:
                    datasets = match.group(1).split(",")
                    new_datasets = [d for d in datasets if d.strip() != "ds_wikipedia"]
                    if len(new_datasets) != len(datasets):
                        new_line = f'MINER_DATASETS="{",".join(new_datasets)}"'
                        new_lines.append(new_line)
                        changed = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        if changed:
            file_path.write_text("\n".join(new_lines) + "\n")
            print(f"Updated {file_path}")

    except Exception as e:
        print(f"Error processing {file_path}: {e}")

def main():
    project_root = Path("/home/losbanditos/_code/awp-agents-project")
    agents_dir = project_root / "agents"
    
    if not agents_dir.exists():
        print("Agents directory not found.")
        return

    json_files = [
        "session.json",
        "background_session.json",
        "dataset_cursors.json"
    ]

    for agent_dir in agents_dir.iterdir():
        if agent_dir.is_dir():
            # Check JSON files in state directory
            state_dir = agent_dir / "state"
            if state_dir.exists():
                for filename in json_files:
                    remove_wikipedia_from_json(state_dir / filename)
            
            # Check .env file in agent directory
            remove_wikipedia_from_env(agent_dir / ".env")

if __name__ == "__main__":
    main()
