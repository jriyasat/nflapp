"""Value radar: every 2h, scan this week's remaining games for spread edges the
model would actually bet (|edge| >= VALUE_RADAR_MIN, default 2.0 — the Track
Record threshold). Uses FREE ESPN odds (+ nflverse line fallback) — zero Odds
API credits. Fires once per game per week (deduped weekly snapshot).
Silent otherwise (watchdog pattern: empty stdout = nothing sent).
Run via nfl_value_radar.sh (venv python)."""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PYTHONPATH", None)

import pandas as pd
import data as dl
import predictor as pr

EDGE_MIN = float(os.environ.get("VALUE_RADAR_MIN", "2.0"))
SNAP = os.path.join(dl.CACHE, "snap_value_radar.json")


def main():
    games = dl.load_games()
    season, week = dl.current_season_week(games)
    today = pd.Timestamp.now().normalize()
    wk = games[(games["season"] == season) & (games["game_type"] == "REG")
               & (games["week"] == week) & games["result"].isna()
               & (pd.to_datetime(games["gameday"], errors="coerce") >= today)]
    if wk.empty:
        return
    try:
        espn_odds = dl.espn_week_odds(season, week)
    except Exception:
        espn_odds = {}  # ESPN circuit open — nflverse line fallback still works
    try:
        nv, _ = dl.nflverse_injuries(max_age_h=2)
    except Exception:
        nv = {}
    elo = pr.Elo(games)
    snap = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    wk_key = f"{season}-{week}"
    alerted = snap.get("alerts", {}) if snap.get("week") == wk_key else {}

    hits = []
    for _, g in wk.iterrows():
        away, home = g["away_team"], g["home_team"]
        wind = None
        try:
            if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
                import weather as wx
                wind, _ = wx.wind_for_game(g)
        except Exception:
            pass
        pred = pr.predict_game(g, elo, None, espn_odds.get((away, home)), nv, wind_mph=wind)
        edge = pred.get("edge_pts")
        if edge is None and pred.get("p_market") is not None:
            # ESPN ML-only path: predictor sets no edge_pts without a posted spread —
            # derive the market spread exactly like predictor does (de-vig -> Elo map)
            pc = min(max(pred["p_market"], 0.02), 0.98)
            edge = (elo._a * math.log(pc / (1 - pc)) + elo._b) - pred["model_spread"]
        label = f"{away} @ {home}"
        if edge is None or abs(edge) < EDGE_MIN or label in alerted:
            continue
        side = home if edge > 0 else away
        hits.append((abs(edge), label,
                     f"• {label}: model likes *{side}* by {abs(edge):.1f} pts vs market"))
        alerted[label] = round(float(edge), 1)

    json.dump({"week": wk_key, "alerts": alerted}, open(SNAP, "w"))
    if not hits:
        return
    hits.sort(reverse=True)
    print(f"🚨 *VALUE RADAR — Week {week}*\n" + "\n".join(m for _, _, m in hits)
          + "\n\n_Free scan (ESPN/nflverse lines) — confirm in the app before betting._")


if __name__ == "__main__":
    from _common import run
    run(main)
