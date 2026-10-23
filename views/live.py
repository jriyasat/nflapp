"""
Live page view.
"""
import streamlit as st
import pandas as pd
import data as dl
import journal
import db
from shared import logo_img, matchup_md, _ABBR_TO_NAME

def _live_score_map(season, week):
    """{(away, home): live event} — ESPN first, SGO when ESPN is WAF-banned."""
    try:
        evs = dl.espn_live_scores(season, week)
        if evs:
            return {(ev["away"], ev["home"]): ev for ev in evs}
    except Exception:
        pass
    try:
        key = dl.sgo_api_key()
        if key:
            return {(ev["away"], ev["home"]): ev for ev in dl.sgo_live_scores(key)}
    except Exception:
        pass
    return {}

def _live_body(season, week, user):
    live = list(_live_score_map(season, week).values())  # ESPN first, SGO fallback when WAF-banned
    if not live:
        st.info("Live scores unavailable right now (ESPN may be rate-limiting). Try again shortly.")
        return
    bets = journal.load_bets(user)
    pending = bets[bets["status"] == "pending"] if not bets.empty else bets
    wk_picks = db.load_pickem_week(season, week)
    any_live = False
    for ev in live:
        state = ev["state"]
        if state == "in":
            any_live = True
            badge = f"🟢 LIVE Q{ev['period']} {ev['clock']}"
        elif state == "post":
            badge = "✅ Final"
        else:
            badge = f"⏰ {ev['detail'] or 'upcoming'}"
        if state != "pre":
            score_line = (f"**{ev['a_score']}** {logo_img(ev['away'], 22)} {_ABBR_TO_NAME.get(ev['away'], ev['away'])}"
                          f" @ **{ev['h_score']}** {logo_img(ev['home'], 22)} {_ABBR_TO_NAME.get(ev['home'], ev['home'])}")
            st.markdown(f"{score_line} — {badge}", unsafe_allow_html=True)
        else:
            st.markdown(f"{matchup_md(ev['away'], ev['home'], 22)} — {badge}",
                        unsafe_allow_html=True)
        margin = ev["h_score"] - ev["a_score"]
        notes = []
        if not pending.empty:
            for _, b in pending[pending["game"] == ev["label"]].iterrows():
                sel, line = str(b["selection"]), float(b["line"] or 0)
                if state == "pre":
                    notes.append(f"🎟️ your bet: {sel} {line:+g}")
                else:
                    tm = margin if sel == ev["home"] else -margin
                    if b["bet_type"] in ("over", "under"):
                        tot = ev["a_score"] + ev["h_score"]
                        diff = tot - line if b["bet_type"] == "over" else line - tot
                    else:
                        diff = tm + line
                    status = f"✅ by {diff:.0f}" if diff > 0 else (f"❌ by {-diff:.0f}" if diff < 0 else "➖ push")
                    notes.append(f"🎟️ {sel} {line:+g} {b['bet_type']}: {status}")
        if not wk_picks.empty:
            for _, pk in wk_picks[wk_picks["game"] == ev["label"]].iterrows():
                if state != "pre":
                    tm = margin if pk["pick"] == ev["home"] else -margin
                    diff = tm + (pk["line"] or 0)
                    status = "✅" if diff > 0 else ("❌" if diff < 0 else "➖")
                    notes.append(f"🏆 {pk['user']}: {pk['pick']} {pk['line']:+g} {status}")
                else:
                    notes.append(f"🏆 {pk['user']}: {pk['pick']} {pk['line']:+g}")
        if notes:
            st.caption("  •  ".join(notes))
    if not any_live and all(ev["state"] == "pre" for ev in live):
        st.caption("No games in progress — this page lights up at kickoff. Auto-refreshes every 60s.")

def live_page(ctx):
    st.header(f"🔴 Live — Week {ctx.week}")
    if hasattr(st, "fragment"):
        @st.fragment(run_every=60)
        def _frag():
            _live_body(ctx.season, ctx.week, ctx.USER)
        _frag()
    else:
        _live_body(ctx.season, ctx.week, ctx.USER)
        if st.button("🔄 Refresh"):
            st.rerun()