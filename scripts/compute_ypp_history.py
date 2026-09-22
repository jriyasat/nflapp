#!/usr/bin/env python
"""
Compute YPP (yards per play) differential per team‑week from nflverse play‑by‑play.
Output stored in Turso shared_cache as 'team_ypp_history' (JSON array) for YPP model fallback.
"""

import os
import sys
import json
import time
import pandas as pd
import numpy as np
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl
import db
import nflverse_extra as nve

def compute_ypp_for_season(year):
    """Aggregate yards/plays per team‑week for a single season."""
    raw_path = os.path.join(dl.CACHE, f"raw_pbp_{year}.parquet")
    agg_path = os.path.join(dl.CACHE, f"agg_ypp_{year}.csv")
    
    # Download raw if stale
    if not nve._fresh(raw_path, nve.PBP_CACHE_H * 3600):
        print(f"Downloading PBP {year}...")
        try:
            nve._download_raw(nve.PBP_URL.format(year=year), raw_path)
        except Exception as e:
            print(f"Download failed for {year}: {e}")
            return pd.DataFrame()
    else:
        print(f"Using cached PBP {year}")
    
    # Load raw parquet
    try:
        raw = pd.read_parquet(raw_path)
    except Exception as e:
        print(f"Failed to read PBP {year}: {e}")
        return pd.DataFrame()
    
    # Filter regular season, drop plays with missing yards/play info
    # Keep only offensive plays (pass, run, qb_kneel, qb_spike, sack) with yards_gained
    reg = raw[
        (raw.season_type == "REG") &
        raw.yards_gained.notna() &
        raw.play_type.isin(["pass", "run", "qb_kneel", "qb_spike", "sack"])
    ].copy()
    if reg.empty:
        print(f"No regular season plays for {year}")
        return pd.DataFrame()
    
    # Ensure team abbreviations are strings
    reg["posteam"] = reg["posteam"].astype(str)
    reg["defteam"] = reg["defteam"].astype(str)
    
    # Group by game‑team (posteam) vs opponent (defteam)
    # Offensive stats: yards gained, number of plays
    off = reg.groupby(["season", "week", "posteam", "defteam"]).agg(
        off_yards=("yards_gained", "sum"),
        off_plays=("play_id", "count")
    ).reset_index()
    off.rename(columns={"posteam": "team", "defteam": "opponent"}, inplace=True)
    
    # Defensive stats: yards allowed, number of plays defended
    def_ = reg.groupby(["season", "week", "defteam", "posteam"]).agg(
        def_yards_allowed=("yards_gained", "sum"),
        def_plays=("play_id", "count")
    ).reset_index()
    def_.rename(columns={"defteam": "team", "posteam": "opponent"}, inplace=True)
    
    # Merge offensive and defensive stats
    merged = pd.merge(off, def_, on=["season", "week", "team", "opponent"], how="outer").fillna(0)
    
    # Compute YPP (avoid division by zero)
    merged["off_ypp"] = merged.off_yards / merged.off_plays.replace(0, np.nan)
    merged["def_ypp"] = merged.def_yards_allowed / merged.def_plays.replace(0, np.nan)
    merged["net_ypp"] = merged.off_ypp - merged.def_ypp
    
    # Replace LA with LAR (consistent with nflverse_extra)
    merged["team"] = merged["team"].str.upper().replace({"LA": "LAR"})
    merged["opponent"] = merged["opponent"].str.upper().replace({"LA": "LAR"})
    
    # Load games.csv to add game date
    games = dl.load_games()
    games["game_date"] = pd.to_datetime(games["gameday"])
    # Map team abbreviation (home_team/away_team) to game date
    # We'll create a mapping from (season, week, team) to date
    home = games[["season", "week", "home_team", "game_date"]].copy()
    home.rename(columns={"home_team": "team"}, inplace=True)
    away = games[["season", "week", "away_team", "game_date"]].copy()
    away.rename(columns={"away_team": "team"}, inplace=True)
    date_map = pd.concat([home, away], ignore_index=True).drop_duplicates(
        subset=["season", "week", "team"], keep="first"
    )
    date_map["team"] = date_map["team"].str.upper().replace({"LA": "LAR"})
    
    merged = merged.merge(date_map, on=["season", "week", "team"], how="left")
    merged["date"] = merged["game_date"].dt.date  # Python date object for JSON
    
    # Keep essential columns
    merged = merged[[
        "season", "week", "team", "opponent",
        "off_yards", "off_plays", "def_yards_allowed", "def_plays",
        "off_ypp", "def_ypp", "net_ypp", "date"
    ]]
    
    # Save aggregated CSV for caching
    merged.to_csv(agg_path, index=False)
    print(f"Computed YPP for {year}: {len(merged)} team‑game rows")
    return merged

def main(years=(2022, 2023, 2024)):
    """Compute YPP history for given years and upload to Turso shared_cache."""
    import glob
    
    all_rows = []
    for yr in years:
        df = compute_ypp_for_season(yr)
        if not df.empty:
            all_rows.append(df)
    
    if not all_rows:
        print("No data computed.")
        return
    
    full = pd.concat(all_rows, ignore_index=True)
    
    # Convert NaN to None for JSON serialization
    records = full.replace({np.nan: None}).to_dict(orient="records")
    # Convert date to ISO string
    for r in records:
        if r.get("date"):
            r["date"] = r["date"].isoformat()
    
    # Upload to Turso shared_cache
    raw = json.dumps(records)
    db.cache_set("team_ypp_history", raw)
    print(f"Uploaded {len(records)} team‑game rows to shared_cache 'team_ypp_history'")
    
    # Also save local backup
    backup_path = os.path.join(dl.CACHE, "team_ypp_history.json")
    with open(backup_path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"Local backup saved to {backup_path}")
    
    # Print sample
    print("\nSample row:")
    print(json.dumps(records[0], indent=2))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024],
                        help="Seasons to compute (default 2022‑2024)")
    args = parser.parse_args()
    main(tuple(args.years))