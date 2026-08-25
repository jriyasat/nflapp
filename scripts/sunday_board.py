"""Sunday State of the Board — a guaranteed weekly digest (not a watchdog).
Runs Sundays 9 AM ET during the season (silent in the offseason when no week
of games is upcoming). Email-only delivery: Jeff always, plus users opted into
email briefs. Telegram stays quiet unless the script errors."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PYTHONPATH", None)

from datetime import datetime

import pandas as pd
import data as dl
import db
import weather as wx
import tracker
import notify


def fmt_line(g):
    sp, tot = g["spread_line"], g["total_line"]
    s = f"{g['away_team']} {sp:+.1f} @ {g['home_team']} {-sp:+.1f}" if pd.notna(sp) else f"{g['away_team']} @ {g['home_team']} (no line)"
    if pd.notna(tot):
        s += f"  •  O/U {tot:.1f}"
    return s


def main():
    games = dl.load_games()
    season, week = dl.current_season_week(games)
    wk = games[(games["season"] == season) & (games["game_type"] == "REG")
               & (games["week"] == week)].sort_values(["gameday", "gametime"])
    if wk.empty:
        return  # offseason: no board to report

    first = wk.iloc[0]["gameday"]
    kickoff = first.strftime("%a %b %d") if pd.notna(first) else ""
    today = datetime.now().strftime("%a %b %d")

    # lines
    lines_sec = "📉 *THE BOARD*\n" + "\n".join(f"• {fmt_line(g)}" for _, g in wk.iterrows())

    # model picks logged so far this week
    picks = tracker.load_picks()
    wk_picks = picks[(picks["season"] == season) & (picks["week"] == week)] if not picks.empty else picks
    if not wk_picks.empty:
        pl = [f"• {r['game']}: {r['side']} ({r['pick_type']}, gap {abs(r['edge_log']):.1f})"
              for _, r in wk_picks.iterrows()]
        picks_sec = "🎯 *MODEL PICKS LOGGED (so far)*\n" + "\n".join(pl)
    else:
        picks_sec = "🎯 *MODEL PICKS*\n• None over the 2-pt threshold yet this week."

    # season record (once graded games exist)
    s = tracker.summary(picks)
    n_graded = s["spread"]["n"] + s["total"]["n"]
    record_sec = (f"📈 *MODEL SEASON RECORD* — sides {s['spread']['record']}, "
                  f"totals {s['total']['record']}, {s['pending']} pending"
                  if n_graded else "📈 *MODEL SEASON RECORD* — starts grading Week 1.")

    # injuries
    try:
        nv, _ = dl.nflverse_injuries(season)
    except Exception:
        nv = {}
    out_d = [(p["name"], t, p.get("status", "")) for t, blk in nv.items()
             for p in blk.get("rows", []) if p.get("status") in ("Out", "Doubtful")]
    q = sum(1 for blk in nv.values() for p in blk.get("rows", [])
            if p.get("status") == "Questionable")
    if out_d or q:
        names = ", ".join(f"{n} ({t}, {st})" for n, t, st in out_d[:6]) or "none Out/Doubtful"
        inj_sec = f"🏥 *INJURY WATCH* — {len(out_d)} Out/Doubtful, {q} Questionable\n• {names}"
    else:
        inj_sec = "🏥 *INJURY WATCH* — no official designations yet (first report drops game week)."

    # wind
    wind_lines = []
    for _, g in wk.iterrows():
        label = f"{g['away_team']} @ {g['home_team']}"
        w, flag = wx.wind_for_game(g)
        if w is not None and w >= 10:
            tag = "🔴 UNDER angle" if flag == "under" else "breezy"
            wind_lines.append(f"• {label}: {w:.0f} mph {tag}")
    wind_sec = ("🌬️ *WIND WATCH*\n" + "\n".join(wind_lines)) if wind_lines else \
        "🌬️ *WIND WATCH* — no games ≥10 mph."

    header = f"🏈 *NFL Edge — Sunday State of the Board* — {today}\nWeek {week} kicks off {kickoff}\n"
    body = "\n\n".join([lines_sec, picks_sec, record_sec, inj_sec, wind_sec])
    footer = "\n\n_App: https://nfledge.streamlit.app — 🏆 Pick'em locks at kickoff._"
    full = header + body + footer
    subject = f"🏈 NFL Edge — Sunday State of the Board (Week {week})"

    # ---- email delivery: jeff always + opted-in users ----
    gmail_user = notify._env("GMAIL_USER")
    sent = []
    if gmail_user:
        if notify.send_email(gmail_user, subject, full):
            sent.append("jeff")
    for u in db.list_users():
        if u["username"] == "jeff":
            continue
        if u.get("email_enabled") and u.get("email"):
            # personalized pick'em nudge
            mine = db.load_pickem(u["username"], season, week)
            n = len(mine)
            nudge = (f"\n\n🏆 Your Pick'em: {n}/5 picks in — "
                     + ("you're set. ✅" if n >= 5 else "get yours in before kickoff!"))
            if notify.send_email(u["email"], subject, full + nudge):
                sent.append(u["username"])

    # stdout only as a status breadcrumb (keeps telegram quiet on success)
    if not sent:
        print("⚠️ Sunday Board: no email delivered (check GMAIL_USER/GMAIL_APP_PASSWORD secrets)")
    os._exit(0)


if __name__ == "__main__":
    main()
