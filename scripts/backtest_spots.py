"""Backtest candidate predictor adjustments vs closing lines, 2021-2025.
Validates each 'blend' module before it goes into the predictor."""

import sys
sys.path.insert(0, "/Users/jeff/nfl-edge")
import pandas as pd
import data as dl

df = dl.load_games()
g = df[(df["result"].notna()) & (df["game_type"].isin(["REG", "POST"])) &
       (df["season"] >= 2021) & df["spread_line"].notna()].copy()
g["home_covered"] = g["home_cover_margin"] > 0
g["push"] = g["home_cover_margin"] == 0

def ats(mask, label):
    sub = g[mask & ~g["push"]]
    if len(sub) < 30:
        print(f"{label:44s} n={len(sub):4d} (too few)")
        return
    pct = sub["home_covered"].mean() * 100
    print(f"{label:44s} n={len(sub):4d}  home cover {pct:.1f}%")

print("=== BASELINE ===")
ats(g["season"] >= 0, "All games (home cover rate)")

print("\n=== REST ===")
d = g["home_rest"] - g["away_rest"]
ats(d >= 3, "Home rest edge >= 3 days")
ats(d <= -3, "Away rest edge >= 3 days (home faded)")
ats(d.abs() >= 3, "Any rest edge >= 3 (favored side = more rest)")

print("\n=== SHORT WEEK / TNF ===")
thu = g["weekday"].astype(str).str.startswith("Thu")
ats(thu, "TNF: home cover rate")
ats(g["weekday"].astype(str).str.startswith("Thu") & (g["spread_line"] <= -3),
    "TNF: home favored by 3+")

print("\n=== DIVISION ===")
ats(g["div_game"] == 1, "Division games: home cover")
ats((g["div_game"] == 1) & (g["spread_line"] > 0), "Division: home is dog (dog cover check)")

# divisional dog cover rate (dog = positive spread side)
div = g[(g["div_game"] == 1) & ~g["push"]]
home_dog = div[div["spread_line"] > 0]
away_dog = div[div["spread_line"] < 0]
dog_covers = pd.concat([home_dog["home_covered"], (~away_dog["home_covered"])])
print(f"{'Divisional dog cover rate':44s} n={len(dog_covers):4d}  {dog_covers.mean()*100:.1f}%")

print("\n=== BODY CLOCK (West away team, early ET window) ===")
import analytics as an
tz = an.TEAM_TZ
g["away_tz"] = g["away_team"].map(tz).map(an.TZ_RANK)
g["home_tz"] = g["home_team"].map(tz).map(an.TZ_RANK)
g["hour"] = pd.to_numeric(g["gametime"].astype(str).str.split(":").str[0], errors="coerce")
west_early = (g["home_tz"] - g["away_tz"] >= 2) & (g["hour"] <= 13)
ats(west_early, "West team away @ 1pm ET: home cover")

print("\n=== BIG FAVORITES / DOGS ===")
ats(g["spread_line"] <= -7, "Home favored 7+")
ats(g["spread_line"] >= 7, "Home dog 7+ (away fav)")

print("\n=== TOTALS ===")
t = g[g["total_line"].notna() & (g["total"] != g["total_line"])]
print(f"Over rate overall: {(t['total'] > t['total_line']).mean()*100:.1f}%  n={len(t)}")
wind = g[(g["wind"].notna()) & (g["roof"].isin(["outdoors", "open"])) & (g["total"] != g["total_line"])]
hw = wind[wind["wind"] >= 15]
print(f"Over rate when wind >= 15mph (outdoor): {(hw['total'] > hw['total_line']).mean()*100:.1f}%  n={len(hw)}")
