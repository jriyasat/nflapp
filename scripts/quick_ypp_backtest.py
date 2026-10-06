#!/usr/bin/env python
"""
Quick side‑by‑side backtest with YPP enabled, limited to first 200 games for speed.
"""
import sys, os, json, math
sys.path.insert(0, '/app')
import pandas as pd
import numpy as np
import data as dl
import predictor as pr
from ypp_model import YPPModel

# Config weights
with open('/app/config/model_weights.json') as f:
    cfg = json.load(f)
market_weight = cfg.get('market_weight', 0.85)
nonmarket_weight = 1.0 - market_weight
ypp_weight = cfg.get('ypp_weight', 0.85)
elo_weight = cfg.get('elo_weight', 0.15)
total = ypp_weight + elo_weight
if total > 0:
    ypp_weight /= total
    elo_weight /= total

# Load games, limit to 200 REG games with result
games = dl.load_games()
g = games[(games["result"].notna()) & (games["season"] >= 2021)
          & (games["game_type"] == "REG")].sort_values(["season", "week", "gameday"])
if len(g) > 200:
    g = g.head(200)
    print(f"Limited to {len(g)} games")
else:
    print(f"Using {len(g)} games")

ratings = {}
hist = []
a = b = None
rows = []
for _, r in g.iterrows():
    if a is None:
        a, b = 0.033, 0.0
    ra = ratings.get(r["away_team"], pr.START)
    rh = ratings.get(r["home_team"], pr.START)
    p_home = 1 / (1 + 10 ** (-((rh + pr.HFA) - ra) / 400))
    if pd.notna(r["spread_line"]):
        p_c = min(max(p_home, 0.02), 0.98)
        elo_spread = a * math.log(p_c / (1 - p_c)) + b
        market_spread = -float(r["spread_line"])
        ypp = YPPModel()
        ypp_spread = ypp.predict_spread(r["away_team"], r["home_team"],
                                        date=r.get("gameday"))
        nonmarket_spread = ypp_spread * ypp_weight + elo_spread * elo_weight
        # rest fade
        adj = 0.0
        ar, hr = r.get("away_rest"), r.get("home_rest")
        if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
            adj = -0.5 if hr > ar else 0.5
        adj = max(min(adj, pr.MAX_ADJ), -pr.MAX_ADJ)
        model_spread = market_weight * market_spread + nonmarket_weight * nonmarket_spread - adj
        edge = (-model_spread) - (-market_spread)
        home_cov = r["result"] - market_spread
        pick_home = edge > 0
        pick_won = (pick_home and home_cov > 0) or (not pick_home and home_cov < 0)
        rows.append({
            "edge": edge,
            "pick_home": pick_home,
            "home_cov": home_cov,
            "pick_won": pick_won,
        })
    # update ratings
    home_won = r["result"] > 0
    mov = abs(r["result"])
    elo_diff = (rh + pr.HFA - ra) if home_won else (ra - rh - pr.HFA)
    mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
    shift = pr.K * mult * ((1 if home_won else 0) - p_home)
    ratings[r["home_team"]] = rh + shift
    ratings[r["away_team"]] = ra - shift

df = pd.DataFrame(rows)
print(f"Total games processed: {len(df)}")
for thresh in [1.5, 2.0]:
    sub = df[df["edge"].abs() >= thresh]
    dec = sub[sub["home_cov"] != 0]
    if len(dec) == 0:
        print(f"Threshold {thresh}: n=0, win%=N/A, ROI=N/A, CLV=N/A")
        continue
    wins = dec["pick_won"].sum()
    win_pct = wins / len(dec) * 100
    profit = wins * (100 / 110) - (len(dec) - wins)
    roi = profit / len(dec) * 100
    clv = sub["edge"].mean()
    print(f"Threshold {thresh}: n={len(dec)}, win%={win_pct:.1f}, ROI={roi:.1f}%, avg CLV={clv:.2f} pts")