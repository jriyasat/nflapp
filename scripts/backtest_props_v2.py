"""Props Model v2 backtest: opportunity x efficiency + game script vs v1 vs naive.

Gate (agreed with Jeff): walk-forward, point-in-time. Evaluated 2023-2025
(2021-2022 = burn-in + script-fit). Pass requires:
  1. v2 MAE < v1 MAE (per market)
  2. v2 MAE < naive-line MAE (the "beat the book's number" test)
  3. lean hit-rate vs naive lines > 52.4% at the app's edge screen

v2 formulas (per player-week, all stats ewm(halflife=6) over PRIOR games):
  proj_targets  = share_t  x team_pass_att x script_pass(team_line)
  proj_rec_yds  = proj_targets x yards_per_target x opp_mult(WR/TE)
  proj_rec      = proj_targets x catch_rate       x opp_mult(WR/TE)
  proj_rush_yds = share_c  x team_rush_att x script_rush(team_line) x ypc x opp_mult(RB)
  proj_pass_yds = team_pass_att x script_pass(team_line) x ypa x opp_mult(QB)
Snap gate: only graded players with ewm snap% >= 40% (non-QB).

naive line = unweighted mean of the stat over the prior 10 games (≈ what books hang).
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/jeff/nfl-edge")
import data as dl

SEASONS_ALL = (2021, 2022, 2023, 2024, 2025)
EVAL_FROM = 2023
HL = 6.0
MIN_GAMES = 4
SNAP_GATE = 0.40
SHRINK = 0.5
EDGE_SCREEN = (0.05, 0.075, 0.10)  # |v2 - naive| / naive thresholds


def norm_name(n):
    n = str(n).lower().replace(".", "").replace(",", "")
    for suf in (" jr", " sr", " iii", " ii", " iv", " v"):
        n = n.removesuffix(suf)
    return n.strip()


def ewm_prior(df, group, cols, hl=HL, min_p=MIN_GAMES):
    """Point-in-time ewm mean of cols per group (shifted, so no leakage)."""
    df = df.sort_values([group, "season", "week"])
    return df.groupby(group, group_keys=False)[cols].apply(
        lambda g: g.shift().ewm(halflife=hl, min_periods=min_p).mean())


def main():
    # ---------------- load weekly ----------------
    frames = []
    for s in SEASONS_ALL:
        df = pd.read_csv(os.path.join(dl.CACHE, f"player_stats_{s}.csv"), low_memory=False)
        frames.append(df[df["season_type"] == "REG"])
    w = pd.concat(frames, ignore_index=True)
    num_cols = ["attempts", "passing_yards", "carries", "rushing_yards",
                "targets", "receptions", "receiving_yards"]
    for c in num_cols:
        w[c] = pd.to_numeric(w[c], errors="coerce").fillna(0.0)
    w = w.sort_values(["player_id", "season", "week"]).reset_index(drop=True)

    # ---------------- team-week volumes ----------------
    tw = w.groupby(["season", "week", "team"], as_index=False).agg(
        team_pass_att=("attempts", "sum"), team_rush_att=("carries", "sum"),
        team_targets=("targets", "sum"))
    w = w.merge(tw, on=["season", "week", "team"], how="left")
    w["share_t"] = np.where(w["team_targets"] > 0, w["targets"] / w["team_targets"], 0.0)
    w["share_c"] = np.where(w["team_rush_att"] > 0, w["carries"] / w["team_rush_att"], 0.0)
    # per-game efficiencies (0-safe)
    w["ypt"] = np.where(w["targets"] > 0, w["receiving_yards"] / w["targets"], np.nan)
    w["catch_rate"] = np.where(w["targets"] > 0, w["receptions"] / w["targets"], np.nan)
    w["ypc"] = np.where(w["carries"] > 0, w["rushing_yards"] / w["carries"], np.nan)
    w["ypa"] = np.where(w["attempts"] > 0, w["passing_yards"] / w["attempts"], np.nan)

    # ---------------- team line for game script (from games.csv) ----------------
    games = dl.load_games()
    gl = []
    for _, g in games[(games["game_type"] == "REG") & games["spread_line"].notna()].iterrows():
        gl.append({"season": g["season"], "week": g["week"], "team": g["home_team"],
                   "team_line": -g["spread_line"]})
        gl.append({"season": g["season"], "week": g["week"], "team": g["away_team"],
                   "team_line": g["spread_line"]})
    gl = pd.DataFrame(gl)
    tw = tw.merge(gl, on=["season", "week", "team"], how="left")

    # ---------------- script fit on 2021-2022 ----------------
    fit = tw[tw["season"] <= 2022].dropna(subset=["team_line"])
    b_pass = np.polyfit(fit["team_line"], fit["team_pass_att"], 1)
    b_rush = np.polyfit(fit["team_line"], fit["team_rush_att"], 1)
    mean_pa, mean_ra = fit["team_pass_att"].mean(), fit["team_rush_att"].mean()
    print(f"script fit (2021-22): pass_att = {b_pass[0]:.3f}*team_line + {b_pass[1]:.1f} | "
          f"rush_att = {b_rush[0]:.3f}*team_line + {b_rush[1]:.1f}")

    def script_pass(line):
        f = (b_pass[0] * line + b_pass[1]) / mean_pa
        return float(np.clip(f, 0.85, 1.15)) if pd.notna(line) else 1.0

    def script_rush(line):
        f = (b_rush[0] * line + b_rush[1]) / mean_ra
        return float(np.clip(f, 0.85, 1.15)) if pd.notna(line) else 1.0

    w = w.merge(gl, on=["season", "week", "team"], how="left")

    # ---------------- opponent multipliers (point-in-time) ----------------
    opp_frames = {}
    for grp, mask, col in (("QB", w["position"] == "QB", "passing_yards"),
                           ("RB", w["position"] == "RB", "rushing_yards"),
                           ("WT", w["position"].isin(["WR", "TE"]), "receiving_yards")):
        d = (w[mask].groupby(["opponent_team", "season", "week"], as_index=False)[col].sum()
             .rename(columns={"opponent_team": "def_team", col: "yds_allowed"})
             .sort_values(["def_team", "season", "week"]))
        d["def_avg"] = d.groupby("def_team", group_keys=False)["yds_allowed"].apply(
            lambda s: s.shift().ewm(halflife=8, min_periods=4).mean())
        d["lg_avg"] = d["yds_allowed"].expanding().mean().shift()
        d["opp_mult"] = 1 + (d["def_avg"] / d["lg_avg"] - 1) * SHRINK
        opp_frames[grp] = d[["def_team", "season", "week", "opp_mult"]]
    for grp, of in opp_frames.items():
        w = w.merge(of.rename(columns={"opp_mult": f"opp_{grp}"}),
                    left_on=["opponent_team", "season", "week"],
                    right_on=["def_team", "season", "week"], how="left").drop(columns=["def_team"])

    # ---------------- snap counts ----------------
    snaps = []
    for s in SEASONS_ALL:
        path = os.path.join(dl.CACHE, f"snap_counts_{s}.csv")
        if os.path.exists(path):
            sc = pd.read_csv(path, low_memory=False)
            sc = sc[["season", "week", "team", "player", "offense_pct"]].copy()
            sc["nname"] = sc["player"].map(norm_name)
            snaps.append(sc)
    snaps = pd.concat(snaps, ignore_index=True)
    snaps["offense_pct"] = pd.to_numeric(snaps["offense_pct"], errors="coerce")
    w["nname"] = w["player_display_name"].map(norm_name)
    w = w.merge(snaps[["season", "week", "team", "nname", "offense_pct"]],
                on=["season", "week", "team", "nname"], how="left")
    matched = w["offense_pct"].notna().mean()
    print(f"snap merge rate: {matched*100:.0f}% of player-weeks")

    # ---------------- point-in-time player features ----------------
    feat_cols = ["share_t", "share_c", "ypt", "catch_rate", "ypc", "ypa",
                 "passing_yards", "rushing_yards", "receiving_yards", "receptions",
                 "offense_pct"]
    feats = ewm_prior(w, "player_id", feat_cols)
    feats.columns = [f"e_{c}" for c in feat_cols]
    w = pd.concat([w, feats], axis=1)
    # naive line: unweighted trailing-10 mean
    for c in ("passing_yards", "rushing_yards", "receiving_yards", "receptions"):
        w[f"n_{c}"] = (w.sort_values(["player_id", "season", "week"])
                       .groupby("player_id")[c]
                       .transform(lambda s: s.shift().rolling(10, min_periods=MIN_GAMES).mean()))
    # team volumes point-in-time
    tw_e = ewm_prior(tw.sort_values(["team", "season", "week"]), "team",
                     ["team_pass_att", "team_rush_att"])
    tw_e.columns = ["e_team_pass_att", "e_team_rush_att"]
    tw = pd.concat([tw.sort_values(["team", "season", "week"]).reset_index(drop=True),
                    tw_e.reset_index(drop=True)], axis=1)
    w = w.drop(columns=["team_pass_att", "team_rush_att"], errors="ignore")
    w = w.merge(tw[["season", "week", "team", "e_team_pass_att", "e_team_rush_att"]],
                on=["season", "week", "team"], how="left")

    # ---------------- projections ----------------
    w["sp_pass"] = w["team_line"].map(script_pass)
    w["sp_rush"] = w["team_line"].map(script_rush)
    w["v2_rec_yds"] = w["e_share_t"] * w["e_team_pass_att"] * w["sp_pass"] * w["e_ypt"] * w["opp_WT"]
    w["v2_rec"] = w["e_share_t"] * w["e_team_pass_att"] * w["sp_pass"] * w["e_catch_rate"] * w["opp_WT"]
    w["v2_rush"] = w["e_share_c"] * w["e_team_rush_att"] * w["sp_rush"] * w["e_ypc"] * w["opp_RB"]
    w["v2_pass"] = w["e_team_pass_att"] * w["sp_pass"] * w["e_ypa"] * w["opp_QB"]
    # v1 re-implementation: ewm stat x opp mult
    w["v1_rec_yds"] = w["e_receiving_yards"] * w["opp_WT"]
    w["v1_rec"] = w["e_receptions"] * w["opp_WT"]
    w["v1_rush"] = w["e_rushing_yards"] * w["opp_RB"]
    w["v1_pass"] = w["e_passing_yards"] * w["opp_QB"]

    # ---------------- evaluation ----------------
    ev = w[(w["season"] >= EVAL_FROM) & w["e_receiving_yards"].notna()].copy()
    ev = ev[(ev["position"] == "QB") | (ev["e_offense_pct"] >= SNAP_GATE)]
    print(f"\neval player-weeks (2023-25, role-qualified): {len(ev)}\n")

    markets = [("rec_yds", "receiving_yards", ("WR", "TE")),
               ("rec", "receptions", ("WR", "TE")),
               ("rush", "rushing_yards", ("RB",)),
               ("pass", "passing_yards", ("QB",))]

    print("=== GATE 1+2: MAE vs actuals (v2 must beat v1 AND naive) ===")
    print(f"{'market':>10} {'n':>6} {'MAE v1':>8} {'MAE naive':>10} {'MAE v2':>8} {'v2<naive?':>10} {'v2<v1?':>8}")
    gate_pass = {}
    for mkey, actual, positions in markets:
        sub = ev[ev["position"].isin(positions)].dropna(
            subset=[f"v2_{mkey}", f"v1_{mkey}", f"n_{actual}"])
        mae1 = (sub[f"v1_{mkey}"] - sub[actual]).abs().mean()
        maen = (sub[f"n_{actual}"] - sub[actual]).abs().mean()
        mae2 = (sub[f"v2_{mkey}"] - sub[actual]).abs().mean()
        gate_pass[mkey] = (mae2 < maen) and (mae2 < mae1)
        print(f"{mkey:>10} {len(sub):>6} {mae1:>8.2f} {maen:>10.2f} {mae2:>8.2f} "
              f"{'YES' if mae2 < maen else 'no':>10} {'YES' if mae2 < mae1 else 'no':>8}")

    print("\n=== GATE 3: lean hit-rate vs naive line (breakeven 52.4%) ===")
    print(f"{'market':>10} {'screen':>7} {'n':>6} {'hit%':>7}")
    for mkey, actual, positions in markets:
        sub = ev[ev["position"].isin(positions)].dropna(subset=[f"v2_{mkey}", f"n_{actual}"])
        for t in EDGE_SCREEN:
            edge_pct = (sub[f"v2_{mkey}"] - sub[f"n_{actual}"]) / sub[f"n_{actual}"].replace(0, np.nan)
            leans = sub[edge_pct.abs() >= t]
            if len(leans) < 30:
                continue
            over_lean = leans[f"v2_{mkey}"] > leans[f"n_{actual}"]
            hit = np.where(over_lean, leans[actual] > leans[f"n_{actual}"],
                           leans[actual] < leans[f"n_{actual}"]).mean()
            print(f"{mkey:>10} {t*100:>6.1f}% {len(leans):>6} {hit*100:>6.1f}%")

    print("\n=== PER-SEASON consistency (lean hit-rate at 7.5% screen) ===")
    for mkey, actual, positions in markets:
        sub = ev[ev["position"].isin(positions)].dropna(subset=[f"v2_{mkey}", f"n_{actual}"])
        edge_pct = (sub[f"v2_{mkey}"] - sub[f"n_{actual}"]) / sub[f"n_{actual}"].replace(0, np.nan)
        leans = sub[edge_pct.abs() >= 0.075]
        if len(leans) < 30:
            continue
        over_lean = leans[f"v2_{mkey}"] > leans[f"n_{actual}"]
        hits = pd.Series(np.where(over_lean, leans[actual] > leans[f"n_{actual}"],
                                  leans[actual] < leans[f"n_{actual}"]), index=leans.index)
        line = f"  {mkey:>9}: "
        for s, idx in leans.groupby("season").groups.items():
            line += f"{s} n={len(idx)} {hits.loc[idx].mean()*100:.0f}%  |  "
        print(line)

    print("\n=== VERDICT ===")
    for mkey, ok in gate_pass.items():
        print(f"  {mkey}: {'PASS' if ok else 'FAIL'} (MAE gate)")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
