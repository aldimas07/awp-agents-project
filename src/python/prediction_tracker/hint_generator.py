import os
import csv
import argparse
from pathlib import Path

try:
    import pandas as pd
except ModuleNotFoundError:
    pd = None

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

def load_agent_history(agent_id):
    outcome_file = PROJECT_ROOT / "data" / f"prediction_outcomes_{agent_id}.csv"
    if outcome_file.exists():
        df = pd.read_csv(outcome_file).tail(1000)
        if not df.empty:
            return df, True
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE).tail(1000)
        if 'agent_id' in df.columns and not df.empty:
            df = df[df['agent_id'] == agent_id]
            if not df.empty:
                return df, False
    return pd.DataFrame(), False

def bool_series(series):
    return series.astype(str).str.lower().isin(["true", "1", "yes", "won"])

def load_agent_history_rows(agent_id):
    outcome_file = PROJECT_ROOT / "data" / f"prediction_outcomes_{agent_id}.csv"
    if outcome_file.exists():
        with open(outcome_file, newline='') as f:
            rows = list(csv.DictReader(f))
        if rows:
            return rows[-1000:], True
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, newline='') as f:
            rows = [row for row in csv.DictReader(f) if row.get('agent_id') == agent_id]
        if rows:
            return rows[-1000:], False
    return [], False

def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def generate_hint_without_pandas(agent_id):
    hint_lines = ["# Strategy Hint (Super-Quant Performance)\n\n"]
    persona = get_agent_persona(agent_id)
    hint_lines.append(f"**DIRECTIVE:**\n")
    hint_lines.append(f"- **ACTIVE PERSONA:** {persona}\n")

    rows, has_resolved = load_agent_history_rows(agent_id)
    if rows:
        sort_key = 'resolved_at' if has_resolved else 'timestamp' if 'timestamp' in rows[0] else 'created_at'
        rows = sorted(rows, key=lambda r: r.get(sort_key, ''), reverse=True)
        recent = rows[:SHORT_TERM]
        last_results = []
        win_streak = 0
        loss_streak = 0

        for row in recent:
            won = str(row.get('won', '')).lower()
            if has_resolved and won in ['true', 'false']:
                if won == 'true':
                    last_results.append("✅")
                    win_streak += 1
                    loss_streak = 0
                else:
                    last_results.append("❌")
                    loss_streak += 1
                    win_streak = 0
            else:
                status = str(row.get('submission_status', '')).lower()
                if "error" in status or "rejected" in status:
                    last_results.append("❌")
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

        filled = [
            row for row in rows[:LONG_TERM]
            if str(row.get('won', '')).lower() in ['true', 'false'] and to_float(row.get('tickets_filled')) > 0
        ]
        if filled:
            wins = sum(1 for row in filled if str(row.get('won', '')).lower() == 'true')
            win_rate = wins / len(filled)
            hint_lines.append(f"- Resolved Win Rate: **{win_rate*100:.1f}%** over {len(filled)} filled/resolved trades\n")
        else:
            win_rate = 0.5

        r_ratio = 1.4
        kelly_pct = max(0, min(win_rate - ((1 - win_rate) / r_ratio), 0.40))
        safe_kelly = kelly_pct * 0.5
        if loss_streak >= 3 or win_rate < 0.45:
            safe_kelly = min(safe_kelly, 0.05)
            hint_lines.append(f"- **ACCURACY PROTECTION ACTIVE** → Skip weak setups; size capped near 5%\n")
        hint_lines.append(f"- Kelly Recommended Size: **{safe_kelly*100:.1f}% of balance**\n")

    append_common_directives(hint_lines)
    return "".join(hint_lines)

def append_common_directives(hint_lines):
    hint_lines.append("- Output valid JSON starting with `DECISION: `.\n")
    hint_lines.append("- Balanced accuracy mode: only submit when confidence is above the threshold and the setup has a real directional edge.\n")
    hint_lines.append("- Include `confidence`, `edge_reason`, and `invalid_if` in the JSON.\n")
    hint_lines.append("- If deterministic signal and your direction conflict, skip unless your confidence is very high and your edge is concrete.\n")
    hint_lines.append("- **JSON FORMAT**: You MUST use DOUBLE QUOTES (`\"`) for all keys and string values. Single quotes (`'`) are INVALID in JSON.\n")
    hint_lines.append("- The `reasoning` field must be a DOUBLE QUOTED string value. Include the challenge answer INSIDE this string at the very end.\n")
    hint_lines.append("- For `reasoning`: Describe specific price action, indicators, and volume trends in detail. **Hard minimum: 255 characters**.\n")
    hint_lines.append("- **ANTI-BOT PROTOCOL**: Avoid 'Based on', 'I believe', 'Therefore', 'Furthermore'. Just spit raw data and conviction.\n")
    hint_lines.append("- **CHALLENGE COMPLIANCE**: ALWAYS end your `reasoning` string (INSIDE the JSON) with 'Challenge: <number>' on a new line, replacing <number> with the correct value.\n")
    hint_lines.append("- Decide an appropriate ticket size autonomously based on your analysis.\n")

def generate_hint(agent_id):
    try:
        if pd is None:
            return generate_hint_without_pandas(agent_id)

        hint_lines = ["# Strategy Hint (Super-Quant Performance)\n\n"]
        
        persona = get_agent_persona(agent_id)
        hint_lines.append(f"**DIRECTIVE:**\n")
        hint_lines.append(f"- **ACTIVE PERSONA:** {persona}\n")
        
        agent_df, has_resolved = load_agent_history(agent_id)
        if not agent_df.empty:
            sort_col = 'resolved_at' if has_resolved and 'resolved_at' in agent_df.columns else 'timestamp' if 'timestamp' in agent_df.columns else 'created_at' if 'created_at' in agent_df.columns else None
            if sort_col:
                agent_df = agent_df.sort_values(by=sort_col, ascending=False)

            if not agent_df.empty:
                # ==================== SHORT-TERM ====================
                recent = agent_df.head(SHORT_TERM)
                last_results = []
                win_streak = 0
                loss_streak = 0
                rejection_count = 0

                for _, row in recent.iterrows():
                    if has_resolved and 'won' in recent.columns and str(row.get('won', '')).lower() in ['true', 'false']:
                        if str(row.get('won')).lower() == 'true':
                            last_results.append("✅")
                            win_streak += 1
                            loss_streak = 0
                        else:
                            last_results.append("❌")
                            loss_streak += 1
                            win_streak = 0
                    else:
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
                if has_resolved and 'won' in long_term_df.columns:
                    filled = long_term_df[long_term_df.get('tickets_filled', 0).fillna(0).astype(float) > 0] if 'tickets_filled' in long_term_df.columns else long_term_df
                elif 'submission_status' in long_term_df.columns:
                    filled = long_term_df[long_term_df['submission_status'].isin(['filled', 'partial'])]
                else:
                    filled = pd.DataFrame()

                payout_col = get_payout_column(agent_df)
                ticket_col = get_ticket_column(agent_df)

                if not filled.empty and has_resolved and 'won' in filled.columns:
                    won_flags = bool_series(filled['won'])
                    wins = filled[won_flags]
                    losses = filled[~won_flags]

                    if payout_col and ticket_col:
                        avg_win_profit = (pd.to_numeric(wins[payout_col], errors='coerce') - pd.to_numeric(wins[ticket_col], errors='coerce')).mean() if not wins.empty else 0
                        avg_loss = pd.to_numeric(losses[ticket_col], errors='coerce').mean() if not losses.empty else 100

                        realized_rr = avg_win_profit / avg_loss if avg_loss > 0 else 1.4
                        r_ratio = max(0.8, min(realized_rr, 2.5))
                    else:
                        r_ratio = 1.4
                    win_rate = won_flags.mean()
                    hint_lines.append(f"- Resolved Win Rate: **{win_rate*100:.1f}%** over {len(filled)} filled/resolved trades\n")
                else:
                    r_ratio = 1.4
                    win_rate = 0.5

                kelly_pct = win_rate - ((1 - win_rate) / r_ratio) if r_ratio > 0 else 0
                kelly_pct = max(0, min(kelly_pct, 0.40))
                safe_kelly = kelly_pct * 0.5

                if loss_streak >= 3 or win_rate < 0.45:
                    safe_kelly = min(safe_kelly, 0.05)
                    hint_lines.append(f"- **ACCURACY PROTECTION ACTIVE** → Skip weak setups; size capped near 5%\n")

                hint_lines.append(f"- Kelly Recommended Size: **{safe_kelly*100:.1f}% of balance**\n")

        append_common_directives(hint_lines)

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
