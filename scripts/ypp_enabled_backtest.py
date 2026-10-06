import sys, os, math, json, numpy as np, pandas as pd
os.environ['USE_YPP'] = 'true'
sys.path.insert(0, '.')
import data as dl
import predictor as pr
from ypp_model import YPPModel

K, HFA, REGRESS, START = pr.K, pr.HFA, pr.REGRESS, pr.START

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
        ypp = YPPModel()
        ypp_spread = ypp.predict_spread(r["away_team"], r["home_team"], r.get("gameday"))
        nonmarket_spread = ypp_spread * ypp_weight + elo_spread * elo_weight
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
            "season": r["season"], "week": r["week"], "away": r["away_team"], "home": r["home_team"],
            "edge": edge, "home_cov": home_cov, "market_spread": market_spread,
            "model_margin": model_margin, "market_margin": market_margin,
            "ypp_spread": ypp_spread, "elo_spread": elo_spread,
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
print(f"Games evaluated: {len(df)} (2021‑2025: {len(df[df['season'] <= 2025])}, 2026: {len(df[df['season'] == 2026])})")
thresh = 2.0
sub = df[df["edge"].abs() >= thresh]
dec = sub[sub["home_cov"] != 0]
if len(dec) == 0:
    print(f"YPP‑enabled threshold {thresh}: no picks")
else:
    win = ((dec["edge"] > 0) & (dec["home_cov"] > 0)) | ((dec["edge"] < 0) & (dec["home_cov"] < 0))
    win_pct = win.sum() / len(dec) * 100
    profit = win.sum() * (100 / 110) - (len(dec) - win.sum())
    roi = profit / len(dec) * 100
    clv = sub["edge"].mean()
    print(f"YPP‑enabled threshold {thresh}: n={len(dec)}, win%={win_pct:.1f}, ROI={roi:.1f}%, avg CLV={clv:.2f} pts")
    for _, r in dec.iterrows():
        print(f"  {r['season']} W{r['week']} {r['away']}@{r['home']}: edge={r['edge']:.2f}, ypp={r['ypp_spread']:.2f}, elo={r['elo_spread']:.2f}, home_cov={r['home_cov']:.1f}")
    # also compute edge distribution
    print(f"Edge min={df['edge'].min():.3f}, max={df['edge'].max():.3f}")
    print(f"Edge mean={df['edge'].mean():.3f}, std={df['edge'].std():.3f}")