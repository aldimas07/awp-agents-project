import os
import pandas as pd
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CSV_FILE = PROJECT_ROOT / "data" / "predictions.csv"
HIVE_AGENTS_BASE_DIR = PROJECT_ROOT / "agents"

# Window settings
SHORT_TERM = 8      # For visual sequence + streak
LONG_TERM = 40      # For Kelly & win-rate

def get_payout_column(df):
    """Robust column detection for payout"""
    candidates = ['payout_chips', 'payout', 'reward', 'total_payout']
    for col in candidates:
        if col in df.columns:
            return col
    return None

def get_ticket_column(df):
    """Robust column detection for tickets/spent"""
    candidates = ['tickets', 'chips_spent', 'ticket_size', 'size']
    for col in candidates:
        if col in df.columns:
            return col
    return None

def get_agent_persona(agent_id):
    """Returns a specific persona for known agents, or a default one."""
    personas = {
        "agent-13": "Skeptical Technical Analyst. Focus on volume exhaustion and fakeouts.",
        "agent-26": "Aggressive Trend Follower. Focus on breakout strength and ADX momentum.",
        "agent-32": "Orderbook Specialist. Focus on bid/ask imbalance and liquidity gaps.",
        "agent-37": "Skeptical Technical Analyst. Focus on volume exhaustion and fakeouts.",
    }
    return personas.get(agent_id, "Senior Quantitative Lead. Focus on technical indicators and raw numbers.")

def generate_hint(agent_id):
    try:
        hint_lines = ["# Strategy Hint (Super-Quant Performance)\n\n"]
        
        persona = get_agent_persona(agent_id)
        hint_lines.append(f"**DIRECTIVE:**\n")
        hint_lines.append(f"- **ACTIVE PERSONA:** {persona}\n")
        
        if os.path.exists(CSV_FILE):
            df = pd.read_csv(CSV_FILE).tail(1000)
            if 'agent_id' in df.columns and not df.empty:
                df = df.sort_values(by='timestamp', ascending=False)
                agent_df = df[df['agent_id'] == agent_id]

                if not agent_df.empty:
                    # ==================== SHORT-TERM ====================
                    recent = agent_df.head(SHORT_TERM)
                    last_results = []
                    win_streak = 0
                    loss_streak = 0
                    rejection_count = 0

                    for _, row in recent.iterrows():
                        status = str(row.get('submission_status', '')).lower()
                        if "error" in status or "rejected" in status:
                            last_results.append("❌")
                            rejection_count += 1
                            loss_streak += 1
                            win_streak = 0
                        elif status in ["filled", "partial", "open"]:
                            last_results.append("✅")
                            win_streak += 1
                            loss_streak = 0
                        else:
                            last_results.append("⏳")
                    
                    hint_lines.append(f"- Recent Outcomes: {' '.join(reversed(last_results))} (Last {SHORT_TERM} trades)\n")
                    hint_lines.append(f"- Current Streak: **{win_streak}W** / **{loss_streak}L**\n")

                    # ==================== LONG-TERM KELLY ====================
                    long_term_df = agent_df.head(LONG_TERM)
                    filled = long_term_df[long_term_df['submission_status'].isin(['filled', 'partial'])]

                    payout_col = get_payout_column(df)
                    ticket_col = get_ticket_column(df)

                    if not filled.empty and payout_col and ticket_col:
                        wins = filled[filled['won'] == True]
                        losses = filled[filled['won'] == False]

                        avg_win_profit = (wins[payout_col] - wins[ticket_col]).mean() if not wins.empty else 0
                        avg_loss = losses[ticket_col].mean() if not losses.empty else 100

                        realized_rr = avg_win_profit / avg_loss if avg_loss > 0 else 1.4
                        r_ratio = max(0.8, min(realized_rr, 2.5))
                        win_rate = filled['won'].mean()
                    else:
                        r_ratio = 1.4
                        win_rate = 0.5

                    kelly_pct = win_rate - ((1 - win_rate) / r_ratio) if r_ratio > 0 else 0
                    kelly_pct = max(0, min(kelly_pct, 0.40))
                    safe_kelly = kelly_pct * 0.5

                    if loss_streak >= 3 or win_rate < 0.30:
                        safe_kelly = 0.05
                        hint_lines.append(f"- **DRAWDOWN PROTECTION ACTIVE** → Size locked at 5%\n")

                    hint_lines.append(f"- Kelly Recommended Size: **{safe_kelly*100:.1f}% of balance**\n")

        hint_lines.append("- Output valid JSON starting with `DECISION: `.\n")
        hint_lines.append("- **JSON FORMAT**: You MUST use DOUBLE QUOTES (`\"`) for all keys and string values. Single quotes (`'`) are INVALID in JSON.\n")
        hint_lines.append("- The `reasoning` field must be a DOUBLE QUOTED string value. Include the challenge answer INSIDE this string at the very end.\n")
        hint_lines.append("- For `reasoning`: Describe specific price action, indicators, and volume trends in detail. **Hard minimum: 255 characters**.\n")
        hint_lines.append("- **ANTI-BOT PROTOCOL**: Avoid 'Based on', 'I believe', 'Therefore', 'Furthermore'. Just spit raw data and conviction.\n")
        hint_lines.append("- **CHALLENGE COMPLIANCE**: ALWAYS end your `reasoning` string (INSIDE the JSON) with 'Challenge: <number>' on a new line, replacing <number> with the correct value.\n")
        hint_lines.append("- Decide an appropriate ticket size autonomously based on your analysis.\n")

        return "".join(hint_lines)

    except Exception as e:
        return f"# Strategy Hint\n\nError generating hint: {e}\n"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=str, help="Agent ID (e.g. agent-13)")
    args = parser.parse_args()

    if args.agent:
        agent_ids = [args.agent]
    else:
        # Default to agents 13, 26, 32, 37 if no agent specified (the active fleet)
        agent_ids = ["agent-13", "agent-26", "agent-32", "agent-37"]

    for agent_id in agent_ids:
        hint_content = generate_hint(agent_id)
        hint_dir = HIVE_AGENTS_BASE_DIR / agent_id / "home"
        os.makedirs(hint_dir, exist_ok=True)
        hint_file_path = hint_dir / "strategy_hint.md"
        
        with open(hint_file_path, 'w') as f:
            f.write(hint_content)
        print(f"✅ Generated improved hint for {agent_id}")

if __name__ == "__main__":
    main()
