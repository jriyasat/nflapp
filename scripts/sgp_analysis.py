"""Empirical SGP leg-correlation analysis on 2024-2025 weekly data."""
import sys

sys.path.insert(0, "/Users/jeff/nfl-edge")
import pandas as pd

import data as dl

ps = dl.load_player_stats()
ps = ps[ps["season_type"] == "REG"]
games = dl.load_games()

# per team-game: QB pass yds (top passer), WR1 rec yds (top receiver), RB1 rush yds
rows = []
for (team, season, week), grp in ps.groupby(["team", "season", "week"]):
    qb = grp[grp["position"] == "QB"].sort_values("passing_yards", ascending=False).head(1)
    wr = grp[grp["position"].isin(["WR", "TE"])].sort_values("receiving_yards", ascending=False).head(1)
    rb = grp[grp["position"] == "RB"].sort_values("rushing_yards", ascending=False).head(1)
    if qb.empty or wr.empty:
        continue
    rows.append({
        "team": team, "season": season, "week": week,
        "qb_yds": qb["passing_yards"].iloc[0], "qb_id": qb["player_id"].iloc[0],
        "wr_yds": wr["receiving_yards"].iloc[0], "wr_id": wr["player_id"].iloc[0],
        "rb_yds": rb["rushing_yards"].iloc[0] if not rb.empty else None,
        "rb_id": rb["player_id"].iloc[0] if not rb.empty else None,
    })
tg = pd.DataFrame(rows)

# player season averages as the "line" proxy
avg_qb = ps[ps["position"] == "QB"].groupby(["player_id", "season"])["passing_yards"].mean().rename("qb_avg")
avg_wr = ps[ps["position"].isin(["WR", "TE"])].groupby(["player_id", "season"])["receiving_yards"].mean().rename("wr_avg")
avg_rb = ps[ps["position"] == "RB"].groupby(["player_id", "season"])["rushing_yards"].mean().rename("rb_avg")
tg = tg.merge(avg_qb, left_on=["qb_id", "season"], right_index=True)
tg = tg.merge(avg_wr, left_on=["wr_id", "season"], right_index=True)
tg = tg.merge(avg_rb, left_on=["rb_id", "season"], right_index=True)

# attach game info (closing lines, result)
gg = games[(games["game_type"] == "REG") & games["result"].notna()][
    ["season", "week", "home_team", "away_team", "result", "total", "spread_line", "total_line"]]
h = gg.rename(columns={"home_team": "team"})
h["margin"] = h["result"]; h["cover_margin"] = h["result"] - h["spread_line"]
a = gg.rename(columns={"away_team": "team"})
a["margin"] = -a["result"]; a["cover_margin"] = -a["result"] + a["spread_line"]
tg = tg.merge(pd.concat([h, a])[["season", "week", "team", "margin", "cover_margin", "total", "total_line"]],
              on=["season", "week", "team"], how="left")

tg["qb_over"] = tg["qb_yds"] > tg["qb_avg"]
tg["wr_over"] = tg["wr_yds"] > tg["wr_avg"]
tg["rb_over"] = tg["rb_yds"] > tg["rb_avg"]
tg["covered"] = tg["cover_margin"] > 0
tg["won"] = tg["margin"] > 0
tg["game_over"] = tg["total"] > tg["total_line"]
tg = tg.dropna(subset=["cover_margin", "total_line"])

def lift(col_a, col_b, label):
    sub = tg.dropna(subset=[col_a, col_b])
    pa, pb = sub[col_a].mean(), sub[col_b].mean()
    joint = (sub[col_a] & sub[col_b]).mean()
    l = joint / (pa * pb) if pa * pb else float("nan")
    print(f"{label:44s} n={len(sub):5d}  P(a)={pa:.2f} P(b)={pb:.2f} joint={joint:.3f} naive={pa*pb:.3f}  LIFT={l:.3f}")

print("=== EMPIRICAL SGP CORRELATION LIFTS (2024-25 REG) ===")
lift("qb_over", "wr_over", "QB pass over + WR1 rec over (same team)")
lift("qb_over", "game_over", "QB pass over + game OVER")
lift("qb_over", "covered", "QB pass over + team covers")
lift("rb_over", "covered", "RB1 rush over + team covers")
lift("rb_over", "won", "RB1 rush over + team wins")
lift("covered", "game_over", "team covers + game OVER")
lift("won", "game_over", "team wins + game OVER")
lift("wr_over", "game_over", "WR1 rec over + game OVER")

# SD ratios for prop distributions (per-game deviation from season avg)
for pos, stat, avg in (("QB", "passing_yards", "qb_avg"), ("RB", "rushing_yards", "rb_avg")):
    pass
sub = tg.dropna(subset=["qb_avg"])
print("\nQB pass yds: mean=%.0f sd=%.0f sd/mean=%.2f" % (sub["qb_avg"].mean(), (sub["qb_yds"]-sub["qb_avg"]).std(), (sub["qb_yds"]-sub["qb_avg"]).std()/sub["qb_avg"].mean()))
sub2 = tg.dropna(subset=["rb_avg"])
print("RB rush yds: mean=%.0f sd=%.0f sd/mean=%.2f" % (sub2["rb_avg"].mean(), (sub2["rb_yds"]-sub2["rb_avg"]).std(), (sub2["rb_yds"]-sub2["rb_avg"]).std()/sub2["rb_avg"].mean()))
sub3 = tg.dropna(subset=["wr_avg"])
print("WR1 rec yds: mean=%.0f sd=%.0f sd/mean=%.2f" % (sub3["wr_avg"].mean(), (sub3["wr_yds"]-sub3["wr_avg"]).std(), (sub3["wr_yds"]-sub3["wr_avg"]).std()/sub3["wr_avg"].mean()))
