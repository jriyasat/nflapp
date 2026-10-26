"""
Rankings page view.
"""
import streamlit as st
import pandas as pd
import altair as alt
import predictor as pr
from shared import logo_url, LOGO_CFG, TEAM_SET, get_elo

TEAM_COLORS = {  # official primary brand color per team, for the progression chart
    "ARI": "#97233F", "ATL": "#A71930", "BAL": "#241773", "BUF": "#00338D",
    "CAR": "#0085CA", "CHI": "#0B162A", "CIN": "#FB4F14", "CLE": "#311D00",
    "DAL": "#041E42", "DEN": "#FB4F14", "DET": "#0076B6", "GB": "#203731",
    "HOU": "#03202F", "IND": "#002C5F", "JAX": "#006778", "KC": "#E31837",
    "LAC": "#0080C6", "LAR": "#003594", "LV": "#000000", "MIA": "#008E97",
    "MIN": "#4F2683", "NE": "#002244", "NO": "#D3BC8D", "NYG": "#0B2265",
    "NYJ": "#125740", "PHI": "#004C54", "PIT": "#FFB612", "SEA": "#002244",
    "SF": "#AA0000", "TB": "#D50A0A", "TEN": "#4B92DB", "WAS": "#5A1414",
}

def _rankings_data(ctx, season, elo):
    cur = elo.ratings
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

def _history_df(elo, season):
    rows = [{"Week": wk, "Team": t, "Rating": round(r)}
            for s, wk, ratings in elo.history if s == season
            for t, r in ratings.items() if t in TEAM_SET]
    return pd.DataFrame(rows)

def rankings_page(ctx):
    st.header("📊 Elo Power Rankings")
    st.caption("Our model's power ratings — updated after every game. "
               "Gap between two ratings predicts the winner (+100 pts ≈ 64% win chance). "
               "More: ❓ How It Works.")
    elo = get_elo(ctx.games)
    rows = _rankings_data(ctx, ctx.season, elo)
    half = (len(rows) + 1) // 2
    c1, c2 = st.columns(2)
    c1.dataframe(pd.DataFrame(rows[:half]), column_config=LOGO_CFG, hide_index=True, width="stretch")
    c2.dataframe(pd.DataFrame(rows[half:]), column_config=LOGO_CFG, hide_index=True, width="stretch")

    hist = _history_df(elo, ctx.season)
    if not hist.empty:
        st.subheader("📈 Season Progression")
        st.caption("Click a team in the legend to toggle it off/on — build up any subset to compare.")
        sel = alt.selection_point(fields=["Team"], bind="legend", toggle="true", empty=False)
        domain = sorted(TEAM_COLORS)
        chart = (alt.Chart(hist).mark_line(point=True)
                 .encode(x=alt.X("Week:O"), y=alt.Y("Rating:Q", scale=alt.Scale(zero=False)),
                         color=alt.Color("Team:N",
                                         scale=alt.Scale(domain=domain, range=[TEAM_COLORS[t] for t in domain]),
                                         legend=alt.Legend(symbolLimit=40, columns=2)),
                         opacity=alt.condition(sel, alt.value(0.07), alt.value(1)),
                         tooltip=["Team", "Week", "Rating"])
                 .add_params(sel)
                 .properties(height=440))
        st.altair_chart(chart, width="stretch")