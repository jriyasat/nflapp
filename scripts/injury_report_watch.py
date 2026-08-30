"""Injury report watch: Wed-Fri afternoons, every 30 min. Prints a digest when
new Out/Doubtful/Questionable designations appear or escalate on the official
report (drops ~Wed 4pm ET, updates through Friday). Silent otherwise."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PYTHONPATH", None)

import data as dl
import db

SNAP = os.path.join(dl.CACHE, "snap_inj_report.json")
SEV = {"Out": 3, "Doubtful": 2, "Questionable": 1}


def main():
    games = dl.load_games()
    season, week = dl.current_season_week(games)
    try:
        nv, _ = dl.nflverse_injuries(season)
    except Exception:
        return
    cur = {}
    for team, blk in nv.items():
        for p in blk.get("rows", []):
            st = p.get("status")
            if st in SEV:
                cur[f"{p['name']} ({team})"] = st
    old = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    if cur == old:
        return
    changes = []
    for who, st in sorted(cur.items()):
        prev = old.get(who)
        if prev is None:
            changes.append(f"• {who}: **{st}** (new)")
        elif SEV[st] > SEV.get(prev, 0):
            changes.append(f"• {who}: {prev} → **{st}** ⬆️")
    improved = [f"• {who}: was {st}, now off report ✅" for who, st in old.items() if who not in cur]
    json.dump(cur, open(SNAP, "w"))
    if not changes and not improved:
        return
    wk_games = games[(games.season == season) & (games.week == week) & (games.game_type == "REG")]
    first = wk_games.iloc[0]["gameday"] if not wk_games.empty else None
    kickoff = first.strftime("%a %b %d") if first is not None else ""
    lines = [f"🏥 *INJURY REPORT UPDATE — Week {week}* (kicks off {kickoff})", ""]
    lines += changes[:12] + improved[:6]
    full = "\n".join(lines)
    print(full)
    try:
        import notify
        subject = f"🏥 NFL Edge — Injury report update (Week {week})"
        gmail_user = notify._env("GMAIL_USER")
        if gmail_user:
            notify.send_email(gmail_user, subject, full)
        for u in db.list_users():
            if u.get("email_enabled") and u.get("email"):
                notify.send_email(u["email"], subject, full)
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
