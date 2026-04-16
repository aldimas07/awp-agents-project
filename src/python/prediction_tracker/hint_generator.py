import os
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CSV_FILE = PROJECT_ROOT / "data" / "predictions.csv"
HIVE_AGENTS_BASE_DIR = PROJECT_ROOT / "agents"

# Window settings (tuned untuk stabilitas)
SHORT_TERM = 8      # Untuk visual sequence + streak
LONG_TERM = 40      # Untuk Kelly & win-rate (lebih stabil)

def get_payout_column(df):
    """Robust column detection untuk payout"""
    candidates = ['payout_chips', 'payout', 'reward', 'total_payout']
    for col in candidates:
        if col in df.columns:
            return col
    return None

def get_ticket_column(df):
    """Robust column detection untuk tickets/spent"""
    candidates = ['tickets', 'chips_spent', 'ticket_size', 'size']
    for col in candidates:
        if col in df.columns:
            return col
    return None

def generate_hint(agent_id):
    try:
        df = pd.read_csv(CSV_FILE).tail(1000)  # lebih aman dari 500
        if 'agent_id' not in df.columns or df.empty:
            return "# Strategy Hint\n\nPredictions log is empty or invalid.\n"

        df = df.sort_values(by='timestamp', ascending=False)
        agent_df = df[df['agent_id'] == agent_id]

        if agent_df.empty:
            return "# Strategy Hint\n\nNo recent prediction data available for this agent.\n"

        hint_lines = ["# Strategy Hint (Super-Quant Performance)\n"]

        # ==================== SHORT-TERM (visual + streak) ====================
        recent = agent_df.head(SHORT_TERM)
        last_results = []
        win_streak = 0
        loss_streak = 0
        rejection_count = 0

        for _, row in recent.iterrows():
            status = str(row.get('submission_status', '')).lower()
            if "rejected" in status:
                last_results.append("❌")
                rejection_count += 1
                loss_streak += 1
                win_streak = 0
            elif status in ["filled", "partial"]:
                last_results.append("✅")
                win_streak += 1
                loss_streak = 0
            else:
                last_results.append("⏳")
        
        # Reverse biar Left=Oldest, Right=Newest
        hint_lines.append(f"- Recent Outcomes: {' '.join(reversed(last_results))} (Last {SHORT_TERM} trades)\n")
        hint_lines.append(f"- Current Streak: **{win_streak}W** / **{loss_streak}L**\n")

        if rejection_count >= 2:
            hint_lines.append("> [!WARNING] Reasoning kamu sering REJECTED. Ubah gaya analisis sekarang juga!\n\n")

        # ==================== LONG-TERM KELLY (per-agent) ====================
        long_term_df = agent_df.head(LONG_TERM)
        filled = long_term_df[long_term_df['submission_status'].isin(['filled', 'partial'])]

        payout_col = get_payout_column(df)
        ticket_col = get_ticket_column(df)

        if filled.empty or not payout_col or not ticket_col:
            r_ratio = 1.4
            win_rate = 0.5
        else:
            wins = filled[filled['won'] == True]
            losses = filled[filled['won'] == False]

            avg_win_profit = (wins[payout_col] - wins[ticket_col]).mean() if not wins.empty else 0
            avg_loss = losses[ticket_col].mean() if not losses.empty else 100

            realized_rr = avg_win_profit / avg_loss if avg_loss > 0 else 1.4
            r_ratio = max(0.8, min(realized_rr, 2.5))

            win_rate = filled['won'].mean() if not filled.empty else 0.5

        # Kelly formula
        kelly_pct = win_rate - ((1 - win_rate) / r_ratio) if r_ratio > 0 else 0
        kelly_pct = max(0, min(kelly_pct, 0.40))          # cap 40%
        safe_kelly = kelly_pct * 0.5                      # 0.5x Fractional Kelly

        # Drawdown protection
        if loss_streak >= 3 or win_rate < 0.30:
            safe_kelly = 0.05
            hint_lines.append(f"- **DRAWDOWN PROTECTION ACTIVE** → Size locked at 5%\n")

        hint_lines.append(f"- Strategy Performance: **{win_rate*100:.1f}% Win Rate** | Realized R/R: **{r_ratio:.2f}** | Streak: {win_streak}W/{loss_streak}L\n")
        hint_lines.append(f"- Kelly Recommended Size: **{safe_kelly*100:.1f}% of balance** (Adaptive + Safe)\n")

        # ==================== DIRECTIVE (untuk Gemini 2.5 Flash) ====================
        hint_lines.append("\n**CRITICAL INSTRUCTION FOR LLM REASONING:**\n")
        hint_lines.append("- Output JSON structured as normal, but for the `reasoning` field, you MUST act like a chaotic, retail crypto day trader writing personal notes or live-tweeting.\n")
        hint_lines.append("- DO NOT use bullet points, do NOT use lists, do NOT use robotic words like 'exhibits', 'indicates', 'noteworthy', 'confluence'.\n")
        hint_lines.append("- Write ONE continuous paragraph. Use informal phrasing, short sentences, and slang (e.g. 'looks dumping', 'bags packed', 'getting wicked out').\n")
        hint_lines.append("- Briefly mention the actual metric (e.g., 'macd is dead', 'ema cross just fired', 'adx looks chopped'), but keep it human, messy, and brief.\n")
        hint_lines.append("- Gunakan sizing **persis** sesuai rekomendasi Kelly di atas.\n")

        return "".join(hint_lines)

    except FileNotFoundError:
        return f"# Strategy Hint\n\nError: {CSV_FILE} not found.\n"
    except Exception as e:
        return f"# Strategy Hint\n\nError generating hint: {e}\n"

def main():
    agent_ids = [f"agent-0{i}" for i in range(1, 7)]
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
