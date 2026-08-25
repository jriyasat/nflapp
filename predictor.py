"""Market-blend predictor.

Philosophy (validated by backtests on 2021-2025 closing lines):
- The de-vigged market consensus is the base prediction. Pure Elo vs closing
  line goes ~51% ATS (below -110 breakeven), so we never fade the market raw.
- Elo is the prior/fallback when no market is posted.
- Small, backtest-validated adjustments on top. Angle badges show their real
  historical record next to every lean.
"""

import math

import numpy as np
import pandas as pd

K, HFA, REGRESS, START = 20.0, 48.0, 1 / 3, 1500.0
MARGIN_SD = 13.3          # historical SD of NFL margin vs expectation
TOTAL_SD = 13.5           # SD of game total vs expectation
MAX_ADJ = 2.5             # cap on total adjustment, points
MAX_TOTAL_ADJ = 3.5

# Totals adjustments (validated, scripts/backtest_totals.py 2021-25)
REF_ADJ = {"Shawn Hochuli": -1.0, "Ron Torbert": -0.5, "Shawn Smith": -0.5}

# --- validated angle records (scripts/backtest_spots.py, 2021-2025, n>=30) ---
ANGLES = {
    "big_home_fav": {"record": "62.5% ATS (n=112)", "note": "Home favorite of 7+"},
    "rest_fade": {"record": "rested side 47.0% ATS (n=285)", "note": "Market overprices rest edges of 3+ days"},
    "wind_under": {"record": "unders 60.9% (n=87)", "note": "Outdoor games, wind 15+ mph"},
}

QB_STATUS_PTS = {"Out": -5.5, "Doubtful": -4.0, "Questionable": -1.0}
OTHER_OUT_PTS = -0.4


class Elo:
    """538-style Elo with MOV multiplier + offseason regression; spread map fit on data."""

    def __init__(self, games):
        # ratings verified identical trained on 1999+ vs 2015+ (regression washes
        # out old seasons) — 2015+ is 3x faster
        g = games[(games["result"].notna()) & (games["season"] >= 2015)
                  & games["game_type"].isin(["REG", "POST"])]
        g = g.sort_values(["season", "game_type", "week", "gameday"])
        self.ratings = {}
        hist, last_season = [], None
        for _, r in g.iterrows():
            if last_season is not None and r["season"] != last_season:
                self.ratings = {t: START + (e - START) * (1 - REGRESS)
                                for t, e in self.ratings.items()}
            last_season = r["season"]
            ra = self.ratings.get(r["away_team"], START)
            rh = self.ratings.get(r["home_team"], START)
            p_home = self._p(ra, rh)
            home_won = r["result"] > 0
            mov = abs(r["result"])
            elo_diff = (rh + HFA - ra) if home_won else (ra - rh - HFA)
            mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
            shift = K * mult * ((1 if home_won else 0) - p_home)
            self.ratings[r["home_team"]] = rh + shift
            self.ratings[r["away_team"]] = ra - shift
            if r["season"] >= 2021 and pd.notna(r["spread_line"]):
                hist.append((p_home, -r["spread_line"]))  # home-perspective spread
        h = pd.DataFrame(hist, columns=["p", "spread"])
        h["logit"] = h["p"].clip(0.02, 0.98).apply(lambda p: math.log(p / (1 - p)))
        A = np.vstack([h["logit"], np.ones(len(h))]).T
        self._a, self._b = np.linalg.lstsq(A, h["spread"], rcond=None)[0]

    @staticmethod
    def _p(ra, rh):
        return 1 / (1 + 10 ** (-((rh + HFA) - ra) / 400))

    def predict(self, away, home):
        p = self._p(self.ratings.get(away, START), self.ratings.get(home, START))
        p_c = min(max(p, 0.02), 0.98)
        spread = self._a * math.log(p_c / (1 - p_c)) + self._b  # home perspective, neg = home fav
        return p, spread


def american_to_prob(odds):
    if odds is None:
        return None
    odds = float(odds)
    return (100 / (odds + 100)) if odds > 0 else (-odds / (-odds + 100))


def devig(p_home_raw, p_away_raw):
    s = p_home_raw + p_away_raw
    return p_home_raw / s if s else None


def consensus(books):
    """Median de-vigged probability + median spread/total across books."""
    probs, spreads, totals = [], [], []
    for e in (books or {}).values():
        ph, pa = american_to_prob(e.get("home_ml")), american_to_prob(e.get("away_ml"))
        if ph and pa:
            probs.append(devig(ph, pa))
        if e.get("home_spread") is not None:
            spreads.append(e["home_spread"])
        if e.get("total") is not None:
            totals.append(e["total"])
    out = {"n_books": len(probs)}
    if probs:
        out["p_home"] = float(np.median(probs))
    if spreads:
        out["home_spread"] = float(np.median(spreads))
    if totals:
        out["total"] = float(np.median(totals))
    return out


def injury_adjustment(team_injury_rows):
    """Points adjustment from official report (negative = team hurt). Heuristic."""
    pts = 0.0
    for r in team_injury_rows or []:
        st, pos = r.get("status", ""), r.get("position", "")
        if pos == "QB" and st in QB_STATUS_PTS:
            pts += QB_STATUS_PTS[st]
        elif st == "Out":
            pts += OTHER_OUT_PTS
    return max(pts, -7.0)


def predict_game(game_row, elo, books=None, espn=None, injuries=None, wind_mph=None):
    """Full market-blend prediction for one game."""
    away, home = game_row["away_team"], game_row["home_team"]
    p_elo, elo_spread = elo.predict(away, home)

    market = consensus(books)
    if not market.get("n_books") and espn:
        ph, pa = american_to_prob(espn.get("home_ml")), american_to_prob(espn.get("away_ml"))
        if ph and pa:
            market = {"p_home": devig(ph, pa), "n_books": 1}
        if espn.get("over_under"):
            market["total"] = espn["over_under"]

    # fallback: nflverse carries current lines for upcoming games (spread_line is away-perspective)
    if market.get("p_home") is None and pd.notna(game_row.get("spread_line")):
        sp_home = -float(game_row["spread_line"])
        logit = (sp_home - elo._b) / elo._a
        market = {"p_home": 1 / (1 + math.exp(-logit)), "home_spread": sp_home, "n_books": 0}
        if pd.notna(game_row.get("total_line")):
            market["total"] = float(game_row["total_line"])

    # adjustments, all on the MARGIN axis: positive = toward HOME (negative favors away).
    # injury_adjustment() returns negative pts for the hurt team.
    adjs, total_adj = [], 0.0
    inj = injuries or {}
    for team in (home, away):
        entry = inj.get(team)
        rows = entry.get("rows") if isinstance(entry, dict) else entry
        pts = injury_adjustment(rows)
        if pts:
            toward_home = pts if team == home else -pts
            adjs.append({"module": "injury", "team": team, "pts": toward_home})
            total_adj += toward_home

    ar, hr = game_row.get("away_rest"), game_row.get("home_rest")
    if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
        rested = home if hr > ar else away
        fade = -0.5 if rested == home else 0.5   # fade the rested side (validated 47% ATS)
        adjs.append({"module": "rest_fade", "team": rested, "pts": fade})
        total_adj += fade

    total_adj = max(min(total_adj, MAX_ADJ), -MAX_ADJ)

    mode = "market-blend" if market.get("p_home") is not None else "elo-only"
    if mode == "market-blend":
        base_spread = market.get("home_spread")
        if base_spread is None:
            # derive spread from de-vigged prob via elo-fitted map
            pc = min(max(market["p_home"], 0.02), 0.98)
            base_spread = elo._a * math.log(pc / (1 - pc)) + elo._b
        # blend: 85% market + 15% elo, then adjustments.
        # NOTE: total_adj is on the MARGIN axis (positive = toward home) while
        # model_spread is on the spread axis (negative = home favored) -> SUBTRACT.
        model_spread = 0.85 * base_spread + 0.15 * elo_spread - total_adj
        p_market = market["p_home"]
    else:
        model_spread = elo_spread - total_adj
        p_market = None

    # model spread -> cover prob for each side (margin ~ Normal(-spread, SD))
    model_margin = -model_spread  # positive = home wins by X
    out = {
        "mode": mode, "adjustments": adjs,
        "p_elo": p_elo, "elo_spread": elo_spread,
        "p_market": p_market, "n_books": market.get("n_books", 0),
        "market_spread": market.get("home_spread"), "market_total": market.get("total"),
        "model_spread": model_spread, "model_margin": model_margin,
        "angles": [],
    }
    if market.get("home_spread") is not None:
        z = (model_margin - (-market["home_spread"])) / MARGIN_SD
        p_home_cover = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        out["p_home_cover"] = p_home_cover
        out["edge_pts"] = model_margin - (-market["home_spread"])
        for side, p in (("home", p_home_cover), ("away", 1 - p_home_cover)):
            ev = p * (100 / 110) - (1 - p)
            b = 100 / 110
            kelly = max((b * p - (1 - p)) / b, 0) / 4  # quarter kelly
            out[f"ev_{side}"] = ev
            out[f"kelly_{side}"] = kelly
        if market["home_spread"] <= -7:
            out["angles"].append(("big_home_fav", ANGLES["big_home_fav"]))

    # ---- totals model: market total + validated adjustments ----
    if market.get("total") is not None:
        t_list, t_adj = [], 0.0
        if wind_mph is not None:
            if wind_mph >= 15:
                t_list.append(("wind 15+ mph", -2.7)); t_adj += -2.7
            elif wind_mph >= 10:
                t_list.append(("wind 10-14 mph", -1.2)); t_adj += -1.2
        sp = market.get("home_spread")
        if sp is not None:
            if abs(sp) <= 3:
                t_list.append(("close spread (<=3)", -1.3)); t_adj += -1.3
            elif abs(sp) >= 7:
                t_list.append(("blowout setup (7+)", 0.8)); t_adj += 0.8
        if game_row.get("game_type") == "REG" and pd.notna(game_row.get("week")) and int(game_row["week"]) <= 4:
            t_list.append(("early season (W1-4)", -1.0)); t_adj += -1.0
        ref = game_row.get("referee")
        if isinstance(ref, str) and ref in REF_ADJ:
            t_list.append((f"ref: {ref}", REF_ADJ[ref])); t_adj += REF_ADJ[ref]
        t_adj = max(min(t_adj, MAX_TOTAL_ADJ), -MAX_TOTAL_ADJ)
        model_total = market["total"] + t_adj
        z = (model_total - market["total"]) / TOTAL_SD
        p_over = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        out["model_total"] = model_total
        out["total_adjustments"] = t_list
        out["p_over"] = p_over
        for side, p in (("over", p_over), ("under", 1 - p_over)):
            ev = p * (100 / 110) - (1 - p)
            b = 100 / 110
            out[f"ev_{side}"] = ev
            out[f"kelly_{side}"] = max((b * p - (1 - p)) / b, 0) / 4
    return out
