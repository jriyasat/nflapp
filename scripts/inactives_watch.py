"""Gameday inactives watchdog. Runs every 15 min on game days; prints a digest
only when a game kicks off within the next ~100 minutes AND its inactives
(newly posted ~90 min before kickoff) haven't been reported yet.
Empty stdout = silent. Run via inactives_watch.sh."""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PYTHONPATH", None)

import pandas as pd

import data as dl
import db

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
SNAP = os.path.join(dl.CACHE, "snap_inactives.json")
WINDOW_MIN = 100


def main():
    games = dl.load_games()
    today = pd.Timestamp.now().normalize()
    now = pd.Timestamp.now()
    gd = pd.to_datetime(games["gameday"], errors="coerce").dt.normalize()
    todays = games[(games["result"].isna()) & (gd == today)]
    if todays.empty:
        return

    soon = []
    for _, g in todays.iterrows():
        gt = str(g.get("gametime", ""))
        try:
            hh = int(gt.split(":")[0])
            mm = int(gt.split(":")[1]) if ":" in gt else 0
            kickoff = today + pd.Timedelta(hours=hh, minutes=mm)
            if pd.Timedelta(minutes=-20) <= kickoff - now <= pd.Timedelta(minutes=WINDOW_MIN):
                soon.append((g, kickoff))
        except Exception:
            continue
    if not soon:
        return

    sb = dl._get_json(dl.ESPN_SCOREBOARD + f"?dates={today.strftime('%Y%m%d')}&limit=50",
                      f"espn_sb_{today.strftime('%Y%m%d')}.json", 15)
    ev_map = {}
    for e in sb.get("events", []):
        try:
            comps = e["competitions"][0]["competitors"]
            home = next(c for c in comps if c["homeAway"] == "home")["team"]["abbreviation"]
            away = next(c for c in comps if c["homeAway"] == "away")["team"]["abbreviation"]
            ev_map[(away, home)] = e["id"]
        except Exception:
            continue

    snap = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    new_snap = dict(snap)
    sections = []
    for g, kickoff in soon:
        label = f"{g['away_team']} @ {g['home_team']}"
        eid = ev_map.get((g["away_team"], g["home_team"]))
        if not eid:
            continue
        try:
            summ = dl._get_json(ESPN_SUMMARY + f"?event={eid}", f"espn_sum_{eid}.json", 15)
        except Exception:
            continue
        inact = []
        for block in summ.get("injuries", []):
            tabbr = block.get("team", {}).get("abbreviation", "?")
            for inj in block.get("injuries", []):
                if str(inj.get("status", "")).lower() in ("out", "inactive"):
                    pos = inj.get("position", {})
                    pos = pos.get("abbreviation", "") if isinstance(pos, dict) else str(pos or "")
                    inact.append((tabbr, inj.get("athlete", {}).get("displayName", "?"), pos))
        if not inact:
            continue
        sig = "|".join(sorted(f"{t}:{n}" for t, n, _ in inact))
        if snap.get(label) == sig:
            continue
        new_snap[label] = sig
        lines = [f"• {t}: {n} ({p}) OUT" for t, n, p in inact]
        sections.append(f"🚫 *{label}* (kickoff {kickoff.strftime('%-I:%M %p')})\n" + "\n".join(lines))

    json.dump(new_snap, open(SNAP, "w"))
    if not sections:
        return

    full = (f"🏈 *Gameday Inactives* — {now.strftime('%a %b %d, %-I:%M %p')}\n\n"
            + "\n\n".join(sections)
            + "\n\n_Props on OUT players are dead — check the Props tab for who absorbs the volume._")
    sys.stdout.write(full + "\n")
    sys.stdout.flush()

    try:
        import notify
        for u in db.list_users():
            try:
                if u.get("email_enabled") and u.get("email"):
                    notify.send_email(u["email"], f"NFL Edge Inactives — {now.strftime('%a %b %d')}", full)
                if u.get("telegram_enabled") and u.get("telegram_chat_id"):
                    notify.send_telegram(u["telegram_chat_id"], full)
            except Exception:
                continue
    except Exception:
        pass


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
