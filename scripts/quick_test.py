import sys
sys.path.insert(0, '/app')
import data as dl
import predictor as pr
from ypp_model import YPPModel
import pandas as pd
import numpy as np
import math

def quick_test(limit_games=50, threshold=2.0):
    games = dl.load_games()
    # REG season only, with result
    g = games[(games["result"].notna()) & (games["season"] >= 2015)
              & games["game_type"].isin(["REG", "POST"])].sort_values(
                  ["season", "game_type", "week", "gameday"])
    ratings, last_season = {}, None
    hist = []
    a = b = None
    rows = []
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
            ypp_model = YPPModel()
            ypp_spread = ypp_model.predict_spread(r["away_team"], r["home_team"],
                                                  date=r.get("gameday"))
            market_spread = -float(r["spread_line"]) if pd.notna(r.get("spread_line")) else elo_spread
            # Load config weights
            import json
            with open('/app/config/model_weights.json') as f:
                config = json.load(f)
            market_weight = config.get('market_weight', 0.85)
            nonmarket_weight = 1.0 - market_weight
            ypp_weight = config.get('ypp_weight', 0.85)
            elo_weight = config.get('elo_weight', 0.15)
            total = ypp_weight + elo_weight
            if total > 0:
                ypp_weight /= total
                elo_weight /= total
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
                "season": r["season"],
                "week": r["week"],
                "away": r["away_team"],
                "home": r["home_team"],
                "edge": edge,
                "pick_home": pick_home,
                "home_cov": home_cov,
                "pick_won": pick_won,
                "market_spread": market_spread,
                "model_spread": model_spread,
            })
            count += 1
            if count >= limit_games:
                break
        # update ratings
        home_won = r["result"] > 0
        mov = abs(r["result"])
        elo_diff = (rh + pr.HFA - ra) if home_won else (ra - rh - pr.HFA)
        mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
        shift = pr.K * mult * ((1 if home_won else 0) - p_home)
        ratings[r["home_team"]] = rh + shift
        ratings[r["away_team"]] = ra - shift
        if r["season"] < 2021 and pd.notna(r["spread_line"]):
            hist.append((p_home, -r["spread_line"]))
    df = pd.DataFrame(rows)
    if df.empty:
        print("No games processed.")
        return
    print(f"Processed {len(df)} games")
    picks = df[df['edge'].abs() >= threshold]
    print(f"Picks (|edge| >= {threshold}): {len(picks)}")
    if len(picks) > 0:
        win_pct = picks['pick_won'].mean() * 100
        print(f"Win %: {win_pct:.1f}%")
        for _, row in picks.iterrows():
            print(f"  {row['season']} W{row['week']} {row['away']}@{row['home']} edge={row['edge']:.2f} {'HOME' if row['pick_home'] else 'AWAY'} {'WIN' if row['pick_won'] else 'LOSS'} (home_cov={row['home_cov']:.1f})")

if __name__ == "__main__":
    quick_test(limit_games=100, threshold=1.5)