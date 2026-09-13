"""Value radar v2: every 30 min, scan this week's remaining games for edges the
model would actually bet (|edge| >= VALUE_RADAR_MIN, default 2.0 — the Track
Record threshold), on BOTH spreads and totals.

Re-alerts on real line movement: after a game's first alert, it can fire again
only when that market's line moved >= MOVE_MIN pts with the edge still live —
the message shows the actual move ("DET -7 -> -5.5").

Zero API spend by design: lines come from the shared SGO disk cache (only when
already fresh — never triggers a fetch), then ESPN (free), then nflverse.
Deduped per week via snapshot. Silent otherwise (watchdog pattern).
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
MOVE_MIN = float(os.environ.get("VALUE_RADAR_MOVE", "1.0"))
SNAP = os.path.join(dl.CACHE, "snap_value_radar.json")


def _fmt_line(sp_home, away, home):
    """home-perspective spread -> 'DET -5.5' style."""
    if sp_home is None:
        return "?"
    return f"{home} {sp_home:.1f}" if sp_home < 0 else f"{away} {-sp_home:.1f}"


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
        espn_odds = {}  # ESPN circuit open — SGO/nflverse fallbacks still work
    sgo_abbr = {}
    for (an, hn), books in (dl.cached_sgo_lines() or {}).items():
        k = (dl.TEAM_NAME_TO_ABBR.get(an), dl.TEAM_NAME_TO_ABBR.get(hn))
        if all(k):
            sgo_abbr[k] = books
    try:
        nv, _ = dl.nflverse_injuries(max_age_h=2)
    except Exception:
        nv = {}
    elo = pr.Elo(games)
    snap = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    wk_key = f"{season}-{week}"
    state = snap.get("games", {}) if snap.get("week") == wk_key else {}

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
        pred = pr.predict_game(g, elo, sgo_abbr.get((away, home)),
                               espn_odds.get((away, home)), nv, wind_mph=wind)
        edge = pred.get("edge_pts")
        if edge is None and pred.get("p_market") is not None:
            # ESPN ML-only path: derive the market spread exactly like predictor does
            pc = min(max(pred["p_market"], 0.02), 0.98)
            edge = (elo._a * math.log(pc / (1 - pc)) + elo._b) - pred["model_spread"]
        mk, kt = pred.get("market_spread"), pred.get("market_total")
        mt = pred.get("model_total")
        label = f"{away} @ {home}"
        st = dict(state.get(label, {}))

        # ---- spread ----
        if edge is not None and abs(edge) >= EDGE_MIN:
            first = "sp_edge" not in st
            moved = (st.get("sp_line") is not None and mk is not None
                     and abs(mk - st["sp_line"]) >= MOVE_MIN)
            if first or moved:
                side = home if edge > 0 else away
                if first:
                    msg = (f"• {label}: model likes *{side}* by {abs(edge):.1f} pts "
                           f"(line {_fmt_line(mk, away, home)})")
                else:
                    msg = (f"• 📉 {label}: {_fmt_line(st['sp_line'], away, home)} → "
                           f"*{_fmt_line(mk, away, home)}* — model likes *{side}* by {abs(edge):.1f} pts")
                hits.append((abs(edge), label, msg))
                st["sp_edge"] = round(float(edge), 1)
        if mk is not None:
            st["sp_line"] = round(float(mk), 2)

        # ---- total ----
        t_edge = (float(mt) - float(kt)) if (mt is not None and kt is not None) else None
        if t_edge is not None and abs(t_edge) >= EDGE_MIN:
            first = "tot_edge" not in st
            moved = (st.get("tot_line") is not None and kt is not None
                     and abs(kt - st["tot_line"]) >= MOVE_MIN)
            if first or moved:
                lean = "OVER" if t_edge > 0 else "UNDER"
                if first:
                    msg = f"• {label}: model total leans *{lean}* by {abs(t_edge):.1f} pts (line {kt:.1f})"
                else:
                    msg = (f"• 📉 {label}: total {st['tot_line']:.1f} → *{kt:.1f}* — "
                           f"model leans *{lean}* by {abs(t_edge):.1f} pts")
                hits.append((abs(t_edge), label, msg))
                st["tot_edge"] = round(float(t_edge), 1)
        if kt is not None:
            st["tot_line"] = round(float(kt), 2)

        state[label] = st

    json.dump({"week": wk_key, "games": state}, open(SNAP, "w"))
    if not hits:
        return
    hits.sort(reverse=True)
    full = (f"🚨 *VALUE RADAR — Week {week}*\n" + "\n".join(m for _, _, m in hits)
            + "\n\n_Lines from SGO/ESPN cache — confirm in the app before betting._")
    print(full)
    try:
        from _common import fanout
        fanout("radar", f"🚨 NFL Edge Value Radar — Week {week}", full)
    except Exception:
        pass


if __name__ == "__main__":
    from _common import run
    run(main)
