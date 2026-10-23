"""
Pick'em page view.
"""
import streamlit as st
import pandas as pd
import db
from shared import logo_url, pick_logo

def _kickoff_passed(g):
    """Pick lock for this game: 5 minutes before kickoff (mirrors db.PICK_LOCK)."""
    try:
        if pd.isna(g["gameday"]):
            return False
        gt = str(g.get("gametime", "13:00"))
        hh, mm = int(gt.split(":")[0]), int(gt.split(":")[1])
        return (pd.Timestamp.now()
                > g["gameday"] + pd.Timedelta(hours=hh, minutes=mm) - pd.Timedelta(minutes=5))
    except Exception:
        return False

    """Pick lock for this game: 5 minutes before kickoff (mirrors db.PICK_LOCK)."""
    try:
        if pd.isna(g["gameday"]):
            return False
        gt = str(g.get("gametime", "13:00"))
        hh, mm = int(gt.split(":")[0]), int(gt.split(":")[1])
        return (pd.Timestamp.now()
                > g["gameday"] + pd.Timedelta(hours=hh, minutes=mm) - pd.Timedelta(minutes=5))
    except Exception:
        return False


def pickem_page(ctx):
    st.header("🏆 Weekly Pick'em")
    st.caption("Up to **5 games** against the spread, every week. **Change picks freely until "
               "5 minutes before each kickoff** — then they lock. Tap a logo to pick, tap it "
               "again to remove. Your line is whatever's current at the moment you make "
               "(or change) a pick.")

    # 🤖 model picks — public immediately (transparency over gamesmanship; tailing is fine)
    st.subheader(f"🤖 Model picks — Week {ctx.week}")
    model_picks = db.load_pickem("model", ctx.season, ctx.week)
    if model_picks.empty:
        st.info("Model's picks drop with the Monday 8 AM brief — it plays its top-5 edge games, "
                "at the lines posted when it enters.")
    else:
        GRADE_ICON = {"won": "✅ won", "lost": "❌ lost", "push": "➖ push", "pending": "⏳ pending"}
        show = pd.DataFrame({
            "Game": model_picks["game"],
            "Pick": model_picks["pick"].map(logo_url),  # logo IS the pick
            "Line": model_picks["line"].apply(lambda v: f"{float(v):+g}" if pd.notna(v) else "-"),
            "Result": model_picks["grade"].map(lambda g: GRADE_ICON.get(g, g)),
        })
        st.dataframe(show,
                     column_config={"Pick": st.column_config.ImageColumn("Pick", width="small")},
                     hide_index=True, width="stretch")
        made_raw = model_picks["created_at"].dropna().max()
        if made_raw:
            ts = pd.Timestamp(made_raw)
            made = (f"{ts:%a} {ts:%b} {ts.day}, "
                    f"{ts.hour % 12 or 12}:{ts:%M} {'AM' if ts.hour < 12 else 'PM'}")
            st.caption(f"🕐 Picks made **{made}** — locked at the lines posted at that moment.")
        mrec = next((r for r in db.pickem_leaderboard(ctx.season) if r["user"] == "model"), None)
        if mrec:
            st.markdown(f"**Model pick'em record:** {mrec['record']} "
                        f"({mrec['win_pct']*100:.0f}%)")
        st.caption("⚠️ **PLEASE NOTE:** The model is **required to pick 5 games every week** in "
                   "pick'em — those are the rules of the game, same as you. On the 📈 **Track "
                   "Record** page it plays by its own discipline: it only logs picks where its "
                   "edge vs the market is **2+ points**, graded at the closing line. Pick'em "
                   "record = the model playing your game. Track Record = the model's real bets.")
    for w in range(1, ctx.week + 1):
        db.grade_pickem(ctx.games, ctx.season, w)

    mine = db.load_pickem(ctx.USER, ctx.season, ctx.week)
    picked = dict(zip(mine["game"], mine["pick"])) if not mine.empty else {}
    line_by_game = dict(zip(mine["game"], mine["line"])) if not mine.empty else {}
    grade_by_game = dict(zip(mine["game"], mine["grade"])) if not mine.empty else {}

    st.markdown("""<style>
.stElementContainer:has(.sticky-picks) { position: sticky; top: 2.9rem; z-index: 999;
  background: rgba(14,17,23,0.97); border-bottom: 1px solid #2a2f3a; }
.sticky-picks { padding: 0.45rem 0 0.35rem; font-size: 1.3rem; font-weight: 700; }
</style>""", unsafe_allow_html=True)
    st.markdown(f"<div class='sticky-picks'>🏆 Week {ctx.week} — your picks "
                f"(<span style='color:#7cffb2'>{len(picked)}/5</span>)</div>",
                unsafe_allow_html=True)
    model_side = (dict(zip(model_picks["game"], model_picks["pick"]))
                  if not model_picks.empty else {})
    GRADE_MARK = {"won": "✅", "lost": "❌", "push": "➖"}
    for _, g in ctx.week_games.iterrows():
        away, home = g["away_team"], g["home_team"]
        label = f"{away} @ {home}"
        mside = model_side.get(label)
        sp = g["spread_line"]
        locked = _kickoff_passed(g)
        my = picked.get(label)
        grade = grade_by_game.get(label)
        gicon = GRADE_MARK.get(grade) if my and grade != "pending" else None
        day = g["gameday"].strftime("%a %b %d") if pd.notna(g["gameday"]) else ""
        ca, cm, ch = st.columns([2, 1, 2])
        ca.markdown(pick_logo(away, my == away, gicon if my == away else None,
                              model=mside == away), unsafe_allow_html=True)
        ch.markdown(pick_logo(home, my == home, gicon if my == home else None,
                              model=mside == home), unsafe_allow_html=True)
        if pd.notna(sp):
            fav = sp if sp < 0 else -sp  # favorite's line, always negative
            lt = "PK" if sp == 0 else f"{fav:+.1f}"
        else:
            lt = "—"
        cm.markdown(f"<div style='text-align:center;padding-top:14px'>"
                    f"<span style='font-size:24px;font-weight:700'>{lt}</span><br>"
                    f"<span style='color:#888'>@</span><br>"
                    f"<small style='color:#888'>{day} {g.get('gametime', '')} ET"
                    f"{' 🔒' if locked else ''}</small></div>", unsafe_allow_html=True)
        if not locked and pd.notna(sp):
            full = len(picked) >= 5 and label not in picked
            if ca.button(f"{away}", key=f"pk_a_{label}",
                         type="primary" if my == away else "secondary",
                         use_container_width=True):
                if my == away:
                    db.delete_pickem(ctx.USER, ctx.season, ctx.week, label)
                    st.rerun()
                elif full:
                    st.warning("You're at 5/5 — tap one of your glowing picks to remove it first.")
                else:
                    db.save_pickem(ctx.USER, ctx.season, ctx.week, label, away, float(sp))
                    st.rerun()
            if ch.button(f"{home}", key=f"pk_h_{label}",
                         type="primary" if my == home else "secondary",
                         use_container_width=True):
                if my == home:
                    db.delete_pickem(ctx.USER, ctx.season, ctx.week, label)
                    st.rerun()
                elif full:
                    st.warning("You're at 5/5 — tap one of your glowing picks to remove it first.")
                else:
                    db.save_pickem(ctx.USER, ctx.season, ctx.week, label, home, float(-sp))
                    st.rerun()

    st.subheader("🏆 Leaderboard")
    lb = db.pickem_leaderboard(ctx.season)
    if lb:
        st.dataframe(pd.DataFrame([{"Player": r["user"], "Record": r["record"],
                                    "Win %": f"{r['win_pct']*100:.0f}%"} for r in lb]),
                     hide_index=True, width="stretch")
    else:
        st.info("No graded picks yet this season — standings appear after Week 1.")

    wk_all = db.load_pickem_week(ctx.season, ctx.week)
    if not wk_all.empty:
        locked_games = {f"{g['away_team']} @ {g['home_team']}"
                        for _, g in ctx.week_games.iterrows() if _kickoff_passed(g)}
        vis = wk_all[wk_all["game"].isin(locked_games)]
        if not vis.empty:
            st.subheader("Everyone's picks (locked games)")
            vis = vis.rename(columns={"user": "Player", "game": "Game", "pick": "Pick",
                                      "line": "Line", "grade": "Result"})
            vis["Pick"] = vis["Pick"].map(logo_url)  # logo IS the pick
            st.dataframe(vis, column_config={"Pick": st.column_config.ImageColumn("Pick", width="small")},
                         hide_index=True, width="stretch")