"""End-to-end walk-forward backtest of the full market-blend model, 2021-2025.

Honesty rules:
- Elo is POINT-IN-TIME: ratings updated only with games BEFORE the predicted one.
- The Elo->spread map (a, b) is fit on 2015-2020 only; 2021+ is out-of-sample.
- Market = nflverse closing line (spread_line is AWAY-perspective).
- Adjustments included: rest fade only (known pre-game from schedule).
  NOT included (no historical data): injuries, weather, referee — so this
  backtests the market+Elo+rest core, not the full live feature set.
- REG season only (matches what the tracker logs).

Graded vs the CLOSING line, pushes excluded from win%, ROI at -110.
"""

import math
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/jeff/nfl-edge")
import data as dl
import predictor as pr

K, HFA, REGRESS, START = pr.K, pr.HFA, pr.REGRESS, pr.START
MARGIN_SD = pr.MARGIN_SD


def walk_forward(games):
    """Yield (game_row, p_home_elo, elo_spread) with point-in-time ratings."""
    g = games[(games["result"].notna()) & (games["season"] >= 2015)
              & games["game_type"].isin(["REG", "POST"])].sort_values(
                  ["season", "game_type", "week", "gameday"])
    ratings, last_season = {}, None
    hist = []  # (p_prior, home spread) for map fitting, pre-2021 only
    a = b = None
    for _, r in g.iterrows():
        if last_season is not None and r["season"] != last_season:
            ratings = {t: START + (e - START) * (1 - REGRESS) for t, e in ratings.items()}
        last_season = r["season"]
        ra = ratings.get(r["away_team"], START)
        rh = ratings.get(r["home_team"], START)
        p_home = 1 / (1 + 10 ** (-((rh + HFA) - ra) / 400))
        if r["season"] >= 2021 and a is None:
            # fit spread map on 2015-2020 once 2021 begins
            h = pd.DataFrame(hist, columns=["p", "spread"])
            h["logit"] = h["p"].clip(0.02, 0.98).apply(lambda p: math.log(p / (1 - p)))
            A = np.vstack([h["logit"], np.ones(len(h))]).T
            a, b = np.linalg.lstsq(A, h["spread"], rcond=None)[0]
        if r["season"] >= 2021 and r["game_type"] == "REG" and pd.notna(r["spread_line"]):
            p_c = min(max(p_home, 0.02), 0.98)
            elo_spread = a * math.log(p_c / (1 - p_c)) + b
            yield r, p_home, elo_spread
        # now update ratings with this game's result
        home_won = r["result"] > 0
        mov = abs(r["result"])
        elo_diff = (rh + HFA - ra) if home_won else (ra - rh - HFA)
        mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
        shift = K * mult * ((1 if home_won else 0) - p_home)
        ratings[r["home_team"]] = rh + shift
        ratings[r["away_team"]] = ra - shift
        if r["season"] < 2021 and pd.notna(r["spread_line"]):
            hist.append((p_home, -r["spread_line"]))


def main():
    games = dl.load_games()
    rows = []
    for r, p_elo, elo_spread in walk_forward(games):
        market_spread = -float(r["spread_line"])          # home perspective, neg = home fav
        market_margin = -market_spread                     # positive = home by X
        # rest fade (margin axis, + toward home)
        adj = 0.0
        ar, hr = r.get("away_rest"), r.get("home_rest")
        if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
            adj = -0.5 if hr > ar else 0.5                # fade rested side
        adj = max(min(adj, pr.MAX_ADJ), -pr.MAX_ADJ)
        model_spread = 0.85 * market_spread + 0.15 * elo_spread - adj
        model_margin = -model_spread
        edge = model_margin - market_margin                # + = model likes home more
        home_cov = r["result"] - r["spread_line"]          # >0: home covered closing
        p_cover_home = 0.5 * (1 + math.erf((edge / MARGIN_SD) / math.sqrt(2)))
        rows.append({"season": r["season"], "week": r["week"], "edge": edge,
                     "p_cover": p_cover_home if edge > 0 else 1 - p_cover_home,
                     "pick_home": edge > 0, "home_cov": home_cov,
                     "model_margin": model_margin, "actual_margin": r["result"],
                     "market_margin": market_margin})
    df = pd.DataFrame(rows)
    df["pick_won"] = np.where(df["pick_home"], df["home_cov"] > 0, df["home_cov"] < 0)
    df["push"] = df["home_cov"] == 0

    print(f"games evaluated: {len(df)} (2021-2025 REG, closing lines)\n")

    print("=== MODEL PICKS BY EDGE THRESHOLD (ATS vs closing, -110 ROI) ===")
    print(f"{'threshold':>10} {'n':>5} {'ATS%':>7} {'push':>5} {'units':>8} {'ROI':>7}")
    for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
        sub = df[df["edge"].abs() >= t]
        dec = sub[~sub["push"]]
        if len(dec) < 10:
            continue
        wins = dec["pick_won"].sum()
        profit = wins * (100 / 110) - (len(dec) - wins)
        print(f"{t:>10.1f} {len(dec):>5} {dec['pick_won'].mean()*100:>6.1f}% "
              f"{int(sub['push'].sum()):>5} {profit:>+8.1f} {profit/len(dec)*100:>+6.1f}%")

    print("\n=== PER-SEASON ATS at the production threshold (|edge| >= 2.0) ===")
    for s, sub in df[df["edge"].abs() >= 2.0].groupby("season"):
        dec = sub[~sub["push"]]
        if len(dec):
            print(f"  {int(s)}: n={len(dec):3d}  ATS {dec['pick_won'].mean()*100:.1f}%")

    print("\n=== CALIBRATION (predicted cover prob vs actual cover rate) ===")
    picks = df[df["edge"].abs() >= 1.0].copy()
    picks["bucket"] = pd.cut(picks["p_cover"], [0, .53, .56, .60, .65, 1.0],
                             labels=["50-53%", "53-56%", "56-60%", "60-65%", "65%+"])
    for b, sub in picks.groupby("bucket", observed=True):
        dec = sub[~sub["push"]]
        if len(dec):
            print(f"  {str(b):>7}: n={len(dec):4d}  predicted {sub['p_cover'].mean()*100:.1f}%  "
                  f"actual {dec['pick_won'].mean()*100:.1f}%")

    print("\n=== MARGIN PREDICTION ERROR (does blend beat raw market?) ===")
    mae_mkt = (df["market_margin"] - df["actual_margin"]).abs().mean()
    mae_mod = (df["model_margin"] - df["actual_margin"]).abs().mean()
    print(f"  market MAE: {mae_mkt:.3f} pts | model MAE: {mae_mod:.3f} pts "
          f"({'BETTER' if mae_mod < mae_mkt else 'WORSE'} by {abs(mae_mod-mae_mkt):.3f})")
    sys.stdout.flush()
    import os
    os._exit(0)


if __name__ == "__main__":
    main()
