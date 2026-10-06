#!/usr/bin/env python
"""
YPP‑only backtest limited to first 200 games for speed.
"""
import sys, os, math, json, numpy as np, pandas as pd
os.environ['USE_YPP'] = 'false'
sys.path.insert(0, '.')
import data as dl
from ypp_model import YPPModel

games = dl.load_games()
g = games[(games["result"].notna()) & (games["season"] >= 2021)
          & (games["game_type"] == "REG")].sort_values(
              ["season", "week", "gameday"])
g = g.head(200)
print(f"Limited to {len(g)} games")
model = YPPModel()
rows = []
ypp_diffs = []
for _, r in g.iterrows():
    if pd.notna(r["spread_line"]):
        market_spread = -float(r["spread_line"])
        ypp_spread = model.predict_spread(r["away_team"], r["home_team"], r.get("gameday"))
        edge = (-ypp_spread) - (-market_spread)
        home_cov = r["result"] - market_spread
        pick_home = edge > 0
        pick_won = (pick_home and home_cov > 0) or (not pick_home and home_cov < 0)
        away_net, away_n = model.get_team_ypp_stats(r["away_team"], r.get("gameday"))
        home_net, home_n = model.get_team_ypp_stats(r["home_team"], r.get("gameday"))
        ypp_diff = home_net - away_net if away_n > 0 and home_n > 0 else 0.0
        rows.append({
            "edge": edge, "home_cov": home_cov, "pick_won": pick_won,
            "ypp_spread": ypp_spread, "ypp_diff": ypp_diff,
            "away_net": away_net, "home_net": home_net,
            "away_n": away_n, "home_n": home_n,
        })
        ypp_diffs.append(ypp_diff)
df = pd.DataFrame(rows)
if df.empty:
    print("No games processed.")
    sys.exit(0)
print(f"Games processed: {len(df)}")
print(f"YPP differential range: [{min(ypp_diffs):.3f}, {max(ypp_diffs):.3f}]")
print(f"YPP spread range: [{df['ypp_spread'].min():.3f}, {df['ypp_spread'].max():.3f}]")
threshold = 2.0
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
    for _, r in dec.iterrows():
        print(f"    edge={r['edge']:.2f}, ypp_diff={r['ypp_diff']:.3f}, home_cov={r['home_cov']:.1f}")
print(f"\nEdge distribution:")
print(f"  min={df['edge'].min():.3f}, max={df['edge'].max():.3f}")
print(f"  mean={df['edge'].mean():.3f}, std={df['edge'].std():.3f}")
for th in [0.5, 1.0, 1.5, 2.0]:
    n = (df['edge'].abs() >= th).sum()
    print(f"  |edge| >= {th}: {n} games ({n/len(df)*100:.1f}%)")
# check week 2 onward
if 'week' in g.columns:
    week2 = g[g['week'].astype(int) >= 2]
    if len(week2) > 0:
        print("\nWeek 2+ games sample:")
        for _, r in week2.head(5).iterrows():
            away_net, away_n = model.get_team_ypp_stats(r["away_team"], r.get("gameday"))
            home_net, home_n = model.get_team_ypp_stats(r["home_team"], r.get("gameday"))
            ypp_diff = home_net - away_net if away_n > 0 and home_n > 0 else 0.0
            print(f"  {r['season']} W{r['week']} {r['away_team']}@{r['home_team']}: "
                  f"away_net={away_net:.3f} (n={away_n}), home_net={home_net:.3f} (n={home_n}), "
                  f"ypp_diff={ypp_diff:.3f}")