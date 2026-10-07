#!/usr/bin/env python
"""
Walk-forward backtest of sides/totals model (market + YPP + Elo) using SGO real‑book closing lines.
Scope: REG season games 2021‑2026 (including current partial season).

Honesty rules:
- Elo point‑in‑time: ratings updated only with games BEFORE the predicted one.
- YPP differential uses rolling last‑4 games before date (via YPPModel).
- Market lines: SGO cached closing lines (real books) where available; fallback to nflverse spread_line.
- Rest‑fade adjustment included (validated 47% ATS).
- Injuries/weather/referee excluded (historical data unavailable).
- Graded vs closing line, pushes excluded, ROI at -110.
- Threshold 2.0 for picks (production threshold).

Output: win%, ROI, avg_edge, n per config (candidate vs current).
"""

import os
os.environ['USE_YPP'] = 'false'
import sys
import json
import math
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl
import predictor as pr
from ypp_model import YPPModel

# Load configurable weights
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'model_weights.json')
def load_weights(config_overrides=None):
    """
    Load weights from config file, optionally override with dict.
    Returns market_weight, nonmarket_weight, ypp_weight, elo_weight.
    """
    try:
        with open(_CONFIG_PATH) as f:
            config = json.load(f)
    except Exception:
        config = {}
    # Apply overrides
    if config_overrides:
        config.update(config_overrides)
    market_weight = config.get('market_weight', 0.85)
    nonmarket_weight = 1.0 - market_weight
    ypp_weight = config.get('ypp_weight', 0.85)
    elo_weight = config.get('elo_weight', 0.15)
    if not pr.USE_YPP:
        ypp_weight = 0.0
        elo_weight = 1.0
    # Normalize ypp/elo within non-market portion (as in predictor)
    total = ypp_weight + elo_weight
    if total > 0:
        ypp_weight /= total
        elo_weight /= total
    return market_weight, nonmarket_weight, ypp_weight, elo_weight

# Defaults (used when script imported as module)
MARKET_WEIGHT, NONMARKET_WEIGHT, YPP_WEIGHT, ELO_WEIGHT = load_weights()

# Predictor constants (rest fade magnitude)
MAX_ADJ = pr.MAX_ADJ
REST_FADE_PTS = 0.5   # validated 0.5 pts fade rested side
MARGIN_SD = pr.MARGIN_SD

# Build inverse mapping: abbreviation → long name
ABBR_TO_LONG = {abbr: long for long, abbr in dl.TEAM_NAME_TO_ABBR.items()}

def walk_forward(games, ypp_model, market_lines_fn):
    """
    Generator yielding (game_row, elo_spread, ypp_spread, market_spread, market_src)
    with point‑in‑time ratings.
    """
    # Filter games with known result, REG season only
    g = games[(games["result"].notna()) & (games["season"] >= 2015)
              & games["game_type"].isin(["REG", "POST"])].sort_values(
                  ["season", "game_type", "week", "gameday"])
    ratings, last_season = {}, None
    hist = []   # (p_prior, home spread) for Elo‑spread map fitting (pre‑2021 only)
    a = b = None
    hist_ypp = []  # (strength_diff, spread_line) for YPP coefficient fitting
    a_ypp = b_ypp = None
    for _, r in g.iterrows():
        if last_season is not None and r["season"] != last_season:
            ratings = {t: pr.START + (e - pr.START) * (1 - pr.REGRESS)
                       for t, e in ratings.items()}
        last_season = r["season"]
        ra = ratings.get(r["away_team"], pr.START)
        rh = ratings.get(r["home_team"], pr.START)
        p_home = 1 / (1 + 10 ** (-((rh + pr.HFA) - ra) / 400))
        if r["season"] >= 2021 and a is None:
            # fit spread map on 2015-2020 once 2021 begins
            h = pd.DataFrame(hist, columns=["p", "spread"])
            h["logit"] = h["p"].clip(0.02, 0.98).apply(lambda p: math.log(p / (1 - p)))
            A = np.vstack([h["logit"], np.ones(len(h))]).T
            a, b = np.linalg.lstsq(A, h["spread"], rcond=None)[0]
            if a_ypp is None and len(hist_ypp) > 0:
                # fit YPP coefficients on pre-2021 data
                hy = pd.DataFrame(hist_ypp, columns=["diff", "spread"])
                A_ypp = np.vstack([hy["diff"], np.ones(len(hy))]).T
                a_ypp, b_ypp = np.linalg.lstsq(A_ypp, hy["spread"], rcond=None)[0]
        if r["season"] >= 2021 and r["game_type"] == "REG":
            # Compute Elo spread
            p_c = min(max(p_home, 0.02), 0.98)
            elo_spread = a * math.log(p_c / (1 - p_c)) + b
            # Compute YPP spread (point‑in‑time) using fitted coefficients if available
            away_net, away_n = ypp_model.get_team_ypp_stats(r["away_team"], r.get("gameday"))
            home_net, home_n = ypp_model.get_team_ypp_stats(r["home_team"], r.get("gameday"))
            if away_n == 0 or home_n == 0:
                ypp_diff = 0.0
            else:
                ypp_diff = home_net - away_net
            if a_ypp is not None:
                ypp_spread = -(a_ypp + b_ypp * ypp_diff)
            else:
                # fallback to static coefficients
                ypp_spread = ypp_model.predict_spread(r["away_team"], r["home_team"],
                                                      date=r.get("gameday"))
            # Get market line
            market_spread, market_src = market_lines_fn(r)
            if market_spread is None:
                # fallback to nflverse spread_line
                if pd.notna(r.get("spread_line")):
                    market_spread = -float(r["spread_line"])
                    market_src = "nflverse"
                else:
                    market_spread = elo_spread   # placeholder
                    market_src = "none"
            yield r, elo_spread, ypp_spread, market_spread, market_src
        # Update ratings with this game's result
        home_won = r["result"] > 0
        mov = abs(r["result"])
        elo_diff = (rh + pr.HFA - ra) if home_won else (ra - rh - pr.HFA)
        mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
        shift = pr.K * mult * ((1 if home_won else 0) - p_home)
        ratings[r["home_team"]] = rh + shift
        ratings[r["away_team"]] = ra - shift
        if r["season"] < 2021 and pd.notna(r["spread_line"]):
            hist.append((p_home, -r["spread_line"]))
            # also collect YPP differential for coefficient fitting
            away_net, away_n = ypp_model.get_team_ypp_stats(r["away_team"], r.get("gameday"))
            home_net, home_n = ypp_model.get_team_ypp_stats(r["home_team"], r.get("gameday"))
            if away_n > 0 and home_n > 0:
                strength_diff = home_net - away_net
                hist_ypp.append((strength_diff, -r["spread_line"]))

def evaluate_config(games, ypp_model, market_lines_fn, market_weight, nonmarket_weight,
                    ypp_weight, elo_weight, threshold=2.0):
    """
    Run walk‑forward backtest with given weights.
    Returns dict with win%, ROI, avg_edge, n (picks at threshold).
    """
    rows = []
    for r, elo_spread, ypp_spread, market_spread, market_src in walk_forward(games, ypp_model, market_lines_fn):
        # Non‑market blend
        nonmarket_spread = ypp_spread * ypp_weight + elo_spread * elo_weight
        # Base market spread (if missing, use Elo‑derived from market probability?)
        # We assume market_spread already home perspective.
        base_spread = market_spread
        # Rest‑fade adjustment
        adj = 0.0
        ar, hr = r.get("away_rest"), r.get("home_rest")
        if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
            adj = -REST_FADE_PTS if hr > ar else REST_FADE_PTS  # fade rested side
        adj = max(min(adj, MAX_ADJ), -MAX_ADJ)
        # Final blend
        model_spread = market_weight * base_spread + nonmarket_weight * nonmarket_spread - adj
        model_margin = -model_spread          # positive = home wins by X
        market_margin = -market_spread
        edge = model_margin - market_margin   # + = model likes home more
        # Did home cover closing spread?
        home_cov = r["result"] - market_margin
        # Cover probability (assuming normal margin error)
        p_cover_home = 0.5 * (1 + math.erf((edge / MARGIN_SD) / math.sqrt(2)))
        rows.append({
            "season": r["season"],
            "week": r["week"],
            "edge": edge,
            "p_cover": p_cover_home if edge > 0 else 1 - p_cover_home,
            "pick_home": edge > 0,
            "home_cov": home_cov,
            "model_margin": model_margin,
            "actual_margin": r["result"],
            "market_margin": market_margin,
            "market_src": market_src,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n_games": 0, "n_picks": 0, "win_pct": 0.0, "roi": 0.0, "clv": 0.0}
    df["pick_won"] = np.where(df["pick_home"], df["home_cov"] > 0, df["home_cov"] < 0)
    df["push"] = df["home_cov"] == 0
    # Subset where |edge| >= threshold
    sub = df[df["edge"].abs() >= threshold]
    dec = sub[~sub["push"]]
    if len(dec) == 0:
        return {"n_games": len(df), "n_picks": 0, "win_pct": 0.0, "roi": 0.0, "clv": 0.0}
    wins = dec["pick_won"].sum()
    profit = wins * (100 / 110) - (len(dec) - wins)  # -110 odds
    roi = profit / len(dec) * 100
    # Average edge on picks (not closing‑line value)
    avg_edge = sub["edge"].mean()
    return {
        "n_games": len(df),
        "n_picks": len(dec),
        "win_pct": dec["pick_won"].mean() * 100,
        "roi": roi,
        "clv": avg_edge,
        "full_df": df,   # for debugging
    }

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=2.0,
                        help="Edge threshold for picks (default 2.0)")
    parser.add_argument("--out", help="JSON file to save results")
    # Weight overrides
    parser.add_argument("--market_weight", type=float, help="Market weight (0-1)")
    parser.add_argument("--ypp_weight", type=float, help="YPP weight (0-1)")
    parser.add_argument("--elo_weight", type=float, help="Elo weight (0-1)")
    parser.add_argument("--pass_volume_factor", type=float, help="Pass volume factor")
    parser.add_argument("--rush_volume_factor", type=float, help="Rush volume factor")
    parser.add_argument("--snap_share_weight", type=float, help="Snap share weight")
    parser.add_argument("--target_share_weight", type=float, help="Target share weight")
    args = parser.parse_args()
    
    # Build overrides dict from non‑None args
    overrides = {}
    if args.market_weight is not None:
        overrides['market_weight'] = args.market_weight
    if args.ypp_weight is not None:
        overrides['ypp_weight'] = args.ypp_weight
    if args.elo_weight is not None:
        overrides['elo_weight'] = args.elo_weight
    if args.pass_volume_factor is not None:
        overrides['pass_volume_factor'] = args.pass_volume_factor
    if args.rush_volume_factor is not None:
        overrides['rush_volume_factor'] = args.rush_volume_factor
    if args.snap_share_weight is not None:
        overrides['snap_share_weight'] = args.snap_share_weight
    if args.target_share_weight is not None:
        overrides['target_share_weight'] = args.target_share_weight
    
    # Compute final weights (normalized)
    market_weight, nonmarket_weight, ypp_weight, elo_weight = load_weights(overrides)
    
    # Load data
    games = dl.load_games()
    ypp_model = YPPModel()
    # Market lines function
    def market_line_fn(game_row):
        # Try SGO cache first
        books = dl.cached_sgo_lines()
        if books:
            away_long = ABBR_TO_LONG.get(game_row["away_team"].upper())
            home_long = ABBR_TO_LONG.get(game_row["home_team"].upper())
            if away_long and home_long:
                key = (away_long, home_long)
                if key in books:
                    market = pr.consensus(books[key])
                    if market.get("home_spread") is not None:
                        return market["home_spread"], "books"
        # Fallback to nflverse spread_line
        if pd.notna(game_row.get("spread_line")):
            return -float(game_row["spread_line"]), "nflverse"
        return None, "none"
    
    print(f"Running walk‑forward backtest (2021‑2026) with threshold {args.threshold}...")
    print(f"Weights: market={market_weight:.2f}, non‑market={nonmarket_weight:.2f}, ypp={ypp_weight:.2f}, elo={elo_weight:.2f}")
    result = evaluate_config(games, ypp_model, market_line_fn,
                             market_weight, nonmarket_weight, ypp_weight, elo_weight,
                             threshold=args.threshold)
    
    print(f"\nGames evaluated: {result['n_games']}")
    print(f"Picks (|edge| ≥ {args.threshold}): {result['n_picks']}")
    if result['n_picks']:
        print(f"Win %: {result['win_pct']:.1f}%")
        print(f"ROI (%): {result['roi']:.1f}%")
        print(f"Avg edge: {result['clv']:.2f} pts")
    
    if args.out:
        with open(args.out, "w") as f:
            json.dump({k: v for k, v in result.items() if k != "full_df"}, f, indent=2)
        print(f"Results saved to {args.out}")

if __name__ == "__main__":
    main()