
import os
import re
import time
import json
import csv
import fcntl
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3] 
CSV_FILE = PROJECT_ROOT / "data" / "predictions.csv"
SLEEP_INTERVAL = 5 

# --- CSV Headers ---
CSV_HEADERS = [
    "timestamp", "agent_id", "iteration", "balance", "persona", "timeslot_used",
    "timeslot_resets_in", "market", "challenge_nonce", "llm_model",
    "submission_status", "filled_amount", "predicted_amount", "llm_response_time_s",
    "submission_time_s", "error_message", "is_retry"
]

def initialize_csv():
    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_FILE.exists():
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
        print(f"Created new CSV file: {CSV_FILE}")

def parse_log_entry(log_line, agent_id, current_state):
    data = {"agent_id": agent_id, "timestamp": datetime.now().isoformat()}

    balance_match = re.search(r"balance=(\d+), persona=(\w+), timeslot=(\d+)/(\d+) used, resets in (\d+)s", log_line)
    if balance_match:
        current_state["balance"] = int(balance_match.group(1))
        current_state["persona"] = balance_match.group(2)
        current_state["timeslot_used"] = int(balance_match.group(3))
        current_state["timeslot_resets_in"] = int(balance_match.group(5))
        
    iter_match = re.search(r"=== iteration (\d+) ===", log_line)
    if iter_match:
        current_state["iteration"] = int(iter_match.group(1))

    challenge_match = re.search(r"got challenge nonce=(ch_\w+) for market=(\S+)", log_line)
    if challenge_match:
        current_state["challenge_nonce"] = challenge_match.group(1)
        current_state["market"] = challenge_match.group(2)
        current_state["is_retry"] = False

    llm_call_match = re.search(r"calling direct LLM (\S+) @", log_line)
    if llm_call_match:
        current_state["llm_model"] = llm_call_match.group(1)

    llm_resp_match = re.search(r"LLM responded \((\d+\.?\d*)s,", log_line)
    if llm_resp_match:
        current_state["llm_response_time_s"] = float(llm_resp_match.group(1))

    submission_result_match = re.search(r"submission result — status=(\w+), filled=(\d+)/(\d+)", log_line)
    if submission_result_match:
        data.update(current_state)
        data["submission_status"] = submission_result_match.group(1)
        data["filled_amount"] = int(submission_result_match.group(2))
        data["predicted_amount"] = int(submission_result_match.group(3))
        return data

    error_match = re.search(r"ERROR] POST .* returned HTTP (\d+)", log_line)
    if error_match:
        err_msg_match = re.search(r"message\":\"(.*?)\"", log_line)
        data.update(current_state)
        data["submission_status"] = "error"
        data["error_message"] = err_msg_match.group(1) if err_msg_match else "Unknown error"
        return data

    spell_retry_match = re.search(r"CHALLENGE_SPELL_FAIL .* retrying LLM", log_line)
    if spell_retry_match:
        current_state["is_retry"] = True
    
    skip_match = re.search(r"LLM chose to skip: (.*)", log_line)
    if skip_match:
        data.update(current_state)
        data["submission_status"] = "skipped"
        data["error_message"] = skip_match.group(1)
        data["filled_amount"] = 0
        data["predicted_amount"] = 0
        return data

    return None

def follow_log_file(agent_id, log_file_path, last_position):
    new_entries = []
    try:
        if not os.path.exists(log_file_path):
            return []
        
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            if agent_id not in last_position:
                last_position[agent_id] = 0
            
            f.seek(last_position[agent_id])
            for line in f:
                new_entries.append(line.strip())
            last_position[agent_id] = f.tell()
    except Exception as e:
        print(f"Error reading log file for {agent_id}: {e}")
    return new_entries

RECENT_WRITES = set()
RECENT_WRITES_MAX_SIZE = 1000

def write_to_csv(data_row):
    global RECENT_WRITES
    entry_id = f"{data_row.get('agent_id')}_{data_row.get('timestamp')}_{data_row.get('submission_status')}"
    if entry_id in RECENT_WRITES:
        return
    
    with open(CSV_FILE, 'a', newline='') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writerow(data_row)
            f.flush()
            RECENT_WRITES.add(entry_id)
            if len(RECENT_WRITES) > RECENT_WRITES_MAX_SIZE:
                RECENT_WRITES.pop()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def main():
    initialize_csv()
    last_positions = {}
    current_states = {}
    agents_dir = PROJECT_ROOT / "agents"

    print(f"Starting Dynamic CSV logger...")
    while True:
        # Dynamically discover agents
        if agents_dir.exists():
            for agent_folder in sorted(agents_dir.iterdir()):
                if agent_folder.is_dir() and agent_folder.name.startswith("agent-"):
                    agent_id = agent_folder.name
                    log_file_path = agent_folder / "logs" / "predict.log"
                    
                    if agent_id not in current_states:
                        current_states[agent_id] = {}
                        last_positions[agent_id] = 0
                    
                    new_lines = follow_log_file(agent_id, log_file_path, last_positions)
                    for line in new_lines:
                        parsed_data = parse_log_entry(line, agent_id, current_states[agent_id])
                        if parsed_data:
                            filtered_data = {k: parsed_data.get(k, '') for k in CSV_HEADERS}
                            write_to_csv(filtered_data)
        
        time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    main()
