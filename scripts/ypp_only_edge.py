import sys, pandas as pd, math
sys.path.insert(0, '/app')
from ypp_model import YPPModel
import data as dl

games = dl.load_games()
g = games[(games["result"].notna()) & (games["season"] >= 2021)
          & (games["game_type"] == "REG")].sort_values(["season", "week", "gameday"])
g = g.head(100)  # limit
model = YPPModel()
rows = []
for _, r in g.iterrows():
    if pd.notna(r["spread_line"]):
        market_spread = -float(r["spread_line"])
        ypp_spread = model.predict_spread(r["away_team"], r["home_team"], r.get("gameday"))
        # YPP edge assuming YPP spread same perspective as market
        market_margin = -market_spread
        edge = (-ypp_spread) - (-market_spread)  # + means model likes home more
        home_cov = r["result"] - market_margin
        pick_home = edge > 0
        pick_won = (pick_home and home_cov > 0) or (not pick_home and home_cov < 0)
        rows.append({
            "edge": edge,
            "pick_home": pick_home,
            "home_cov": home_cov,
            "pick_won": pick_won,
        })
df = pd.DataFrame(rows)
print(f"Games: {len(df)}")
# count picks where |edge| >= 2.0
thresh = 2.0
sub = df[df["edge"].abs() >= thresh]
dec = sub[sub["home_cov"] != 0]
if len(dec) > 0:
    wins = dec["pick_won"].sum()
    win_pct = wins / len(dec) * 100
    print(f"YPP‑only picks (|edge| >= {thresh}): n={len(dec)}, win%={win_pct:.1f}")
else:
    print(f"No YPP‑only picks at edge >= {thresh}")
# also check edge distribution
print(f"Edge min={df['edge'].min():.3f}, max={df['edge'].max():.3f}")
print(f"Edge mean={df['edge'].mean():.3f}, std={df['edge'].std():.3f}")