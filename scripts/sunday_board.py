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

    # injuries — per-team summary for teams playing this week
    try:
        nv, _ = dl.nflverse_injuries(season)
    except Exception:
        nv = {}
    DESIG = ("Out", "Doubtful", "Questionable")
    teams_wk = sorted(set(wk["away_team"]) | set(wk["home_team"]))
    # key players = the ones our props model projects (betting-relevant)
    key_names = {}
    try:
        import props_model as pm
        ps = dl.load_player_stats()
        defs = pm.defense_multipliers(ps)
        opp_of = {}
        for _, g in wk.iterrows():
            opp_of[g["away_team"]] = g["home_team"]
            opp_of[g["home_team"]] = g["away_team"]
        for t in teams_wk:
            try:
                res = pm.project_game(ps, defs, t, opp_of.get(t, t), per_pos=2)
                key_names[t] = {p["player"] for p in res["players"]}
            except Exception:
                key_names[t] = set()
    except Exception:
        key_names = {t: set() for t in teams_wk}

    sev_rank = {"Out": 0, "Doubtful": 1, "Questionable": 2}
    sev_short = {"Out": "Out", "Doubtful": "D", "Questionable": "Q"}
    inj_lines = []
    for t in teams_wk:
        prows = [p for p in nv.get(t, {}).get("rows", []) if p.get("status") in DESIG]
        if not prows:
            continue
        prows.sort(key=lambda p: sev_rank.get(p["status"], 3))
        keys = [p for p in prows if p["name"] in key_names.get(t, set())][:2]
        for p in prows:  # fill to 2 with most severe if needed
            if len(keys) >= 2:
                break
            if p not in keys:
                keys.append(p)
        key_txt = ", ".join(f"{p['name']} ({sev_short.get(p['status'], p['status'])}"
                            f"{' — ' + p['detail'] if p.get('detail') else ''})" for p in keys)
        inj_lines.append(f"• **{t}** ({len(prows)} designated): {key_txt}")
    if inj_lines:
        inj_sec = "🏥 *INJURY WATCH — by team (count = Out/D/Q designated)*\n" + "\n".join(inj_lines)
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
