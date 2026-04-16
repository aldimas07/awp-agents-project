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
        df = pd.read_csv(CSV_FILE)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values(by='timestamp', ascending=False)

        agent_df = df[df['agent_id'] == agent_id].head(LAST_N_RESULTS)

        if agent_df.empty:
            return "# Strategy Hint (Last 5 Predictions)\n\nNo recent prediction data available for this agent.\n"

        hint_lines = ["# Strategy Hint (Last 5 Predictions)\n"] # Added newline for better formatting

        # Summary of last N results
        last_results = []
        for _, row in agent_df.iterrows():
            status = row['submission_status']
            # Simple P/L estimation from filled_amount vs predicted_amount
            # This is a very basic heuristic. Real P/L is more complex.
            if pd.notna(row['filled_amount']) and pd.notna(row['predicted_amount']):
                if row['filled_amount'] > 0 and row['filled_amount'] >= row['predicted_amount'] * 0.5: # Consider >50% filled a 'win'
                    last_results.append("W")
                elif row['filled_amount'] > 0 and row['filled_amount'] < row['predicted_amount'] * 0.5: # Partial win
                    last_results.append("P")
                else:
                    last_results.append("L")
            else:
                last_results.append("U") # Unknown

        hint_lines.append(f"- Last {LAST_N_RESULTS} results: {' '.join(reversed(last_results))}\n")

        # Basic analysis of recent performance
        wins = last_results.count("W")
        losses = last_results.count("L")
        partials = last_results.count("P")
        total_known = wins + losses + partials

        if total_known > 0:
            win_rate = (wins / total_known) * 100
            if win_rate >= 60: # Good performance
                hint_lines.append("- Current sentiment: Strong. Maintain strategy.\n")
            elif win_rate <= 40: # Poor performance
                hint_lines.append("- Current sentiment: Weak. Consider adjusting persona or reducing ticket size.\n")
            else:
                hint_lines.append("- Current sentiment: Neutral. Continue monitoring.\n")
        else:
            hint_lines.append("- No conclusive sentiment from recent data.\n")

        # Add LLM Model info
        unique_models = agent_df['llm_model'].dropna().unique()
        if len(unique_models) > 0:
            hint_lines.append(f"- LLM Model used: {', '.join(unique_models)}\n")
        
        # Add Persona info
        unique_personas = agent_df['persona'].dropna().unique()
        if len(unique_personas) > 0:
            hint_lines.append(f"- Persona used: {', '.join(unique_personas)}\n")

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
