#!/usr/bin/env python
"""
Debug version of walk‑forward backtest: print first 10 games with spreads and edge.
"""

import os
import sys
import json
import math
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl
import predictor as pr
from ypp_model import YPPModel

# Load configurable weights
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'model_weights.json')
def load_weights():
    try:
        with open(_CONFIG_PATH) as f:
            config = json.load(f)
        market_weight = config.get('market_weight', 0.85)
        nonmarket_weight = 1.0 - market_weight
        ypp_weight = config.get('ypp_weight', 0.85)
        elo_weight = config.get('elo_weight', 0.15)
        if not pr.USE_YPP:
            ypp_weight = 0.0
            elo_weight = 1.0
        total = ypp_weight + elo_weight
        if total > 0:
            ypp_weight /= total
            elo_weight /= total
        return market_weight, nonmarket_weight, ypp_weight, elo_weight
    except Exception:
        return 0.85, 0.15, 0.85, 0.15

MARKET_WEIGHT, NONMARKET_WEIGHT, YPP_WEIGHT, ELO_WEIGHT = load_weights()

MAX_ADJ = pr.MAX_ADJ
REST_FADE_PTS = 0.5
MARGIN_SD = pr.MARGIN_SD

ABBR_TO_LONG = {abbr: long for long, abbr in dl.TEAM_NAME_TO_ABBR.items()}

def debug_walk(games, ypp_model, market_lines_fn, limit=10):
    g = games[(games["result"].notna()) & (games["season"] >= 2015)
              & games["game_type"].isin(["REG", "POST"])].sort_values(
                  ["season", "game_type", "week", "gameday"])
    ratings, last_season = {}, None
    hist = []
    a = b = None
    count = 0
    for _, r in g.iterrows():
        if last_season is not None and r["season"] != last_season:
            ratings = {t: pr.START + (e - pr.START) * (1 - pr.REGRESS)
                       for t, e in ratings.items()}
        last_season = r["season"]
        ra = ratings.get(r["away_team"], pr.START)
        rh = ratings.get(r["home_team"], pr.START)
        p_home = 1 / (1 + 10 ** (-((rh + pr.HFA) - ra) / 400))
        if r["season"] >= 2021 and a is None:
            h = pd.DataFrame(hist, columns=["p", "spread"])
            h["logit"] = h["p"].clip(0.02, 0.98).apply(lambda p: math.log(p / (1 - p)))
            A = np.vstack([h["logit"], np.ones(len(h))]).T
            a, b = np.linalg.lstsq(A, h["spread"], rcond=None)[0]
        if r["season"] >= 2021 and r["game_type"] == "REG":
            p_c = min(max(p_home, 0.02), 0.98)
            elo_spread = a * math.log(p_c / (1 - p_c)) + b
            ypp_spread = ypp_model.predict_spread(r["away_team"], r["home_team"],
                                                  date=r.get("gameday"))
            market_spread, market_src = market_lines_fn(r)
            if market_spread is None:
                if pd.notna(r.get("spread_line")):
                    market_spread = -float(r["spread_line"])
                    market_src = "nflverse"
                else:
                    market_spread = elo_spread
                    market_src = "none"
            # Non‑market blend
            nonmarket_spread = ypp_spread * YPP_WEIGHT + elo_spread * ELO_WEIGHT
            # Rest‑fade
            adj = 0.0
            ar, hr = r.get("away_rest"), r.get("home_rest")
            if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
                adj = -REST_FADE_PTS if hr > ar else REST_FADE_PTS
            adj = max(min(adj, MAX_ADJ), -MAX_ADJ)
            model_spread = MARKET_WEIGHT * market_spread + NONMARKET_WEIGHT * nonmarket_spread - adj
            edge = (-model_spread) - (-market_spread)  # model_margin - market_margin
            home_cov = r["result"] - market_margin
            print(f"Game {r['season']} W{r['week']} {r['away_team']}@{r['home_team']}")
            print(f"  market_spread (home side) = {market_spread:.2f} ({market_src})")
            print(f"  elo_spread = {elo_spread:.2f}")
            print(f"  ypp_spread = {ypp_spread:.2f}")
            print(f"  ypp_diff = {ypp_model.get_team_ypp_stats(r['home_team'], date=r.get('gameday'))[0] - ypp_model.get_team_ypp_stats(r['away_team'], date=r.get('gameday'))[0]:.2f}")
            print(f"  nonmarket_spread = {nonmarket_spread:.2f}")
            print(f"  rest adj = {adj:.2f}")
            print(f"  model_spread = {model_spread:.2f}")
            print(f"  edge = {edge:.2f}")
            print(f"  home_cov = {home_cov:.2f} (result {r['result']})")
            print()
            count += 1
            if count >= limit:
                break
        home_won = r["result"] > 0
        mov = abs(r["result"])
        elo_diff = (rh + pr.HFA - ra) if home_won else (ra - rh - pr.HFA)
        mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
        shift = pr.K * mult * ((1 if home_won else 0) - p_home)
        ratings[r["home_team"]] = rh + shift
        ratings[r["away_team"]] = ra - shift
        if r["season"] < 2021 and pd.notna(r["spread_line"]):
            hist.append((p_home, -r["spread_line"]))

def main():
    games = dl.load_games()
    ypp_model = YPPModel()
    def market_line_fn(game_row):
        books = dl.cached_sgo_lines()
        if books:
            away_long = ABBR_TO_LONG.get(game_row["away_team"].upper())
            home_long = ABBR_TO_LONG.get(game_row["home_team"].upper())
            if away_long and home_long:
                key = (away_long, home_long)
                if key in books:
                    market = pr.consensus(books[key])
                    if market.get("home_spread") is not None:
                        return market["home_spread"], "books"
        if pd.notna(game_row.get("spread_line")):
            return -float(game_row["spread_line"]), "nflverse"
        return None, "none"
    debug_walk(games, ypp_model, market_line_fn, limit=10)

if __name__ == "__main__":
    main()