"""Snap/role-trend MOMENTUM backtest — rec yards + receptions (WR/TE).

Hypothesis (Jeff, 2026-11-25): books build prop lines off season-long usage, so a
player whose ROLE is growing (recent snap share >> season-avg snap share) is
systematically underpriced — and vice versa for fading roles. If true, blending
the share projection toward the recent-3-game share should beat both v1 and the
naive trailing-10 line on MAE, with lean hit-rate >= 52.4% and per-season
persistence (2023/2024/2025).

Same pipeline/gates as backtest_props_v2.py (walk-forward, point-in-time ewm
priors halflife=6, burn-in 2021-22, script fit 2021-22, snap gate >= 40%,
eval 2023-25). Momentum variant: share_mom(w) = (1-w)*ewm_share + w*recent3_share,
grid w in {0, .25, .5, .75, 1.0}; w=0 is the current v2 baseline (control).

RESEARCH ONLY — no DB writes, no production impact. v2 lane.
"""

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/app")  # container
sys.path.insert(0, os.path.dirname(HERE))  # local v2 worktree
import data as dl
import nflverse_extra

SEASONS_ALL = (2021, 2022, 2023, 2024, 2025)
EVAL_FROM = 2023
HL = 6.0
MIN_GAMES = 4
SNAP_GATE = 0.40
SHRINK = 0.5
EDGE_SCREEN = (0.05, 0.075, 0.10)
MOM_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


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
    # ---------------- load weekly (identical to backtest_props_v2) ----------------
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

    tw = w.groupby(["season", "week", "team"], as_index=False).agg(
        team_pass_att=("attempts", "sum"), team_targets=("targets", "sum"))
    w = w.merge(tw, on=["season", "week", "team"], how="left")

    snaps_df = nflverse_extra.load_snaps(years=SEASONS_ALL)
    snaps_df["nname"] = snaps_df["player_display_name"].map(norm_name)
    snaps_df["team"] = snaps_df["team"].replace({"LAR": "LA"})  # stats use LA, snaps use LAR
    w["nname"] = w["player_display_name"].map(norm_name)
    w = w.merge(snaps_df[["season", "week", "team", "nname", "offense_pct"]],
                on=["season", "week", "team", "nname"], how="left")
    print(f"snap merge rate: {w['offense_pct'].notna().mean() * 100:.0f}% of player-weeks")

    # NOTE: agg_snap offense_pct is a FRACTION (0-1), not a percent — do NOT /100
    # (the Aug-2026 v2 backtest divided by 100, shrinking snap shares 100x, and its
    # snap gate compared fractions to 0.40 so it passed everyone — both bugs).
    target_share = np.where(w["team_targets"] > 0, w["targets"] / w["team_targets"], 0.0)
    w["share_t"] = w["offense_pct"].clip(0, 1)  # snap share, NaN = no snap data
    w["tshare"] = pd.Series(target_share, index=w.index).clip(0, 1)  # properly normalized (sums to 1)
    w["ypt"] = np.where(w["targets"] > 0, w["receiving_yards"] / w["targets"], np.nan)
    w["catch_rate"] = np.where(w["targets"] > 0, w["receptions"] / w["targets"], np.nan)

    # ---------------- team line for game script ----------------
    games = dl.load_games()
    gl = []
    for _, g in games[(games["game_type"] == "REG") & games["spread_line"].notna()].iterrows():
        gl.append({"season": g["season"], "week": g["week"], "team": g["home_team"],
                   "team_line": -g["spread_line"]})
        gl.append({"season": g["season"], "week": g["week"], "team": g["away_team"],
                   "team_line": g["spread_line"]})
    gl = pd.DataFrame(gl)
    tw_line = gl
    fit = tw_line[tw_line["season"] <= 2022]
    # script fit needs team_pass_att: merge line onto team-week volumes
    twf = tw.merge(tw_line, on=["season", "week", "team"], how="left")
    fit = twf[twf["season"] <= 2022].dropna(subset=["team_line"])
    b_pass = np.polyfit(fit["team_line"], fit["team_pass_att"], 1)
    mean_pa = fit["team_pass_att"].mean()
    print(f"script fit (2021-22): pass_att = {b_pass[0]:.3f}*team_line + {b_pass[1]:.1f}")

    def script_pass(line):
        f = (b_pass[0] * line + b_pass[1]) / mean_pa
        return float(np.clip(f, 0.85, 1.15)) if pd.notna(line) else 1.0

    w = w.merge(tw_line, on=["season", "week", "team"], how="left")

    # ---------------- opponent multipliers (point-in-time), WR/TE only ----------------
    mask = w["position"].isin(["WR", "TE"])
    d = (w[mask].groupby(["opponent_team", "season", "week"], as_index=False)["receiving_yards"].sum()
         .rename(columns={"opponent_team": "def_team", "receiving_yards": "yds_allowed"})
         .sort_values(["def_team", "season", "week"]))
    d["def_avg"] = d.groupby("def_team", group_keys=False)["yds_allowed"].apply(
        lambda s: s.shift().ewm(halflife=8, min_periods=4).mean())
    d["lg_avg"] = d["yds_allowed"].expanding().mean().shift()
    d["opp_WT"] = 1 + (d["def_avg"] / d["lg_avg"] - 1) * SHRINK
    w = w.merge(d[["def_team", "season", "week", "opp_WT"]],
                left_on=["opponent_team", "season", "week"],
                right_on=["def_team", "season", "week"], how="left").drop(columns=["def_team"])

    # ---------------- point-in-time player features ----------------
    feat_cols = ["share_t", "tshare", "ypt", "catch_rate", "receiving_yards", "receptions", "offense_pct"]
    feats = ewm_prior(w, "player_id", feat_cols)
    feats.columns = [f"e_{c}" for c in feat_cols]
    w = pd.concat([w, feats], axis=1)

    # MOMENTUM: recent-3-game means, shifted (point-in-time)
    w = w.sort_values(["player_id", "season", "week"]).reset_index(drop=True)
    w["r3_share_t"] = (w.groupby("player_id")["share_t"]
                       .transform(lambda s: s.shift().rolling(3, min_periods=2).mean()))
    w["r3_tshare"] = (w.groupby("player_id")["tshare"]
                      .transform(lambda s: s.shift().rolling(3, min_periods=2).mean()))
    # snap-momentum RATIO: recent role vs season role (1.0 = stable role);
    # missing snap history = no information = neutral 1.0 (keeps eval sets identical)
    w["snap_mom_ratio"] = (w["r3_share_t"] / w["e_share_t"].replace(0, np.nan)).clip(0.7, 1.3).fillna(1.0)

    # naive line: unweighted trailing-10 mean
    for c in ("receiving_yards", "receptions"):
        w[f"n_{c}"] = (w.groupby("player_id")[c]
                       .transform(lambda s: s.shift().rolling(10, min_periods=MIN_GAMES).mean()))

    # team pass volume point-in-time
    tw2 = tw.sort_values(["team", "season", "week"]).reset_index(drop=True)
    tw_e = ewm_prior(tw2, "team", ["team_pass_att"])
    tw_e.columns = ["e_team_pass_att"]
    tw2 = pd.concat([tw2, tw_e.reset_index(drop=True)], axis=1)
    w = w.drop(columns=["team_pass_att"], errors="ignore")
    w = w.merge(tw2[["season", "week", "team", "e_team_pass_att"]],
                on=["season", "week", "team"], how="left")

    # ---------------- projections ----------------
    w["sp_pass"] = w["team_line"].map(script_pass)
    w["v1_rec_yds"] = w["e_receiving_yards"] * w["opp_WT"]
    w["v1_rec"] = w["e_receptions"] * w["opp_WT"]

    # ---------------- share variants (all point-in-time) ----------------
    def blend(a, b, wt):  # (1-wt)*a + wt*b, falling back to a when b missing
        out = ((1 - wt) * a + wt * b)
        return pd.Series(out, index=w.index).where(b.notna(), a).clip(0, 1)

    variants = {
        "t_base": w["e_tshare"],  # target-share control (properly normalized)
        "snap_mom.5": (w["e_tshare"] * w["snap_mom_ratio"] ** 0.5).clip(0, 1),
        "snap_mom1": (w["e_tshare"] * w["snap_mom_ratio"]).clip(0, 1),
        "ts_mom.25": blend(w["e_tshare"], w["r3_tshare"], 0.25),
        "ts_mom.5": blend(w["e_tshare"], w["r3_tshare"], 0.5),
        "ts_mom.75": blend(w["e_tshare"], w["r3_tshare"], 0.75),
        "ts_mom1": blend(w["e_tshare"], w["r3_tshare"], 1.0),
    }
    # shrinkage CONTROLS: if momentum's MAE gain comes from the multiplier merely
    # averaging <1 (global shrink of an over-projecting base), these match it
    # without any momentum information.
    ratios = w["snap_mom_ratio"]
    mean_mult = float((ratios ** 0.5).mean())
    variants["shrink_mean"] = (w["e_tshare"] * mean_mult).clip(0, 1)
    variants["shrink95"] = (w["e_tshare"] * 0.95).clip(0, 1)
    print(f"\n[control] mean sqrt(snap_mom_ratio) = {mean_mult:.3f}")
    for name, share in variants.items():
        tgt = share * w["e_team_pass_att"] * w["sp_pass"]
        w[f"v_{name}_rec_yds"] = tgt * w["e_ypt"] * w["opp_WT"]
        w[f"v_{name}_rec"] = tgt * w["e_catch_rate"] * w["opp_WT"]

    # ---------------- evaluation (WR/TE, snap-gated, 2023-25) ----------------
    ev = w[(w["season"] >= EVAL_FROM) & w["e_receiving_yards"].notna()].copy()
    # real role gate: verified snap share >= 40% (no snap data = excluded, not passed)
    ev = ev[ev["position"].isin(["WR", "TE"]) & (ev["e_offense_pct"] >= SNAP_GATE)]
    print(f"\neval player-weeks (2023-25, WR/TE role-qualified): {len(ev)}\n")

    markets = [("rec_yds", "receiving_yards"), ("rec", "receptions")]

    print("=== GATE 1+2: MAE vs actuals on the COMMON subset (all variants non-NaN) ===")
    gate = {}
    for mkey, actual in markets:
        v1c = "v1_rec_yds" if mkey == "rec_yds" else "v1_rec"
        cols = [f"v_{name}_{mkey}" for name in variants]
        evc = ev.dropna(subset=cols + [v1c, f"n_{actual}"])  # one common eval set
        mae1 = evc[v1c].sub(evc[actual]).abs().mean()
        maen = evc[f"n_{actual}"].sub(evc[actual]).abs().mean()
        print(f"\n  [{mkey}] common n={len(evc)}  MAE v1={mae1:.2f}  naive={maen:.2f}")
        for name in variants:
            col = f"v_{name}_{mkey}"
            err = evc[col].sub(evc[actual])
            mae = err.abs().mean()
            bias = err.mean()
            gate[(mkey, name)] = (mae < maen) and (mae < mae1)
            print(f"    {name:>11}: MAE {mae:6.2f} (bias {bias:+5.2f})  vs v1 {'BEAT' if mae < mae1 else 'lose'}"
                  f"  vs naive {'BEAT' if mae < maen else 'lose'}")

    print("\n=== GATE 3: lean hit-rate vs naive line (breakeven 52.4%) ===")
    for mkey, actual in markets:
        for name in variants:
            col = f"v_{name}_{mkey}"
            sub = ev.dropna(subset=[col, f"n_{actual}"])
            line = f"  {mkey:>8} {name:>11}: "
            for t in EDGE_SCREEN:
                edge_pct = (sub[col] - sub[f"n_{actual}"]) / sub[f"n_{actual}"].replace(0, np.nan)
                leans = sub[edge_pct.abs() >= t]
                if len(leans) < 30:
                    line += f"{t * 100:.0f}%: n<{30}  "
                    continue
                over_lean = leans[col] > leans[f"n_{actual}"]
                hit = np.where(over_lean, leans[actual] > leans[f"n_{actual}"],
                               leans[actual] < leans[f"n_{actual}"]).mean()
                line += f"{t * 100:.0f}%: {hit * 100:.0f}% (n={len(leans)})  "
            print(line)

    print("\n=== PER-SEASON persistence (lean hit at 7.5% screen — need 3/3) ===")
    for mkey, actual in markets:
        for name in variants:
            col = f"v_{name}_{mkey}"
            sub = ev.dropna(subset=[col, f"n_{actual}"])
            edge_pct = (sub[col] - sub[f"n_{actual}"]) / sub[f"n_{actual}"].replace(0, np.nan)
            leans = sub[edge_pct.abs() >= 0.075]
            if len(leans) < 30:
                continue
            over_lean = leans[col] > leans[f"n_{actual}"]
            hits = pd.Series(np.where(over_lean, leans[actual] > leans[f"n_{actual}"],
                                      leans[actual] < leans[f"n_{actual}"]), index=leans.index)
            line = f"  {mkey:>8} {name:>11}: "
            for s, idx in leans.groupby("season").groups.items():
                line += f"{s} n={len(idx)} {hits.loc[idx].mean() * 100:.0f}%  |  "
            print(line)

    print("\n=== VERDICT (MAE gate) ===")
    for mkey, _ in markets:
        for name in variants:
            ok = gate.get((mkey, name))
            print(f"  {mkey} {name}: {'PASS' if ok else 'FAIL'}")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
