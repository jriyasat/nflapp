"""Player prop projections: recency-weighted volume + opponent defensive adjustment.

Markets modeled: passing_yards, rushing_yards, receiving_yards, receptions.
Method (transparent v1):
  base   = exponentially-weighted per-game rate over last 2 seasons (halflife 6 games)
  opp    = opponent yards allowed to that position group / league average, 50% shrunk
  proj   = base * opp
"""




import os, json, numpy as np

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config/model_weights.json")
try:
    with open(CONFIG_PATH) as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {}

snap_share_weight = CONFIG.get("snap_share_weight", 1.0)
target_share_weight = CONFIG.get("target_share_weight", 0.0)
ryoe_multiplier = CONFIG.get("ryoe_multiplier", 1.0)
separation_multiplier = CONFIG.get("separation_multiplier", 1.0)
cushion_multiplier = CONFIG.get("cushion_multiplier", 1.0)
pass_volume_factor = CONFIG.get("props_pass_volume_factor", CONFIG.get("pass_volume_factor", 1.0))
rush_volume_factor = CONFIG.get("props_rush_volume_factor", CONFIG.get("rush_volume_factor", 1.0))
ypp_weight = CONFIG.get("ypp_weight", 0.85)
elo_weight = CONFIG.get("elo_weight", 0.15)
HALFLIFE = 6.0
MIN_GAMES = {"QB": 4, "RB": 4, "WR": 4, "TE": 4}
SHRINK = 0.5

STAT_BY_MARKET = {
    "player_pass_yds": "passing_yards",
    "player_rush_yds": "rushing_yards",
    "player_reception_yds": "receiving_yards",
    "player_receptions": "receptions",
    "player_pass_td": "passing_tds",
    "player_rush_td": "rushing_tds",
    "player_rec_td": "receiving_tds",
}
POS_BY_MARKET = {
    "player_pass_yds": "QB",
    "player_rush_yds": "RB",
    "player_reception_yds": "WR/TE",
    "player_receptions": "WR/TE",
    "player_pass_td": "QB",
    "player_rush_td": "RB",
    "player_rec_td": "WR/TE",
}
USAGE_COL = {"QB": "attempts", "RB": "carries", "WR/TE": "targets"}

# --- v2 rushing model (backtest-validated, scripts/backtest_props_v2.py) ---
# Gate results 2023-25: beats v1 AND naive-line MAE; lean hit 61% (n=1199),
# consistent 61/59/63% per season. Rush-only: rec/pass v2 FAILED the gate
# and stay on v1. Fit on 2021-25 team-week data (neg team_line = favored):
RUSH_SCRIPT_SLOPE = -0.2284   # team rush attempts per pt of team_line
RUSH_ATT_MEAN = 26.92         # league mean team rush attempts/game
PASS_SCRIPT_SLOPE = 0.15      # team pass attempts per pt of team_line (positive = underdogs pass more)
PASS_ATT_MEAN = 35.0          # league mean team pass attempts/game


def script_rush(team_line):
    """Game-script rush-volume factor: favorites run more. 1.0 when no line."""
    if team_line is None:
        return 1.0
    return float(min(max(1 + RUSH_SCRIPT_SLOPE * team_line / RUSH_ATT_MEAN, 0.85), 1.15))
def script_pass(team_line):
    """Game-script pass-volume factor: underdogs pass more. 1.0 when no line."""
    if team_line is None:
        return 1.0
    return float(min(max(1 + PASS_SCRIPT_SLOPE * team_line / PASS_ATT_MEAN, 0.85), 1.15))

def _weights(n):
    return [0.5 ** (i / HALFLIFE) for i in range(n)]


def _wavg(vals, wts):
    s = sum(wts)
    return sum(v * w for v, w in zip(vals, wts)) / s if s else 0.0


def defense_multipliers(ps):
    """Yards allowed per game by each defense to each position group, vs league avg."""
    out = {}
    reg = ps[ps["season_type"] == "REG"]
    for group, mask in (("QB", reg["position"] == "QB"),
                        ("RB", reg["position"] == "RB"),
                        ("WR/TE", reg["position"].isin(["WR", "TE"]))):
        sub = reg[mask]
        if group == "QB":
            stat = sub.groupby(["opponent_team", "season", "week"])["passing_yards"].sum()
        elif group == "RB":
            stat = sub.groupby(["opponent_team", "season", "week"])["rushing_yards"].sum()
        else:
            stat = sub.groupby(["opponent_team", "season", "week"])["receiving_yards"].sum()
        per_def = stat.groupby("opponent_team").mean()
        lg = per_def.mean()
        out[group] = {team: 1 + (v / lg - 1) * SHRINK for team, v in per_def.items()}
    return out


def _norm(name):
    n = str(name).lower().replace(".", "").replace(",", "")
    for suf in (" jr", " sr", " iii", " ii", " iv"):
        n = n.removesuffix(suf)
    return n.strip()


PROJ_STAT = {"proj_pass": "passing_yards", "proj_rush": "rushing_yards",
             "proj_rec_yds": "receiving_yards", "proj_rec": "receptions",
             "proj_pass_td": "passing_tds", "proj_rush_td": "rushing_tds",
             "proj_rec_td": "receiving_tds"}


def hit_rate(ps, player_id, proj_col, line, last_n=10):
    """Over/under record vs a line over the player's last N REG games."""
    if line is None:
        return None
    scol = PROJ_STAT.get(proj_col)
    g = ps[(ps["player_id"] == player_id) & (ps["season_type"] == "REG")]
    g = g.sort_values(["season", "week"]).tail(last_n)
    if g.empty:
        return None
    overs = int((g[scol] > line).sum())
    unders = int((g[scol] < line).sum())
    return {"n": len(g), "overs": overs, "unders": unders}


def project_game(ps, defs, team, opponent, per_pos=2, injuries=None, team_line=None, snaps_df=None):
    """Projections for one team's key players vs an opponent.

    injuries: {player_name: status} from the official report. Out/Doubtful
    players are benched and 60% of their vacated volume is redistributed to
    remaining players in the same position group. Questionable -> flagged.
    team_line: team's spread for this game (negative = favored) — drives the
    v2 rushing model's game-script factor.
    snaps_df: optional DataFrame from nflverse_extra.load_snaps(); if None,
        load via nflverse_extra (cached).

    Returns {"players": [...], "benched": [...], "warnings": [...]}."""
    reg = ps[(ps["team"] == team) & (ps["season_type"] == "REG")].copy()
    reg = reg.sort_values(["season", "week"], ascending=False)
    # team rush volume per week (for v2 carry‑share model)
    team_rush = (reg.groupby(["season", "week"])["carries"].sum()
                 .rename("team_rush_att").reset_index())
    # team pass volume per week (for snap‑share volume)
    team_pass = (reg.groupby(["season", "week"])["attempts"].sum()
                 .rename("team_pass_att").reset_index())
    
    # load snap counts if not supplied (cached)
    if snaps_df is None:
        import nflverse_extra
        snaps_df = nflverse_extra.load_snaps(years=None)
    # normalize player names for merging
    snaps_df["norm_name"] = snaps_df["player_display_name"].apply(_norm)
    reg["norm_name"] = reg["player_display_name"].apply(_norm)
    # merge snap counts into reg
    print(f"[DEBUG] snaps_df columns: {list(snaps_df.columns)}")
    print(f"[DEBUG] required cols: team, season, week, norm_name, offense_snaps, offense_pct")
    reg_with_snaps = reg.merge(
        snaps_df[["team", "season", "week", "norm_name", "offense_snaps", "offense_pct"]],
        on=["team", "season", "week", "norm_name"], how="left"
    )
    # compute snap share fraction
    reg_with_snaps["snap_share"] = reg_with_snaps["offense_pct"].fillna(0) / 100
    
    # merge team rush/pass volumes
    reg_with_snaps = reg_with_snaps.merge(team_rush, on=["season", "week"], how="left")
    reg_with_snaps = reg_with_snaps.merge(team_pass, on=["season", "week"], how="left")
    reg_with_snaps["team_rush_att"] = reg_with_snaps["team_rush_att"].fillna(0)
    reg_with_snaps["team_pass_att"] = reg_with_snaps["team_pass_att"].fillna(0)

    # compute target share if targets column present
    if "targets" in reg.columns:
        team_targets = (reg.groupby(["season", "week"])["targets"].sum()
                        .rename("team_targets").reset_index())
        reg_with_snaps = reg_with_snaps.merge(team_targets, on=["season", "week"], how="left")
        reg_with_snaps["target_share"] = np.where(
            reg_with_snaps["team_targets"] > 0,
            reg_with_snaps["targets"] / reg_with_snaps["team_targets"],
            0.0
        )
    else:
        reg_with_snaps["target_share"] = 0.0

    # blend snap_share and target_share using configurable weights
    reg_with_snaps["share_t"] = (snap_share_weight * reg_with_snaps["snap_share"] +
                                 target_share_weight * reg_with_snaps["target_share"])
    reg_with_snaps["share_t"] = reg_with_snaps["share_t"].clip(0, 1)
    
    inj = {_norm(k): v for k, v in (injuries or {}).items()}
    players, benched, warnings = [], [], []
    for pos, grp in (("QB", ["QB"]), ("RB", ["RB"]), ("WR/TE", ["WR", "TE"])):
        sub = reg_with_snaps[reg_with_snaps["position"].isin(grp)]
        # define usage per week based on snap share
        if pos == "RB":
            sub["usage_week"] = sub["snap_share"] * sub["team_rush_att"] * rush_volume_factor
        else:  # QB, WR, TE
            sub["usage_week"] = sub["snap_share"] * sub["team_pass_att"] * pass_volume_factor
        # compute weighted average usage per player (exponential weighting)
        usage_dict = {}
        for (pid, name, ppos), g in sub.groupby(["player_id", "player_display_name", "position"]):
            w = _weights(len(g))
            usage_val = _wavg(g["usage_week"].fillna(0).tolist(), w)
            usage_dict[(pid, name, ppos)] = max(usage_val, 0.0)
        
        want = 1 if pos == "QB" else per_pos
        selected, vacated = [], 0.0
        for key, use in sorted(usage_dict.items(), key=lambda kv: kv[1], reverse=True):
            pid, name, ppos = key
            st = inj.get(_norm(name))
            if st in ("Out", "Doubtful"):
                vacated += float(use)
                benched.append({"player": name, "pos": ppos, "status": st})
                continue
            selected.append((pid, name, ppos, st, float(use)))
            if len(selected) >= want:
                break
        if pos == "QB" and vacated and not selected:
            warnings.append(f"🚨 {team} QB1 is out — pass‑catcher projections unreliable")
        if pos == "QB" and vacated and selected:
            warnings.append(f"🚨 {team} QB1 out — {selected[0][1]} steps in; downgrade pass projections")
        sel_total = sum(u for *_ , u in selected)
        boost = 1 + 0.6 * vacated / sel_total if (vacated and sel_total and pos != "QB") else 1.0
        
        for pid, name, ppos, st, _use in selected:
            g = sub[sub["player_id"] == pid].sort_values(["season", "week"], ascending=False)
            if len(g) < MIN_GAMES.get(ppos, 4):
                continue
            w = _weights(len(g))
            mult = defs.get(pos, {}).get(opponent, 1.0)
            # v2 rushing (backtest‑validated): carry share x team rush volume x
            # game script x volume‑weighted YPC x opponent. RB only.
            rush_v2 = False
            if ppos == "RB":
                carries = g["carries"].fillna(0).tolist()
                yards = g["rushing_yards"].fillna(0).tolist()
                share_c = _wavg([c / t if t > 0 else 0.0 for c, t in zip(carries, g["team_rush_att"].fillna(0).tolist())], w)
                team_att = _wavg(g["team_rush_att"].fillna(0).tolist(), w)
                tot_car = sum(c * wi for c, wi in zip(carries, w))
                ypc = sum(y * wi for y, wi in zip(yards, w)) / tot_car if tot_car > 0 else 0.0
                proj_rush = round(share_c * team_att * script_rush(team_line) * ypc
                                  * defs["RB"].get(opponent, 1.0) * boost, 1)
                rush_v2 = True
            elif ppos == "QB":
                proj_rush = round(_wavg(g["rushing_yards"].fillna(0).tolist(), w), 1)
            else:
                proj_rush = None
            row = {
                "player": name, "pos": ppos, "team": team, "games": len(g),
                "proj_pass": round(_wavg(g["passing_yards"].fillna(0).tolist(), w) * (defs["QB"].get(opponent, 1.0) if ppos == "QB" else 1.0), 1) if ppos == "QB" else None,
                "proj_rush": proj_rush,
                "proj_rec_yds": round(_wavg(g["receiving_yards"].fillna(0).tolist(), w) * mult * boost, 1) if ppos in ("WR", "TE", "RB") else None,
                "proj_rec": round(_wavg(g["receptions"].fillna(0).tolist(), w) * mult * boost, 1) if ppos in ("WR", "TE", "RB") else None,
                "proj_pass_td": round(_wavg(g["passing_tds"].fillna(0).tolist(), w) * (defs["QB"].get(opponent, 1.0) if ppos == "QB" else 1.0), 1) if ppos == "QB" else None,
                "proj_rush_td": round(_wavg(g["rushing_tds"].fillna(0).tolist(), w) * defs["RB"].get(opponent, 1.0) * boost, 1) if ppos == "RB" else None,
                "proj_rec_td": round(_wavg(g["receiving_tds"].fillna(0).tolist(), w) * mult * boost, 1) if ppos in ("WR", "TE", "RB") else None,
                "opp_mult": round(mult, 3),
                "flag": st or "",
                "boost": round(boost, 2) if boost != 1.0 else None,
                "rush_v2": rush_v2,
            }
            players.append(row)
    return {"players": players, "benched": benched, "warnings": warnings}


MARKET_TO_PROJ = {
    "player_pass_yds": "proj_pass",
    "player_rush_yds": "proj_rush",
    "player_reception_yds": "proj_rec_yds",
    "player_receptions": "proj_rec",
    "player_pass_td": "proj_pass_td",
    "player_rush_td": "proj_rush_td",
    "player_rec_td": "proj_rec_td",
}


def edges_vs_lines(projections, props_lines):
    """Attach market lines to projections; compute edge where both exist."""
    by_name = {}
    for mkt, players in (props_lines or {}).items():
        col = MARKET_TO_PROJ.get(mkt)
        if not col:
            continue
        for pname, line in players.items():
            by_name.setdefault(pname, {})[col] = line
    for p in projections:
        p["lines"] = by_name.get(p["player"], {})
        p["edges"] = {}
        for col, line in p["lines"].items():
            proj = p.get(col)
            if proj is None or line.get("point") is None:
                continue
            edge = proj - line["point"]
            p["edges"][col] = {
                "line": line["point"], "edge": round(edge, 1),
                "edge_pct": round(edge / line["point"] * 100, 1) if line["point"] else 0,
                "over_price": line.get("over_price"), "under_price": line.get("under_price"),
                "over_book": line.get("over_book"), "under_book": line.get("under_book"),
                "n_books": line.get("n_books", 0),
                "lean": "OVER" if edge > 0 else "UNDER",
            }
    return projections
