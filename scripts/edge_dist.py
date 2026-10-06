import sys
sys.path.insert(0, '/app')
import data as dl
import predictor as pr
from ypp_model import YPPModel
import pandas as pd
import numpy as np
import math

games = dl.load_games()
g = games[(games["result"].notna()) & (games["season"] >= 2021) & (games["game_type"] == "REG")].sort_values(["season", "week"])
ratings = {}
hist = []
a = b = None
rows = []
for _, r in g.iterrows():
    ra = ratings.get(r["away_team"], pr.START)
    rh = ratings.get(r["home_team"], pr.START)
    p_home = 1 / (1 + 10 ** (-((rh + pr.HFA) - ra) / 400))
    if a is None:
        # fit logistic->spread mapping using pre‑2021 games
        pre = games[(games["result"].notna()) & (games["season"] < 2021) & pd.notna(games["spread_line"])]
        if len(pre) > 0:
            pass  # skip for now
        a, b = 0.033, 0.0  # rough placeholder
    if pd.notna(r["spread_line"]):
        p_c = min(max(p_home, 0.02), 0.98)
        elo_spread = a * math.log(p_c / (1 - p_c)) + b
        market_spread = -float(r["spread_line"])
        ypp = YPPModel()
        ypp_spread = ypp.predict_spread(r["away_team"], r["home_team"], date=r.get("gameday"))
        # blend
        market_weight = 0.85
        nonmarket_weight = 0.15
        ypp_weight = 0.85
        elo_weight = 0.15
        total = ypp_weight + elo_weight
        if total > 0:
            ypp_weight /= total
            elo_weight /= total
        nonmarket_spread = ypp_spread * ypp_weight + elo_spread * elo_weight
        adj = 0.0
        model_spread = market_weight * market_spread + nonmarket_weight * nonmarket_spread - adj
        edge = (-model_spread) - (-market_spread)
        rows.append({
            "edge": edge,
            "market_spread": market_spread,
            "ypp_spread": ypp_spread,
            "elo_spread": elo_spread,
            "model_spread": model_spread,
        })
    home_won = r["result"] > 0
    mov = abs(r["result"])
    elo_diff = (rh + pr.HFA - ra) if home_won else (ra - rh - pr.HFA)
    mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
    shift = pr.K * mult * ((1 if home_won else 0) - p_home)
    ratings[r["home_team"]] = rh + shift
    ratings[r["away_team"]] = ra - shift

df = pd.DataFrame(rows)
if len(df) > 0:
    print(f"Edges computed: {len(df)}")
    print(f"Edge min: {df['edge'].min():.3f}, max: {df['edge'].max():.3f}")
    print(f"Edge mean: {df['edge'].mean():.3f}, std: {df['edge'].std():.3f}")
    for thresh in [0.5, 1.0, 1.5, 2.0]:
        n = (df['edge'].abs() >= thresh).sum()
        print(f"Edge ≥ {thresh}: {n} games ({n/len(df)*100:.1f}%)")
    # show outliers beyond 2.0
    outliers = df[df['edge'].abs() >= 2.0]
    if len(outliers) > 0:
        print("\nOutliers (edge ≥ 2.0):")
        for _, row in outliers.iterrows():
            print(f"  edge={row['edge']:.3f}, market={row['market_spread']:.1f}, ypp={row['ypp_spread']:.1f}, elo={row['elo_spread']:.1f}")
else:
    print("No rows computed")