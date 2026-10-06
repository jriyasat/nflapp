#!/usr/bin/env python
"""
Detailed report for sides/totals walk‑forward backtest.
"""
import sys, os, json, math, pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the same modules used by walk_forward_sides_no_ypp.py
import data as dl
import predictor as pr
from ypp_model import YPPModel
from scripts.walk_forward_sides_no_ypp import evaluate_config, load_weights, ABBR_TO_LONG

def market_line_fn(game_row):
    """Market line function (same as original)."""
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

def run_detailed_backtest(threshold=2.0):
    """Run backtest and return detailed stats."""
    games = dl.load_games()
    ypp_model = YPPModel()
    market_weight, nonmarket_weight, ypp_weight, elo_weight = load_weights()
    
    result = evaluate_config(games, ypp_model, market_line_fn,
                             market_weight, nonmarket_weight, ypp_weight, elo_weight,
                             threshold=threshold)
    
    df = result.get("full_df")
    if df is None:
        print("No full_df available")
        return result
    
    # Edge distribution
    print("\n=== EDGE DISTRIBUTION ===")
    edge_bins = [-10, -5, -2, -1, -0.5, 0, 0.5, 1, 2, 5, 10]
    df["edge_bin"] = pd.cut(df["edge"], edge_bins)
    bin_counts = df.groupby("edge_bin").size()
    for bin_label, count in bin_counts.items():
        print(f"{bin_label}: {count} games")
    
    # Picks by season
    print("\n=== PICKS BY SEASON (|edge| >= threshold) ===")
    picks_df = df[df["edge"].abs() >= threshold].copy()
    if not picks_df.empty:
        picks_df["pick_won"] = np.where(picks_df["pick_home"], picks_df["home_cov"] > 0, picks_df["home_cov"] < 0)
        picks_df["push"] = picks_df["home_cov"] == 0
        picks_df = picks_df[~picks_df["push"]]
        by_season = picks_df.groupby("season").agg(
            n_picks=("edge", "size"),
            wins=("pick_won", "sum"),
            avg_edge=("edge", "mean")
        ).reset_index()
        by_season["win_pct"] = by_season["wins"] / by_season["n_picks"] * 100
        for _, row in by_season.iterrows():
            print(f"{row['season']}: {row['n_picks']} picks, {row['wins']} wins ({row['win_pct']:.1f}%), avg edge {row['avg_edge']:.2f}")
    
    # Market source breakdown
    print("\n=== MARKET SOURCE BREAKDOWN ===")
    src_counts = df["market_src"].value_counts()
    for src, count in src_counts.items():
        print(f"{src}: {count} games")
    
    # Edge vs CLV correlation
    print("\n=== EDGE vs ACTUAL MARGIN ===")
    if len(df) > 0:
        corr = df["edge"].corr(df["actual_margin"] - df["market_margin"])
        print(f"Correlation (edge vs actual margin - market margin): {corr:.3f}")
    
    # Return the same result dict
    return result

if __name__ == "__main__":
    # Load current config weights
    market_weight, nonmarket_weight, ypp_weight, elo_weight = load_weights()
    print(f"=== SIDES/TOTALS DETAILED BACKTEST REPORT ===")
    print(f"Weights: market={market_weight:.2f}, non‑market={nonmarket_weight:.2f}, ypp={ypp_weight:.2f}, elo={elo_weight:.2f}")
    print(f"Threshold: 2.0")
    
    result = run_detailed_backtest(threshold=2.0)
    
    print("\n=== SUMMARY ===")
    print(f"Games evaluated: {result['n_games']}")
    print(f"Picks (|edge| ≥ 2.0): {result['n_picks']}")
    if result['n_picks']:
        print(f"Win %: {result['win_pct']:.1f}%")
        print(f"ROI (%): {result['roi']:.1f}%")
        print(f"Avg CLV (edge): {result['clv']:.2f} pts")
    else:
        print("No picks at threshold.")