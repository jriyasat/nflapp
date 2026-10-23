"""
Rankings page view.
"""
import streamlit as st
import pandas as pd
import predictor as pr
from shared import logo_url, LOGO_CFG, TEAM_SET

def _rankings_data(ctx, season):
    cur = pr.Elo(ctx.games).ratings
    done = ctx.games[(ctx.games["season"] == season) & ctx.games["result"].notna()
                     & ctx.games["game_type"].isin(["REG", "POST"])]
    prev = {}
    if not done.empty:
        lw = int(done["week"].max())
        prev = pr.Elo(ctx.games[~((ctx.games["season"] == season) & (ctx.games["week"] == lw))]).ratings
    rows = []
    for t, r in sorted(cur.items(), key=lambda kv: -kv[1]):
        if t not in TEAM_SET:
            continue  # defunct franchises (STL/SD/OAK) — in history, not in current rankings
        d = r - prev.get(t, r)
        rows.append({"#": len(rows) + 1, "Team": t, "Logo": logo_url(t), "Rating": round(r),
                     "Δ wk": f"{'↑' if d > 0.5 else ('↓' if d < -0.5 else '–')} {d:+.0f}" if prev else "–"})
    return rows

def rankings_page(ctx):
    st.header("📊 Elo Power Rankings")
    st.caption("Our model's power ratings — updated after every game. "
               "Gap between two ratings predicts the winner (+100 pts ≈ 64% win chance). "
               "More: ❓ How It Works.")
    rows = _rankings_data(ctx, ctx.season)
    half = (len(rows) + 1) // 2
    c1, c2 = st.columns(2)
    c1.dataframe(pd.DataFrame(rows[:half]), column_config=LOGO_CFG, hide_index=True, width="stretch")
    c2.dataframe(pd.DataFrame(rows[half:]), column_config=LOGO_CFG, hide_index=True, width="stretch")