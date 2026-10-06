#!/usr/bin/env python
"""
Quick side‑by‑side comparison of YPP‑enabled backtest at thresholds 1.5 and 2.0.
Uses nflverse closing lines (same as backtest_model.py) for consistency.
"""
import sys, os, math, json
sys.path.insert(0, '.')
import pandas as pd
import data as dl
import predictor as pr
from ypp_model import YPPModel

def run_backtest(threshold=2.0):
    games = dl.load_games()
    reg = games[(games["result"].notna()) & (games["season"] >= 2021)
                & (games["game_type"] == "REG")].sort_values(
                    ["season", "week", "gameday"])
    ratings = {}
    hist = []
    a = b = None
    picks = []
    for _, r in reg.iterrows():
        if a is None and r["season"] < 2021:
            # fit logistic->spread mapping using pre‑2021 games
            pre = games[(games["result"].notna()) & (games["season"] < 2021)
                       & pd.notna(games["spread_line"])]
            if len(pre) > 0:
                pre_p = 1 / (1 + 10 ** (-((pre["home_elo"] + pr.HFA) - pre["away_elo"]) / 400))
                pre_spread = -pre["spread_line"]
                pre_p_c = pre_p.clip(0.02, 0.98)
                logit = np.log(pre_p_c / (1 - pre_p_c))
                A = np.vstack([logit, np.ones(len(logit))]).T
                a, b = np.linalg.lstsq(A, pre_spread, rcond=None)[0]
    # quick hack: use known constants from predictor
    a, b = 0.033, 0.0
    for _, r in reg.iterrows():
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
            # Load config weights
            with open('config/model_weights.json') as f:
                cfg = json.load(f)
            market_weight = cfg.get('market_weight', 0.85)
            nonmarket_weight = 1.0 - market_weight
            ypp_weight = cfg.get('ypp_weight', 0.85)
            elo_weight = cfg.get('elo_weight', 0.15)
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
            home_cov = r["result"] - r["spread_line"]
            pick_home = edge > 0
            pick_won = (pick_home and home_cov > 0) or (not pick_home and home_cov < 0)
            if abs(edge) >= threshold:
                picks.append({
                    "season": r["season"],
                    "week": r["week"],
                    "away": r["away_team"],
                    "home": r["home_team"],
                    "edge": edge,
                    "pick_home": pick_home,
                    "home_cov": home_cov,
                    "pick_won": pick_won,
                    "market_spread": market_spread,
                })
        # update ratings
        home_won = r["result"] > 0
        mov = abs(r["result"])
        elo_diff = (rh + pr.HFA - ra) if home_won else (ra - rh - pr.HFA)
        mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
        shift = pr.K * mult * ((1 if home_won else 0) - p_home)
        ratings[r["home_team"]] = rh + shift
        ratings[r["away_team"]] = ra - shift
    df = pd.DataFrame(picks)
    n = len(df)
    win = df["pick_won"].sum() if n > 0 else 0
    win_pct = (win / n * 100) if n > 0 else 0
    roi = (win - (n - win)) * 100 / n if n > 0 else 0  # -110 odds
    clv = df["edge"].mean() if n > 0 else 0
    return n, win_pct, roi, clv

if __name__ == "__main__":
    import numpy as np
    for thresh in [1.5, 2.0]:
        n, win_pct, roi, clv = run_backtest(thresh)
        print(f"Threshold {thresh}: n={n}, win%={win_pct:.1f}, ROI={roi:.1f}%, avg CLV={clv:.2f} pts")