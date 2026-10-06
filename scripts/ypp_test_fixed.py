import sys, pandas as pd
sys.path.insert(0, '/app')
from ypp_model import YPPModel
import data as dl

games = dl.load_games()
g = games[(games["result"].notna()) & (games["season"] >= 2021)
          & (games["game_type"] == "REG")].head(10)
model = YPPModel()
for _, r in g.iterrows():
    if pd.notna(r["spread_line"]):
        spread = model.predict_spread(r["away_team"], r["home_team"], r.get("gameday"))
        away_net, away_n = model.get_team_ypp_stats(r["away_team"], r.get("gameday"))
        home_net, home_n = model.get_team_ypp_stats(r["home_team"], r.get("gameday"))
        print(f"{r['season']} W{r['week']} {r['away_team']}@{r['home_team']}:")
        print(f"  away_net={away_net:.2f} (n={away_n}), home_net={home_net:.2f} (n={home_n})")
        print(f"  YPP spread={spread:.2f}, market spread={-r['spread_line']:.1f}")