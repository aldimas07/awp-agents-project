import os
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3] # awp-agents-project/ (script is in src/python/prediction_tracker/)

# CSV_FILE is in data/
CSV_FILE = PROJECT_ROOT / "data" / "predictions.csv"
HIVE_AGENTS_BASE_DIR = PROJECT_ROOT / "agents"
LAST_N_RESULTS = 5 # Number of last results to summarize

def generate_hint(agent_id):
    """Generates a strategy hint for a given agent_id based on last N results."""
    try:
        # Optimization: Only read the bottom of the CSV to avoid RAM bloat (B07)
        try:
            # Try to read only the last 500 rows if the file is large
            df = pd.read_csv(CSV_FILE).tail(500)
        except Exception:
            df = pd.read_csv(CSV_FILE)
            
        if 'agent_id' not in df.columns:
            return "# Strategy Hint\n\nPredictions log is empty or invalid.\n"

        df = df.sort_values(by='timestamp', ascending=False)
        agent_df = df[df['agent_id'] == agent_id].head(LAST_N_RESULTS)

        if agent_df.empty:
            return "# Strategy Hint\n\nNo recent prediction data available for this agent.\n"

        hint_lines = ["# Strategy Hint (Performance Performance)\n"] 

        # Summary of last results
        last_results = []
        rejection_count = 0
        
        for _, row in agent_df.iterrows():
            status = str(row.get('submission_status', '')).lower()
            
            if "rejected" in status:
                last_results.append("❌") # Rejected
                rejection_count += 1
            elif status == "filled":
                last_results.append("✅") # Full win/fill
            elif status == "partial":
                last_results.append("🌗") # Partial fill
            elif status == "open":
                last_results.append("⏳") # Still open
            else:
                last_results.append("?") # Unknown

        hint_lines.append(f"- Recent Outcomes: {' '.join(reversed(last_results))} (Left=Oldest, Right=Newest)\n")

        # Rejection Warning
        if rejection_count >= 2:
            hint_lines.append("> [!WARNING]\n")
            hint_lines.append("> Your reasoning is being REJECTED frequently. You MUST change your analytical style immediately to avoid being flagged as a bot.\n\n")

        # 1. Performance-based Kelly Criterion (v2.0)
        filled_count = last_results.count("✅") + last_results.count("🌗")
        num_trades = len(last_results)
        win_rate = filled_count / num_trades if num_trades > 0 else 0
        
        # Simple Kelly: K% = W - (1-W)/R. Assuming Reward:Risk ratio of 1.4 for 15m/30m windows.
        r_ratio = 1.4
        kelly_pct = win_rate - ((1 - win_rate) / r_ratio)
        kelly_pct = max(0, min(kelly_pct, 0.4)) # Cap at 40%
        
        # Fractional Kelly (0.5x) for safety
        safe_kelly = kelly_pct * 0.5
        
        hint_lines.append(f"- Strategy Performance: **{win_rate*100:.1f}% Win Rate**\n")
        
        if win_rate > 0.6:
            hint_lines.append(f"- Kelly Recommended Size: **{safe_kelly*100:.1f}% of balance** (High Confidence)\n")
        elif win_rate < 0.3 and num_trades >= 3:
             hint_lines.append(f"- Kelly Recommended Size: **5% (Fixed)** - *Drawdown protection active.*\n")
             safe_kelly = 0.05
        else:
            hint_lines.append(f"- Kelly Recommended Size: **{safe_kelly*100:.1f}% of balance** (Adaptive)\n")

        hint_lines.append(f"\n# Technical Performance Report\n")
        hint_lines.append(f"Last {num_trades} trades sequence: {' '.join(last_results)}\n")
        
        # Recent Failure Analysis (Pseudo-reasoning extraction)
        failed_agents = df[(df['agent_id'] == agent_id) & (df['submission_status'].str.contains('rejected', case=False, na=False))].head(2)
        if not failed_agents.empty:
            hint_lines.append("\n**Reason for recent failures:**\n")
            for _, failed in failed_agents.iterrows():
                err = failed.get('error_message', 'Unknown error')
                hint_lines.append(f"- {err}\n")

        # Instruction for the LLM
        hint_lines.append(f"\n**DIRECTIVE:** Your base sizing for this round should be around **{safe_kelly*100:.1f}%** of your balance. If your confidence is extremely high (85+), you may bump it slightly. If you see ADX < 20, SKIP.\n")

        return "".join(hint_lines)

    except FileNotFoundError:
        return f"# Strategy Hint (Last 5 Predictions)\n\nError: {CSV_FILE} not found. Logger might not be running or no data yet.\n"
    except pd.errors.EmptyDataError:
        return f"# Strategy Hint (Last 5 Predictions)\n\nError: {CSV_FILE} is empty. No prediction data yet.\n"
    except Exception as e:
        return f"# Strategy Hint (Last 5 Predictions)\n\nError generating hint: {e}\n"

def main():
    agent_ids = [
        f"agent-0{i}" for i in range(1, 7) # agent-01 to agent-06
    ]

    for agent_id in agent_ids:
        hint_content = generate_hint(agent_id)
        
        # All agents now have their home dir directly under agents/agent-id/home
        hint_dir = HIVE_AGENTS_BASE_DIR / agent_id / "home"

        os.makedirs(hint_dir, exist_ok=True)
        hint_file_path = hint_dir / "strategy_hint.md"
        
        with open(hint_file_path, 'w') as f:
            f.write(hint_content)
        print(f"Generated hint for {agent_id} at {hint_file_path}")

if __name__ == "__main__":
    main()
