#!/usr/bin/env python
"""
Full backtest across 2021‑2026 for market weights 0.7, 0.85, 0.9 (YPP disabled).
"""
import sys, os, math, json, numpy as np, pandas as pd
os.environ['USE_YPP'] = 'false'
sys.path.insert(0, '.')
import data as dl
import predictor as pr

K, HFA, REGRESS, START = pr.K, pr.HFA, pr.REGRESS, pr.START

def backtest_weight(market_weight):
    games = dl.load_games()
    g = games[(games["result"].notna()) & (games["season"] >= 2015)
              & games["game_type"].isin(["REG", "POST"])].sort_values(
                  ["season", "game_type", "week", "gameday"])
    ratings, last_season = {}, None
    hist = []
    a = b = None
    rows = []
    for _, r in g.iterrows():
        if last_season is not None and r["season"] != last_season:
            ratings = {t: START + (e - START) * (1 - REGRESS) for t, e in ratings.items()}
        last_season = r["season"]
        ra = ratings.get(r["away_team"], START)
        rh = ratings.get(r["home_team"], START)
        p_home = 1 / (1 + 10 ** (-((rh + HFA) - ra) / 400))
        if r["season"] >= 2021 and a is None:
            h = pd.DataFrame(hist, columns=["p", "spread"])
            h["logit"] = h["p"].clip(0.02, 0.98).apply(lambda p: math.log(p / (1 - p)))
            A = np.vstack([h["logit"], np.ones(len(h))]).T
            a, b = np.linalg.lstsq(A, h["spread"], rcond=None)[0]
        if r["season"] >= 2021 and r["game_type"] == "REG" and pd.notna(r["spread_line"]):
            p_c = min(max(p_home, 0.02), 0.98)
            elo_spread = a * math.log(p_c / (1 - p_c)) + b
            market_spread = -float(r["spread_line"])
            nonmarket_weight = 1.0 - market_weight
            # YPP disabled, non‑market portion is Elo only
            nonmarket_spread = elo_spread
            adj = 0.0
            ar, hr = r.get("away_rest"), r.get("home_rest")
            if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
                adj = -0.5 if hr > ar else 0.5
            adj = max(min(adj, pr.MAX_ADJ), -pr.MAX_ADJ)
            model_spread = market_weight * market_spread + nonmarket_weight * nonmarket_spread - adj
            model_margin = -model_spread
            market_margin = -market_spread
            edge = model_margin - market_margin
            home_cov = r["result"] - market_spread
            rows.append({
                "edge": edge,
                "home_cov": home_cov,
                "market_spread": market_spread,
                "model_margin": model_margin,
                "market_margin": market_margin,
            })
        home_won = r["result"] > 0
        mov = abs(r["result"])
        elo_diff = (rh + HFA - ra) if home_won else (ra - rh - HFA)
        mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
        shift = K * mult * ((1 if home_won else 0) - p_home)
        ratings[r["home_team"]] = rh + shift
        ratings[r["away_team"]] = ra - shift
        if r["season"] < 2021 and pd.notna(r["spread_line"]):
            hist.append((p_home, -r["spread_line"]))
    df = pd.DataFrame(rows)
    if df.empty:
        return {"picks": 0, "win_pct": 0.0, "roi": 0.0, "clv": 0.0, "n_games": 0,
                "edge_min": 0, "edge_max": 0, "edge_mean": 0, "edge_std": 0}
    thresh = 2.0
    sub = df[df["edge"].abs() >= thresh]
    dec = sub[sub["home_cov"] != 0]
    if len(dec) == 0:
        return {"picks": 0, "win_pct": 0.0, "roi": 0.0, "clv": 0.0, "n_games": len(df),
                "edge_min": df["edge"].min(), "edge_max": df["edge"].max(),
                "edge_mean": df["edge"].mean(), "edge_std": df["edge"].std()}
    wins = ((dec["edge"] > 0) & (dec["home_cov"] > 0)) | ((dec["edge"] < 0) & (dec["home_cov"] < 0))
    win_pct = wins.sum() / len(dec) * 100
    profit = wins.sum() * (100 / 110) - (len(dec) - wins.sum())
    roi = profit / len(dec) * 100
    clv = sub["edge"].mean()
    return {
        "picks": len(dec),
        "win_pct": win_pct,
        "roi": roi,
        "clv": clv,
        "n_games": len(df),
        "edge_min": df["edge"].min(),
        "edge_max": df["edge"].max(),
        "edge_mean": df["edge"].mean(),
        "edge_std": df["edge"].std(),
    }

if __name__ == "__main__":
    print("Full backtest 2021‑2026 (YPP disabled, threshold 2.0)")
    print("=" * 70)
    for mkt in [0.7, 0.85, 0.9]:
        print(f"\nMarket weight = {mkt:.2f}")
        res = backtest_weight(mkt)
        print(f"  Games evaluated: {res['n_games']}")
        print(f"  Edge range: [{res['edge_min']:.3f}, {res['edge_max']:.3f}]")
        print(f"  Edge mean: {res['edge_mean']:.3f}, std: {res['edge_std']:.3f}")
        print(f"  Picks (|edge| >= 2.0): {res['picks']}")
        if res['picks'] > 0:
            print(f"  Win%: {res['win_pct']:.1f}%")
            print(f"  ROI: {res['roi']:.1f}%")
            print(f"  Avg CLV: {res['clv']:.2f} pts")
        else:
            print("  No picks")
    print("\n" + "=" * 70)