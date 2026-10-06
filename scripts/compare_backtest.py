import sys
sys.path.insert(0, '/app')
import data as dl
import predictor as pr
import pandas as pd
import numpy as np
import math

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
    if r["season"] >= 2021 and r["game_type"] == "REG" and pd.notna(r["spread_line"]):
        p_c = min(max(p_home, 0.02), 0.98)
        elo_spread = a * math.log(p_c / (1 - p_c)) + b
        market_spread = -float(r["spread_line"])   # home perspective
        market_margin = -market_spread
        # rest fade
        adj = 0.0
        ar, hr = r.get("away_rest"), r.get("home_rest")
        if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
            adj = -0.5 if hr > ar else 0.5
        adj = max(min(adj, pr.MAX_ADJ), -pr.MAX_ADJ)
        model_spread = 0.85 * market_spread + 0.15 * elo_spread - adj
        model_margin = -model_spread
        edge = model_margin - market_margin
        home_cov = r["result"] - r["spread_line"]   # using away spread_line
        rows.append({
            "season": r["season"],
            "week": r["week"],
            "away": r["away_team"],
            "home": r["home_team"],
            "edge": edge,
            "home_cov": home_cov,
        })
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
print(f"Games evaluated: {len(df)}")
for thresh in [0.0, 0.5, 1.0, 1.5, 2.0]:
    sub = df[df["edge"].abs() >= thresh]
    if len(sub):
        win = ((sub["edge"] > 0) & (sub["home_cov"] > 0)) | ((sub["edge"] < 0) & (sub["home_cov"] < 0))
        win_pct = win.mean() * 100
        print(f"Edge >= {thresh}: n={len(sub)}, win%={win_pct:.1f}")