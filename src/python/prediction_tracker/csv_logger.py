
import os
import re
import time
import json
import csv
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3] # awp-agents-project/ (script is in src/python/prediction_tracker/)

# LOG_DIRS construction based on new agents/agent-0X/logs structure
LOG_DIRS = {
    f"agent-0{i}": PROJECT_ROOT / "agents" / f"agent-0{i}" / "logs" for i in range(1, 7) # agent-01 to agent-06
}

CSV_FILE = PROJECT_ROOT / "data" / "predictions.csv"
SLEEP_INTERVAL = 5 # seconds to sleep between log checks

# --- CSV Headers ---
CSV_HEADERS = [
    "timestamp", "agent_id", "iteration", "balance", "persona", "timeslot_used",
    "timeslot_resets_in", "market", "challenge_nonce", "llm_model",
    "submission_status", "filled_amount", "predicted_amount", "llm_response_time_s",
    "submission_time_s", "error_message", "is_retry"
]

def initialize_csv():
    """Ensures the CSV file exists with correct headers."""
    # Ensure data directory exists
    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_FILE.exists():
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)
        print(f"Created new CSV file: {CSV_FILE}")

def parse_log_entry(log_line, agent_id, current_state):
    """
    Parses a single log line and updates the current state for an agent.
    Returns a dict with extracted data if a submission is complete, otherwise None.
    """
    data = {"agent_id": agent_id, "timestamp": datetime.now().isoformat()}

    # --- Balance and Timeslot ---
    balance_match = re.search(r"balance=(\d+), persona=(\w+), timeslot=(\d+)/(\d+) used, resets in (\d+)s", log_line)
    if balance_match:
        current_state["balance"] = int(balance_match.group(1))
        current_state["persona"] = balance_match.group(2)
        current_state["timeslot_used"] = int(balance_match.group(3))
        current_state["timeslot_total"] = int(balance_match.group(4)) # Not directly used in CSV, but good for context
        current_state["timeslot_resets_in"] = int(balance_match.group(5))
        iter_match = re.search(r"=== iteration (\d+) ===", log_line)
        if iter_match:
            current_state["iteration"] = int(iter_match.group(1))

    # --- Challenge ---
    challenge_match = re.search(r"got challenge nonce=(ch_\w+) for market=(\S+)", log_line)
    if challenge_match:
        current_state["challenge_nonce"] = challenge_match.group(1)
        current_state["market"] = challenge_match.group(2)
        current_state["is_retry"] = False # Reset retry status

    # --- LLM Call ---
    llm_call_match = re.search(r"calling direct LLM (\S+) @", log_line)
    if llm_call_match:
        current_state["llm_model"] = llm_call_match.group(1)

    # --- LLM Response Time ---
    llm_resp_match = re.search(r"LLM responded \((\d+\.?\d*)s,", log_line)
    if llm_resp_match:
        current_state["llm_response_time_s"] = float(llm_resp_match.group(1))

    # --- Submission Result ---
    # Example: submission result — status=open, filled=0/3500
    # Example: submission result — status=filled, filled=3000/3000
    submission_result_match = re.search(r"submission result — status=(\w+), filled=(\d+)/(\d+)", log_line)
    if submission_result_match:
        data.update(current_state) # Capture all current state before adding submission specifics
        data["submission_status"] = submission_result_match.group(1)
        data["filled_amount"] = int(submission_result_match.group(2))
        data["predicted_amount"] = int(submission_result_match.group(3))
        # Infer profit/loss - simple heuristic
        # This is very basic and might need refinement based on exact game mechanics
        # For now, we only log if it's filled or pending. Actual P/L will be based on final balance changes.
        return data

    # --- Errors ---
    error_match = re.search(r"ERROR] POST .* returned HTTP (\d+)", log_line)
    if error_match:
        err_msg_match = re.search(r"message\":\"(.*?)\"", log_line)
        data["error_message"] = err_msg_match.group(1) if err_msg_match else "Unknown error"
        return data # Log error as a separate event if needed, or associate with last submission

    # --- Spell Fail Retry ---
    spell_retry_match = re.search(r"CHALLENGE_SPELL_FAIL .* retrying LLM", log_line)
    if spell_retry_match:
        current_state["is_retry"] = True
    
    return None

def follow_log_file(agent_id, log_file_path, last_position):
    """Reads new lines from a log file."""
    new_entries = []
    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(last_position[agent_id])
            for line in f:
                new_entries.append(line.strip())
            last_position[agent_id] = f.tell()
    except FileNotFoundError:
        print(f"Log file not found for {agent_id}: {log_file_path}")
    except Exception as e:
        print(f"Error reading log file for {agent_id}: {e}")
    return new_entries

def write_to_csv(data_row):
    """Writes a parsed log entry dictionary to the CSV."""
    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(data_row)
    # print(f"Logged: {data_row['agent_id']} - Iteration {data_row.get('iteration')} - Status: {data_row.get('submission_status')}")


def main():
    initialize_csv()
    last_positions = {agent_id: 0 for agent_id in LOG_DIRS.keys()}
    current_states = {agent_id: {} for agent_id in LOG_DIRS.keys()}

    # Populate initial last_positions
    for agent_id, log_base_dir in LOG_DIRS.items():
        log_file_name = "predict.log" if "awp-hive" in str(log_base_dir) or "agent-runs" in str(log_base_dir) else "predict.log" # Defaulting for now
        log_file_path = os.path.join(log_base_dir, log_file_name)
        if os.path.exists(log_file_path):
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, os.SEEK_END)
                last_positions[agent_id] = f.tell()
        else:
            print(f"Warning: Log file not found at {log_file_path} for {agent_id}. Will start tracking if created.")


    print(f"Starting CSV logger. Monitoring logs for {list(LOG_DIRS.keys())}...")
    while True:
        for agent_id, log_base_dir_path in LOG_DIRS.items():
            # log_base_dir_path is already a Path object to the agent's logs directory
            # For now, we only monitor predict.log. Extend here if mine.log parsing is needed.
            log_file_name = "predict.log"
            log_file_path = log_base_dir_path / log_file_name
            
            new_lines = follow_log_file(agent_id, log_file_path, last_positions)
            for line in new_lines:
                parsed_data = parse_log_entry(line, agent_id, current_states[agent_id])
                if parsed_data:
                    # Filter out any keys not in CSV_HEADERS before writing
                    filtered_data = {k: parsed_data.get(k, '') for k in CSV_HEADERS}
                    write_to_csv(filtered_data)
        time.sleep(SLEEP_INTERVAL)

if __name__ == "__main__":
    main()
