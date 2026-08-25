"""Injury-module backtest, 2021-2025: are the -5.5 QB / -0.4 starter adjustments
worth anything vs closing lines?

No historical injury reports exist in our data, so absences are PROXIED from
nflverse weekly player stats (point-in-time):
- "Primary QB" = team's cumulative pass-attempts leader through the PRIOR week
  (week 1: prior season's leader). QB-out proxy = primary QB has 0 attempts.
- "Skill starter" = top-3 on team in cumulative carries+targets through the
  prior week. Starter-out proxy = 0 carries AND 0 targets that week.
- Week 18 excluded (rest-week noise). REG only.

Known proxy errors (documented, cut both ways): benchings count as "out",
mid-game injuries are missed, week-1 rookie starters cause false positives.

Two questions answered:
1. EMPIRICAL: in one-sided QB-out games, how much did the affected team
   underperform the closing line? (validates the -5.5 magnitude/direction)
2. SIMULATED: the full model (market+Elo+rest+injury-proxy) graded vs closing.
"""

import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/jeff/nfl-edge")
sys.path.insert(0, "/Users/jeff/nfl-edge/scripts")
import data as dl
import predictor as pr
from backtest_model import walk_forward

SEASONS = (2021, 2022, 2023, 2024, 2025)
QB_OUT_PTS = -5.5
SKILL_OUT_PTS = -0.4
MIN_QB_ATTEMPTS = 30  # cumulative, to count as "primary"


def load_weekly():
    frames = []
    for s in SEASONS:
        path = os.path.join(dl.CACHE, f"player_stats_{s}.csv")
        df = pd.read_csv(path, low_memory=False)
        frames.append(df[df["season_type"] == "REG"])
    w = pd.concat(frames, ignore_index=True)
    for c in ("attempts", "carries", "targets"):
        w[c] = pd.to_numeric(w[c], errors="coerce").fillna(0).astype(float)
    return w


def build_proxies(weekly):
    """dict[(season, week, team)] = {'qb_out': bool, 'skill_out': int}"""
    out = {}
    qb = weekly[weekly["position"] == "QB"]
    skill = weekly[weekly["position"].isin(("RB", "WR", "TE"))]
    # prior-season attempts leader (for week-1 primaries)
    prev_leader = {}
    for s in SEASONS:
        prev = qb[qb["season"] == s - 1].groupby(["team", "player_id"])["attempts"].sum()
        for team in prev.index.get_level_values(0).unique():
            prev_leader[(s, team)] = prev.loc[team].idxmax()
    for s in SEASONS:
        qbs = qb[qb["season"] == s]
        sks = skill[skill["season"] == s]
        teams = set(weekly[weekly["season"] == s]["team"].unique())
        weeks = sorted(weekly[weekly["season"] == s]["week"].unique())
        for team in teams:
            cum_att, cum_use = {}, {}
            for wk in weeks:
                # primary QB: cumulative leader through prior weeks
                primary = max(cum_att, key=cum_att.get) if cum_att else prev_leader.get((s, team))
                if cum_att and cum_att.get(primary, 0) < MIN_QB_ATTEMPTS:
                    primary = prev_leader.get((s, team), primary)
                # top-3 skill by cumulative usage through prior weeks
                top3 = sorted(cum_use, key=cum_use.get, reverse=True)[:3]
                # this week's appearances
                qwk = qbs[(qbs["team"] == team) & (qbs["week"] == wk)]
                swk = sks[(sks["team"] == team) & (sks["week"] == wk)]
                played_qb = set(qwk[qwk["attempts"] > 0]["player_id"])
                qb_out = bool(primary) and primary not in played_qb
                skill_out = 0
                for pid in top3:
                    row = swk[swk["player_id"] == pid]
                    if row.empty or float(row["carries"].sum() + row["targets"].sum()) == 0.0:
                        skill_out += 1
                out[(s, wk, team)] = {"qb_out": qb_out, "skill_out": min(skill_out, 3)}
                # accumulate AFTER computing (point-in-time)
                for pid, att in qwk.groupby("player_id")["attempts"].sum().items():
                    cum_att[pid] = cum_att.get(pid, 0.0) + float(att)
                usage = (swk["carries"] + swk["targets"]).groupby(swk["player_id"]).sum()
                for pid, use in usage.items():
                    cum_use[pid] = cum_use.get(pid, 0.0) + float(use)
    return out


def injury_pts(info):
    pts = QB_OUT_PTS if info["qb_out"] else 0.0
    pts += SKILL_OUT_PTS * info["skill_out"]
    return max(pts, -7.0)


def main():
    weekly = load_weekly()
    proxies = build_proxies(weekly)
    n_qb = sum(1 for v in proxies.values() if v["qb_out"])
    print(f"proxy team-games with QB out: {n_qb}\n")

    games = dl.load_games()
    rows = []
    for r, p_elo, elo_spread in walk_forward(games):
        s, wk = int(r["season"]), int(r["week"])
        if wk == 18:
            continue
        away, home = r["away_team"], r["home_team"]
        ia = injury_pts(proxies.get((s, wk, away), {"qb_out": False, "skill_out": 0}))
        ih = injury_pts(proxies.get((s, wk, home), {"qb_out": False, "skill_out": 0}))
        market_spread = -float(r["spread_line"])
        total_adj = max(min(ih - ia, pr.MAX_ADJ), -pr.MAX_ADJ)  # margin axis, + toward home
        adj = 0.0
        ar, hr = r.get("away_rest"), r.get("home_rest")
        if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
            adj = -0.5 if hr > ar else 0.5
        total_adj = max(min(total_adj + adj, pr.MAX_ADJ), -pr.MAX_ADJ)
        model_spread = 0.85 * market_spread + 0.15 * elo_spread - total_adj
        edge = (-model_spread) - (-market_spread)
        home_cov = r["result"] - r["spread_line"]
        rows.append({"season": s, "week": wk, "edge": edge,
                     "qb_away": proxies.get((s, wk, away), {}).get("qb_out", False),
                     "qb_home": proxies.get((s, wk, home), {}).get("qb_out", False),
                     "inj_diff": ih - ia, "home_cov": home_cov,
                     "result": r["result"], "exp_home_margin": r["spread_line"]})
    df = pd.DataFrame(rows)
    df["pick_won"] = np.where(df["edge"] > 0, df["home_cov"] > 0, df["home_cov"] < 0)
    df["push"] = df["home_cov"] == 0

    print("=== 1. EMPIRICAL: one-sided QB-out games vs closing line ===")
    for mask, label, affected_home in (
            (df["qb_home"] & ~df["qb_away"], "HOME team's QB out", True),
            (df["qb_away"] & ~df["qb_home"], "AWAY team's QB out", False)):
        sub = df[mask]
        # margin shortfall of the affected team vs closing expectation
        shortfall = (sub["result"] - sub["exp_home_margin"]) * (1 if affected_home else -1)
        covers = (sub["home_cov"] > 0) if affected_home else (sub["home_cov"] < 0)
        dec = sub[~sub["push"]]
        print(f"  {label}: n={len(sub)}  affected team ATS {covers[sub.index.isin(dec.index)].mean()*100:.1f}%  "
              f"mean shortfall vs closing {shortfall.mean():+.2f} pts")

    print("\n=== 2. SIMULATED model (market+Elo+rest+injury-proxy) by threshold ===")
    print(f"{'threshold':>10} {'n':>5} {'ATS%':>7} {'units':>8} {'ROI':>7}")
    for t in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        sub = df[df["edge"].abs() >= t]
        dec = sub[~sub["push"]]
        if len(dec) < 10:
            continue
        wins = dec["pick_won"].sum()
        profit = wins * (100 / 110) - (len(dec) - wins)
        print(f"{t:>10.1f} {len(dec):>5} {dec['pick_won'].mean()*100:>6.1f}% "
              f"{profit:>+8.1f} {profit/len(dec)*100:>+6.1f}%")

    print("\n=== 2b. Same, ONLY games where injury proxy moved the line >= 1 pt ===")
    inj = df[df["inj_diff"].abs() >= 1.0]
    for t in (1.0, 1.5, 2.0, 2.5):
        sub = inj[inj["edge"].abs() >= t]
        dec = sub[~sub["push"]]
        if len(dec) < 10:
            continue
        wins = dec["pick_won"].sum()
        profit = wins * (100 / 110) - (len(dec) - wins)
        print(f"  >= {t:.1f}: n={len(dec):4d}  ATS {dec['pick_won'].mean()*100:.1f}%  "
              f"{profit:+.1f}u ({profit/len(dec)*100:+.1f}% ROI)")

    print("\n=== per-season, injury-driven picks (|inj_diff|>=1 & |edge|>=1.5) ===")
    sub = inj[inj["edge"].abs() >= 1.5]
    for s, ss in sub.groupby("season"):
        dec = ss[~ss["push"]]
        if len(dec):
            print(f"  {s}: n={len(dec):3d}  ATS {dec['pick_won'].mean()*100:.1f}%")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
