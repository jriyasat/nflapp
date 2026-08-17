"""Elo baseline backtest vs closing lines, 2021-2025."""
import sys

sys.path.insert(0, "/Users/jeff/nfl-edge")
import math

import pandas as pd

import data as dl

K = 20.0
HFA = 48.0          # elo points of home-field advantage
REGRESS = 1/3       # offseason regression to 1500
START = 1500.0

df = dl.load_games()
g = df[(df["result"].notna()) & (df["game_type"].isin(["REG", "POST"]))].copy()
g = g.sort_values(["season", "game_type", "week", "gameday"])

ratings = {}
probs, results, rows = [], [], []
last_season = None
for _, r in g.iterrows():
    if last_season is not None and r["season"] != last_season:
        ratings = {t: START + (e - START) * (1 - REGRESS) for t, e in ratings.items()}
    last_season = r["season"]
    ra = ratings.get(r["away_team"], START)
    rh = ratings.get(r["home_team"], START)
    p_home = 1 / (1 + 10 ** (-((rh + HFA) - ra) / 400))
    home_won = r["result"] > 0
    # margin-of-victory multiplier (538-style, damped for blowouts by favorite)
    mov = abs(r["result"])
    elo_diff = (rh + HFA - ra) if home_won else (ra - rh - HFA)
    mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
    shift = K * mult * ((1 if home_won else 0) - p_home)
    ratings[r["home_team"]] = rh + shift
    ratings[r["away_team"]] = ra - shift
    if r["season"] >= 2021:
        probs.append(p_home)
        results.append(1 if home_won else 0)
        rows.append({
            "season": r["season"], "p_home": p_home, "home_won": home_won,
            "spread_line": r["spread_line"], "home_cover_margin": r["home_cover_margin"],
            "home_team": r["home_team"], "away_team": r["away_team"],
        })

bt = pd.DataFrame(rows)
bt = bt[bt["spread_line"].notna()]
brier = ((bt["p_home"] - bt["home_won"]) ** 2).mean()
acc = ((bt["p_home"] > 0.5) == (bt["home_won"] == 1)).mean()
print(f"Elo 2021-25: Brier={brier:.4f}  win-pick accuracy={acc*100:.1f}%  n={len(bt)}")

# elo prob -> implied home spread: fit logit(p) -> -spread_line_away... home spread = -spread_line
bt["home_spread_mkt"] = -bt["spread_line"]  # home perspective, neg = home favored
bt["logit"] = bt["p_home"].apply(lambda p: math.log(p / (1 - p)))
# linear fit: home_spread ~ a * logit + b
import numpy as np

A = np.vstack([bt["logit"], np.ones(len(bt))]).T
a, b = np.linalg.lstsq(A, bt["home_spread_mkt"], rcond=None)[0]
print(f"spread map: home_spread = {a:.2f} * logit(p) + {b:.2f}")
bt["elo_spread"] = a * bt["logit"] + b
bt["edge"] = bt["elo_spread"] - bt["home_spread_mkt"]  # + means elo likes home more than market

print("\nElo-vs-market edge -> ATS record (taking Elo's side):")
for th in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
    sub = bt[bt["edge"].abs() >= th].copy()
    sub = sub[sub["home_cover_margin"] != 0]
    if len(sub) < 30:
        continue
    # take home if edge>0 else away; win if that side covered
    won = ((sub["edge"] > 0) & (sub["home_cover_margin"] > 0)) | ((sub["edge"] < 0) & (sub["home_cover_margin"] < 0))
    print(f"  |edge| >= {th}: n={len(sub):4d}  ATS {won.mean()*100:.1f}%")

# calibration by prob bucket
bt["bucket"] = pd.cut(bt["p_home"], [0, .35, .45, .55, .65, 1.0])
cal = bt.groupby("bucket", observed=True).agg(n=("home_won", "size"), actual=("home_won", "mean"), pred=("p_home", "mean"))
print("\nCalibration:"); print(cal.round(3).to_string())
