"""Totals angles backtest vs closing totals, 2021-2025."""
import sys
sys.path.insert(0, "/Users/jeff/nfl-edge")
import pandas as pd
import data as dl

df = dl.load_games()
g = df[(df["result"].notna()) & (df["game_type"].isin(["REG", "POST"])) &
       (df["season"] >= 2021) & df["total_line"].notna()].copy()
g = g[g["total"] != g["total_line"]]  # drop pushes
g["over"] = g["total"] > g["total_line"]

def rate(mask, label):
    sub = g[mask]
    if len(sub) < 30:
        print(f"{label:44s} n={len(sub):4d} (too few)")
        return None
    pct = sub["over"].mean() * 100
    edge = pct - 52.4
    mark = "  <-- real signal" if abs(edge) > 4 else ""
    print(f"{label:44s} n={len(sub):4d}  over {pct:.1f}%  (under {100-pct:.1f}%){mark}")

print("=== TOTALS ANGLES, 2021-25 (breakeven 52.4%) ===")
rate(g["season"] >= 0, "BASELINE all games")
print()
rate(g["div_game"] == 1, "Division games")
rate(g["weekday"].astype(str).str.startswith("Thu"), "Thursday games")
rate((g["away_rest"] <= 5) | (g["home_rest"] <= 5), "Either team short rest (<=5d)")
print()
rate(g["roof"].isin(["dome", "closed"]), "Dome/closed roof")
rate(g["roof"].isin(["outdoors", "open"]), "Outdoor")
rate((g["wind"] >= 15) & g["roof"].isin(["outdoors", "open"]), "Wind 15+ (outdoor)")
rate((g["wind"] >= 10) & (g["wind"] < 15) & g["roof"].isin(["outdoors", "open"]), "Wind 10-14")
rate((g["temp"] <= 32) & g["roof"].isin(["outdoors", "open"]), "Freezing (<=32F)")
rate((g["temp"] >= 75) & g["roof"].isin(["outdoors", "open"]), "Warm (75+F)")
print()
rate(g["total_line"] >= 47, "High total (47+)")
rate(g["total_line"] <= 41.5, "Low total (<=41.5)")
rate(g["week"] <= 4, "Weeks 1-4 (early season)")
rate(g["week"] >= 15, "Weeks 15+ (late season)")
rate(g["spread_line"].abs() >= 7, "Blowout risk (spread 7+)")
rate(g["spread_line"].abs() <= 3, "Close games (spread <=3)")

print("\n=== REFEREES (min 50 games) ===")
ref = g.groupby("referee")["over"].agg(["mean", "count"])
ref = ref[ref["count"] >= 50].sort_values("mean")
print("Lowest over-rate refs:")
for name, r in ref.head(4).iterrows():
    print(f"  {name:22s} over {r['mean']*100:.1f}%  n={int(r['count'])}")
print("Highest over-rate refs:")
for name, r in ref.tail(4).iterrows():
    print(f"  {name:22s} over {r['mean']*100:.1f}%  n={int(r['count'])}")

print("\n=== POINTS-LEVEL EFFECTS (avg pts vs total_line) ===")
for mask, label in [
    ((g["wind"] >= 15) & g["roof"].isin(["outdoors", "open"]), "wind 15+"),
    (g["div_game"] == 1, "division"),
    (g["weekday"].astype(str).str.startswith("Thu"), "Thursday"),
    (g["roof"].isin(["dome", "closed"]), "dome"),
    ((g["temp"] <= 32) & g["roof"].isin(["outdoors", "open"]), "freezing"),
]:
    sub = g[mask]
    if len(sub) >= 30:
        diff = (sub["total"] - sub["total_line"]).mean()
        print(f"{label:14s} avg total-line diff: {diff:+.2f} pts  n={len(sub)}")
