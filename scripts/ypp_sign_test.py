import sys, pandas as pd
sys.path.insert(0, '/app')
from ypp_model import YPPModel
import data as dl

games = dl.load_games()
g = games[(games["result"].notna()) & (games["season"] >= 2021)
          & (games["game_type"] == "REG")].sort_values(["season", "week", "gameday"])
g = g.head(20)
model = YPPModel()
for _, r in g.iterrows():
    if pd.notna(r["spread_line"]):
        market_spread = -float(r["spread_line"])   # home perspective, negative = home favored
        away, home = r["away_team"], r["home_team"]
        ypp_spread = model.predict_spread(away, home, r.get("gameday"))
        # compute edge assuming YPP spread is home perspective, same as market_spread
        # model_margin = -ypp_spread, market_margin = -market_spread
        edge = (-ypp_spread) - (-market_spread)  # + means model likes home more
        home_cov = r["result"] - market_spread
        pick_home = edge > 0
        pick_won = (pick_home and home_cov > 0) or (not pick_home and home_cov < 0)
        print(f"{r['season']} W{r['week']} {away}@{home}:")
        print(f"  market={market_spread:.1f}, ypp={ypp_spread:.2f}, edge={edge:.2f}")
        print(f"  home_cov={home_cov:.1f}, pick_home={pick_home}, won={pick_won}")