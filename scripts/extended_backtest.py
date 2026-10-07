import sys, os, math
os.environ['USE_YPP'] = 'false'
import pandas as pd
sys.path.insert(0, '.')
import data as dl
import predictor as pr

K, HFA, REGRESS, START = pr.K, pr.HFA, pr.REGRESS, pr.START

def walk_forward(games):
    g = games[(games["result"].notna()) & (games["season"] >= 2015)
              & games["game_type"].isin(["REG", "POST"])].sort_values(
                  ["season", "game_type", "week", "gameday"])
    ratings, last_season = {}, None
    hist = []
    a = b = None
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
            yield r, p_home, elo_spread
        home_won = r["result"] > 0
        mov = abs(r["result"])
        elo_diff = (rh + HFA - ra) if home_won else (ra - rh - HFA)
        mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
        shift = K * mult * ((1 if home_won else 0) - p_home)
        ratings[r["home_team"]] = rh + shift
        ratings[r["away_team"]] = ra - shift
        if r["season"] < 2021 and pd.notna(r["spread_line"]):
            hist.append((p_home, -r["spread_line"]))
import numpy as np
games = dl.load_games()
rows = []
for r, p_elo, elo_spread in walk_forward(games):
    market_spread = -float(r["spread_line"])
    market_margin = -market_spread
    adj = 0.0
    ar, hr = r.get("away_rest"), r.get("home_rest")
    if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
        adj = -0.5 if hr > ar else 0.5
    adj = max(min(adj, pr.MAX_ADJ), -pr.MAX_ADJ)
    model_spread = 0.85 * market_spread + 0.15 * elo_spread - adj
    model_margin = -model_spread
    edge = model_margin - market_margin   # + = model likes home more
    home_cov = r["result"] - market_margin
    rows.append({
        "season": r["season"], "week": r["week"],
        "edge": edge, "home_cov": home_cov,
        "market_spread": market_spread,
        "model_margin": model_margin,
        "market_margin": market_margin,
    })
df = pd.DataFrame(rows)
print(f"Games evaluated: {len(df)}")
thresh = 2.0
sub = df[df["edge"].abs() >= thresh]
dec = sub[sub["home_cov"] != 0]
if len(dec) == 0:
    print(f"Threshold {thresh}: no picks")
else:
    win = ((dec["edge"] > 0) & (dec["home_cov"] > 0)) | ((dec["edge"] < 0) & (dec["home_cov"] < 0))
    win_pct = win.sum() / len(dec) * 100
    profit = win.sum() * (100 / 110) - (len(dec) - win.sum())
    roi = profit / len(dec) * 100
    avg_edge = sub["edge"].mean()
    print(f"Threshold {thresh}: n={len(dec)}, win%={win_pct:.1f}, ROI={roi:.1f}%, avg Avg edge={avg_edge:.2f} pts")
    # show per-season breakdown
    for season in sorted(dec["season"].unique()):
        s = dec[dec["season"]==season]
        win_s = ((s["edge"] > 0) & (s["home_cov"] > 0)) | ((s["edge"] < 0) & (s["home_cov"] < 0))
        print(f"  {season}: n={len(s)}, win%={win_s.sum()/len(s)*100:.1f}")