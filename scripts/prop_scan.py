"""Thursday Top Prop Edges scan: loads live prop lines for the week's top-edge
games (capped to protect the free Odds API quota), finds the biggest
projection-vs-line gaps, emails the best ones. Thursdays 6pm ET."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PYTHONPATH", None)

import pandas as pd
import data as dl
import db
import predictor as pr
import props_model as pm
import notify

GAMES_TO_SCAN = 6      # ~4 credits/game = 24/week — free-tier safe
TOP_N = 5
MIN_EDGE_PCT = 8.0
PROJ_LABEL = {"proj_pass": "Pass Yds", "proj_rush": "Rush Yds",
              "proj_rec_yds": "Rec Yds", "proj_rec": "Receptions"}


def main():
    games = dl.load_games()
    season, week = dl.current_season_week(games)
    wk = games[(games["season"] == season) & (games["week"] == week)
               & (games["game_type"] == "REG")]
    if wk.empty:
        return
    key = notify._env("ODDS_API_KEY") or ""
    try:
        key = key or open(os.path.join(dl.CACHE, "odds_api_key.txt")).read().strip()
    except Exception:
        pass
    if not key:
        print("⚠️ prop scan: no Odds API key")
        return

    elo = pr.Elo(games)
    # rank games by model-vs-market spread disagreement → scan where the model talks loudest
    ranked = []
    for _, g in wk.iterrows():
        pred = pr.predict_game(g, elo)
        gap = abs(pred["edge_pts"]) if pred.get("edge_pts") is not None else 0
        ranked.append((gap, g))
    ranked.sort(key=lambda x: -x[0])

    ps = dl.load_player_stats()
    defs = pm.defense_multipliers(ps)
    hits, scanned = [], 0
    abbr_to_name = {v: k for k, v in dl.TEAM_NAME_TO_ABBR.items()}
    for _, g in ranked[:GAMES_TO_SCAN]:
        away, home = g["away_team"], g["home_team"]
        label = f"{away} @ {home}"
        try:
            lines = dl.odds_api_event_props(key, abbr_to_name.get(away, away),
                                            abbr_to_name.get(home, home)) or {}
        except Exception:
            lines = {}
        scanned += 1
        if not lines:
            continue
        for team, opp in ((away, home), (home, away)):
            res = pm.project_game(ps, defs, team, opp, per_pos=2)
            for p in pm.edges_vs_lines(res["players"], lines):
                for col, e in p.get("edges", {}).items():
                    if abs(e["edge_pct"]) >= MIN_EDGE_PCT:
                        hits.append((abs(e["edge_pct"]),
                                     f"• {label}: **{p['player']} {e['lean']} {e['line']} "
                                     f"{PROJ_LABEL.get(col, col)}** (proj {p[col]:.0f}, "
                                     f"edge {e['edge_pct']:+.0f}%)"))
    if not hits:
        return  # no live props posted yet (normal early in the week) — stay silent
    hits.sort(reverse=True)
    first = wk.iloc[0]["gameday"]
    kickoff = first.strftime("%a %b %d") if pd.notna(first) else ""
    full = (f"🎰 *TOP PROP EDGES — Week {week}* (kicks off {kickoff})\n"
            f"scanned {scanned} games, threshold {MIN_EDGE_PCT:.0f}%\n\n"
            + "\n".join(m for _, m in hits[:TOP_N])
            + "\n\n_App: https://nfledge.streamlit.app → Props tab for the full board_")
    print(full)
    subject = f"🎰 NFL Edge — Top prop edges (Week {week})"
    gmail_user = notify._env("GMAIL_USER")
    if gmail_user:
        notify.send_email(gmail_user, subject, full)
    for u in db.list_users():
        if u.get("email_enabled") and u.get("email"):
            notify.send_email(u["email"], subject, full)
    os._exit(0)


if __name__ == "__main__":
    main()
