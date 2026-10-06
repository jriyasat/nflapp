#!/usr/bin/env python
"""
YPP‑only backtest (2021‑2026 REG season) – isolate YPP signal.
Edge = (-ypp_spread) - (-market_spread) where ypp_spread uses only YPP differential.
Threshold 2.0, closing lines (nflverse).
"""
import sys, os, math, json, numpy as np, pandas as pd
os.environ['USE_YPP'] = 'false'
sys.path.insert(0, '.')
import data as dl
from ypp_model import YPPModel

def ypp_only_backtest(threshold=2.0):
    games = dl.load_games()
    g = games[(games["result"].notna()) & (games["season"] >= 2021)
              & (games["game_type"] == "REG")].sort_values(
                  ["season", "week", "gameday"])
    model = YPPModel()
    rows = []
    ypp_diffs = []
    for _, r in g.iterrows():
        if pd.notna(r["spread_line"]):
            market_spread = -float(r["spread_line"])   # home perspective, negative = home favored
            ypp_spread = model.predict_spread(r["away_team"], r["home_team"], r.get("gameday"))
            edge = (-ypp_spread) - (-market_spread)     # + = YPP likes home more than market
            home_cov = r["result"] - market_spread
            pick_home = edge > 0
            pick_won = (pick_home and home_cov > 0) or (not pick_home and home_cov < 0)
            # compute YPP differential for debugging
            away_net, away_n = model.get_team_ypp_stats(r["away_team"], r.get("gameday"))
            home_net, home_n = model.get_team_ypp_stats(r["home_team"], r.get("gameday"))
            ypp_diff = home_net - away_net if away_n > 0 and home_n > 0 else 0.0
            rows.append({
                "season": r["season"], "week": r["week"],
                "away": r["away_team"], "home": r["home_team"],
                "edge": edge, "home_cov": home_cov, "pick_home": pick_home, "pick_won": pick_won,
                "market_spread": market_spread, "ypp_spread": ypp_spread,
                "ypp_diff": ypp_diff, "away_net": away_net, "home_net": home_net,
                "away_n": away_n, "home_n": home_n,
            })
            ypp_diffs.append(ypp_diff)
    df = pd.DataFrame(rows)
    if df.empty:
        print("No games processed.")
        return
    print(f"Games processed: {len(df)}")
    print(f"YPP differential range: [{min(ypp_diffs):.3f}, {max(ypp_diffs):.3f}]")
    print(f"YPP spread range: [{df['ypp_spread'].min():.3f}, {df['ypp_spread'].max():.3f}]")
    # picks at threshold
    sub = df[df["edge"].abs() >= threshold]
    dec = sub[sub["home_cov"] != 0]
    if len(dec) == 0:
        print(f"\nYPP‑only picks (|edge| >= {threshold}): none")
    else:
        wins = dec["pick_won"].sum()
        win_pct = wins / len(dec) * 100
        profit = wins * (100 / 110) - (len(dec) - wins)
        roi = profit / len(dec) * 100
        clv = sub["edge"].mean()
        print(f"\nYPP‑only picks (|edge| >= {threshold}): n={len(dec)}")
        print(f"  win% = {win_pct:.1f}%, ROI = {roi:.1f}%, avg CLV = {clv:.2f} pts")
        # show first few picks
        for _, r in dec.head(10).iterrows():
            print(f"  {r['season']} W{r['week']} {r['away']}@{r['home']}: "
                  f"edge={r['edge']:.2f}, ypp_diff={r['ypp_diff']:.3f}, "
                  f"home_cov={r['home_cov']:.1f}")
    # edge distribution
    print(f"\nEdge distribution:")
    print(f"  min={df['edge'].min():.3f}, max={df['edge'].max():.3f}")
    print(f"  mean={df['edge'].mean():.3f}, std={df['edge'].std():.3f}")
    for th in [0.5, 1.0, 1.5, 2.0]:
        n = (df['edge'].abs() >= th).sum()
        print(f"  |edge| >= {th}: {n} games ({n/len(df)*100:.1f}%)")
    # YPP diff vs week
    if len(df) > 0:
        df['week_num'] = df['week'].astype(int)
        week2plus = df[df['week_num'] >= 2]
        if len(week2plus) > 0:
            print(f"\nYPP diff after week 1: "
                  f"min={week2plus['ypp_diff'].min():.3f}, max={week2plus['ypp_diff'].max():.3f}")
            # show sample of week 2 games with varying diffs
            sample = week2plus.head(5)
            for _, r in sample.iterrows():
                print(f"  {r['season']} W{r['week']} {r['away']}@{r['home']}: "
                      f"ypp_diff={r['ypp_diff']:.3f}, ypp_spread={r['ypp_spread']:.3f}")

if __name__ == "__main__":
    ypp_only_backtest(threshold=2.0)