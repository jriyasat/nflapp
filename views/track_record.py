"""
Track Record page view.
"""
import streamlit as st
import pandas as pd
import tracker
from shared import logo_url, LOGO_CFG

def _pick_clv(p):
    """Closing line value: pts of line the model captured vs the close, in its favor.
    market_val_log is home-perspective; closing_line is team-perspective (set at grading)."""
    if p["grade"] not in ("won", "lost", "push"):
        return None
    try:
        if p["pick_type"] == "spread":
            away_team = str(p["game"]).split(" @ ")[0]
            log_line = float(p["market_val_log"])
            team_log = -log_line if p["side"] == away_team else log_line
            return team_log - float(p["closing_line"])
        sign = 1.0 if p["side"] == "over" else -1.0
        return sign * (float(p["closing_line"]) - float(p["market_val_log"]))
    except Exception:
        return None


def track_record_page(ctx):
    st.header("📈 Model Track Record")
    picks = tracker.grade_predictions(ctx.games)
    if not len(picks):
        st.info("No picks logged yet. The morning brief logs every |edge| ≥ 2 pt call the model "
                "makes (sides + totals) and grades them against the **closing line**.")
        return
    s = tracker.summary(picks)
    c = st.columns(5)
    c[0].metric("Sides (at close)", s["spread"]["record"],
                f"{s['spread']['win_pct']:.1f}%" if s["spread"]["win_pct"] is not None else "—")
    c[1].metric("Totals (at close)", s["total"]["record"],
                f"{s['total']['win_pct']:.1f}%" if s["total"]["win_pct"] is not None else "—")
    profit = s["spread"]["profit"] + s["total"]["profit"]
    c[2].metric("Profit (flat -110)", f"{profit:+.2f}u")
    c[3].metric("Graded picks", s["spread"]["n"] + s["total"]["n"])
    c[4].metric("Pending", s["pending"])
    # CLV vs closing line — the fast signal. Did the line the model locked (market_val_log,
    # converted to the pick's perspective) beat the number it closed at?
    clvs = []
    for _, p in picks[picks["grade"].isin(["won", "lost", "push"])].iterrows():
        if pd.isna(p["closing_line"]) or pd.isna(p["market_val_log"]):
            continue
        if p["pick_type"] == "spread":
            home_t = p["game"].split(" @ ")[1]
            taken = float(p["market_val_log"]) if p["side"] == home_t else -float(p["market_val_log"])
            clvs.append(taken - float(p["closing_line"]))
        else:
            taken = float(p["market_val_log"])
            clvs.append((float(p["closing_line"]) - taken) if p["side"] == "over"
                        else (taken - float(p["closing_line"])))
    if clvs:
        beat = sum(1 for v in clvs if v > 0)
        st.markdown(f"**📏 CLV vs close:** avg **{sum(clvs)/len(clvs):+.2f} pts** · "
                    f"beat the close **{beat/len(clvs)*100:.0f}%** ({beat}/{len(clvs)}) — "
                    f"the fast signal: positive avg + >52% beat-rate = real edge forming, "
                    f"readable weeks before win% is.")
    else:
        st.caption("📏 CLV vs the closing line appears once picks grade — it becomes "
                   "meaningful weeks before the win% above it is.")
    st.caption("Breakeven at -110 is 52.4%. Picks lock the morning an edge first hits 2+ pts "
               "(8 AM brief) at that morning's line — never edited after. "
               "Graded at the **closing** line — the honest number.")

    clv = picks.apply(_pick_clv, axis=1).dropna()
    if len(clv):
        cc = st.columns(2)
        cc[0].metric("📈 Avg CLV", f"{clv.mean():+.2f} pts")
        cc[1].metric("🎯 Beat the close", f"{(clv > 0).mean()*100:.0f}% "
                     f"({int((clv > 0).sum())}/{len(clv)})")
        st.caption("CLV = the line the model took vs where it closed, in the model's favor. "
                   "Positive = the model was ahead of the market. Beating the close >53% over "
                   "100+ picks is the strongest known signal of a real edge — and it becomes "
                   "meaningful in weeks, not seasons.")
    else:
        st.caption("CLV metrics appear once picks are graded — the fast signal: does the model "
                   "beat the closing line?")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("By edge size")
        rows = tracker.edge_buckets(picks)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("If bigger edges don't win more, the signal is noise. This table is the truth serum.")
        else:
            st.info("No graded picks yet.")
    with col2:
        st.subheader("Calibration")
        rows = tracker.calibration(picks)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("When the model says 56%, it should win ~56%.")
        else:
            st.info("No graded picks yet.")

    st.subheader("All picks")
    show = picks.copy()
    show["profit"] = show["profit"].apply(lambda v: f"{float(v):+.2f}" if pd.notna(v) and str(v) != "" else "…")
    show["closing_line"] = show["closing_line"].apply(lambda v: f"{float(v):+.1f}" if pd.notna(v) and str(v) != "" else "…")
    show["clv"] = picks.apply(_pick_clv, axis=1).apply(lambda v: f"{v:+.2f}" if pd.notna(v) else "…")
    show.insert(0, "Logo", show["side"].map(logo_url))
    st.dataframe(show[["Logo", "logged_at", "game", "pick_type", "side", "model_val",
                       "market_val_log", "edge_log", "closing_line", "clv", "grade", "profit"]].iloc[::-1],
                 column_config=LOGO_CFG, hide_index=True, width="stretch")