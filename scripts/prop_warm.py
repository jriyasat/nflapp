"""Warm the player-prop line cache for games kicking off within PROP_WARM_DAYS days
(default 4). Runs via cron: Monday 10am (TNF game) + Saturday 10am (Sun slate + MNF).

Cost: ~4 API credits per game fetched (only games in the window are fetched).
Silent on success (watchdog pattern: empty stdout = nothing sent). Prints only:
  - fetch failures (worth an alert)
  - an all-empty run (books late posting — worth one info line)
Event IDs are week-specific, so week-old props can never leak into a new week.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PYTHONPATH", None)

import pandas as pd
import data as dl

DAYS = int(os.environ.get("PROP_WARM_DAYS", "4"))


def _get_key():
    try:
        import notify
        key = notify._env("ODDS_API_KEY_PROPS") or notify._env("ODDS_API_KEY") or ""
    except Exception:
        key = ""
    if not key:
        try:
            key = open(os.path.join(dl.CACHE, "odds_api_key.txt")).read().strip()
        except Exception:
            pass
    return key


def main():
    key = _get_key()
    if not key:
        print("⚠️ prop warm: no Odds API key found")
        return
    games = dl.load_games()
    season, week = dl.current_season_week(games)
    wk = games[(games["season"] == season) & (games["game_type"] == "REG")
               & (games["week"] == week)]
    now = pd.Timestamp.now()
    horizon = now + pd.Timedelta(days=DAYS)
    due = wk[(pd.to_datetime(wk["gameday"], errors="coerce") <= horizon)
             & wk["result"].isna()]  # skip games already played
    if due.empty:
        return  # nothing kicking off soon — silent
    abbr_to_name = {v: k for k, v in dl.TEAM_NAME_TO_ABBR.items()}
    fetched, empty, failed = [], [], []
    for _, g in due.iterrows():
        away, home = g["away_team"], g["home_team"]
        an, hn = abbr_to_name.get(away, away), abbr_to_name.get(home, home)
        try:
            dl.bust_event_props_cache(an, hn)  # force a fresh fetch on schedule
            props = dl.odds_api_event_props(key, an, hn)
            (fetched if props else empty).append(f"{away}@{home}")
        except Exception as e:
            failed.append(f"{away}@{home}: {type(e).__name__}: {str(e)[:120]}")
    if failed:
        print("⚠️ Prop warm — fetch failures:\n" + "\n".join(failed))
    if not fetched and empty:
        print(f"ℹ️ Prop warm: no props posted yet for {len(empty)} game(s) "
              f"({', '.join(empty[:4])}{'…' if len(empty) > 4 else ''}) — books haven't hung them.")


if __name__ == "__main__":
    main()
    os._exit(0)  # libsql client threads can hang interpreter shutdown
