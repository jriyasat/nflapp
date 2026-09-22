"""
nflverse extra datasets — Phase 0 foundation for V2.

Six loaders that fetch and cache aggregated summaries from nflverse-data releases.
Each loader returns a pandas DataFrame ready for model consumption.

Pattern:
- Raw files downloaded to CACHE/{raw_*}, aggregated summaries to CACHE/{agg_*}.
- Caching respects 12h TTL (same as games.csv).
- In‑process memoization by file mtime.
- Raw files are kept (optional deletion on aggregation).
"""

import os
import time
import warnings
import pandas as pd
import requests

# Reuse data layer utilities
import data as dl

CACHE = dl.CACHE
os.makedirs(CACHE, exist_ok=True)

def _fresh(path, max_age_sec):
    """Adapt data._fresh."""
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_sec

def _download_raw(url, raw_path):
    """Download raw file atomically."""
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    tmp = raw_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(r.content)
    os.replace(tmp, raw_path)

# ----------------------------------------------------------------------
# 1. Team EPA (play‑by‑play aggregated to weekly team off/def EPA/play)
# ----------------------------------------------------------------------

PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{year}.parquet"
PBP_CACHE_H = 12

def load_team_epa(years=None):
    """
    Weekly team off/def EPA per play, success rate, PROE, pace.
    
    Returns DataFrame indexed by (season, week, team) with columns:
        off_epa_play, def_epa_play, success_rate, proe (pass_rate_over_expected),
        plays_per_game, pace (seconds_per_play)
    """
    if years is None:
        # default: current and previous season
        games = dl.load_games()
        cur = int(games.loc[games["result"].isna(), "season"].max())
        years = [cur - 1, cur]
    
    frames = []
    for yr in years:
        raw_path = os.path.join(CACHE, f"raw_pbp_{yr}.parquet")
        agg_path = os.path.join(CACHE, f"agg_team_epa_{yr}.csv")
        
        # download raw if stale
        if not _fresh(raw_path, PBP_CACHE_H * 3600):
            try:
                _download_raw(PBP_URL.format(year=yr), raw_path)
            except Exception as e:
                warnings.warn(f"Could not download PBP {yr}: {e}")
                continue
        
        # load aggregated cache if fresh
        if _fresh(agg_path, PBP_CACHE_H * 3600):
            df = pd.read_csv(agg_path)
            frames.append(df)
            continue
        
        # aggregate raw file
        try:
            raw = pd.read_parquet(raw_path)
        except Exception as e:
            warnings.warn(f"Could not read PBP {yr}: {e}")
            continue
        
        # Filter regular season, has EPA
        reg = raw[(raw.season_type == "REG") & raw.epa.notna()].copy()
        if reg.empty:
            continue
        
        # Group by game-team
        # TODO: implement actual EPA aggregation (sum EPA per game side)
        # Placeholder: return minimal columns
        agg = reg.groupby(["season", "week", "posteam"]).agg(
            plays=("play_id", "count"),
            off_epa_total=("epa", "sum"),
            off_success=("success", "mean")
        ).reset_index()
        agg.rename(columns={"posteam": "team"}, inplace=True)
        agg["off_epa_play"] = agg.off_epa_total / agg.plays
        agg["def_epa_play"] = 0.0   # need defense EPA from defteam
        agg["success_rate"] = agg.off_success
        agg["proe"] = 0.0
        agg["pace"] = 0.0
        
        # Keep essential columns
        agg = agg[["season", "week", "team", "off_epa_play", "def_epa_play",
                  "success_rate", "proe", "pace"]]
        agg.to_csv(agg_path, index=False)
        frames.append(agg)
    
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # Normalize Rams abbreviation
    df["team"] = df["team"].replace({"LA": "LAR"})
    return df

# ----------------------------------------------------------------------
# 2. Snap counts
# ----------------------------------------------------------------------

SNAP_URL = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{year}.csv"
SNAP_CACHE_H = 12

def load_snaps(years=None):
    """
    Player‑week snap counts + snap share.
    
    Returns DataFrame columns:
        player_id, player_display_name, position, team, season, week,
        offense_snaps, offense_pct, defense_snaps, defense_pct, special_teams_snaps, special_teams_pct
    """
    if years is None:
        games = dl.load_games()
        cur = int(games.loc[games["result"].isna(), "season"].max())
        years = [cur - 1, cur]
    
    frames = []
    for yr in years:
        raw_path = os.path.join(CACHE, f"raw_snap_{yr}.csv")
        agg_path = os.path.join(CACHE, f"agg_snap_{yr}.csv")
        
        if not _fresh(raw_path, SNAP_CACHE_H * 3600):
            try:
                _download_raw(SNAP_URL.format(year=yr), raw_path)
            except Exception as e:
                warnings.warn(f"Could not download snap counts {yr}: {e}")
                continue
        
        if _fresh(agg_path, SNAP_CACHE_H * 3600):
            df = pd.read_csv(agg_path)
            frames.append(df)
            continue
        
        raw = pd.read_csv(raw_path, low_memory=False)
        # Map columns
        raw.rename(columns={
            "player": "player_display_name",
            "pfr_player_id": "player_id",
            "st_snaps": "special_teams_snaps",
            "st_pct": "special_teams_pct"
        }, inplace=True)
        # Ensure required columns exist
        required = ["player_id", "player_display_name", "position", "team", "season", "week",
                    "offense_snaps", "offense_pct", "defense_snaps", "defense_pct",
                    "special_teams_snaps", "special_teams_pct"]
        missing = [c for c in required if c not in raw.columns]
        if missing:
            warnings.warn(f"Snap counts {yr} missing columns {missing}")
            continue
        
        agg = raw[required].copy()
        agg["team"] = agg["team"].replace({"LA": "LAR"})
        agg.to_csv(agg_path, index=False)
        frames.append(agg)
    
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df

# ----------------------------------------------------------------------
# 3. Next Gen Stats
# ----------------------------------------------------------------------

NGS_URLS = {
    "passing": "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{year}_passing.csv",
    "rushing": "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{year}_rushing.csv",
    "receiving": "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{year}_receiving.csv",
}
NGS_CACHE_H = 12

def load_ngs(years=None, stat_type="passing"):
    """
    NGS metrics for a given stat type (passing, rushing, receiving).
    
    Returns DataFrame with columns depending on type:
        player_id, player_display_name, team, season, week,
        ryoe (rush yards over expected), separation, cushion, time_to_throw, etc.
    """
    if years is None:
        games = dl.load_games()
        cur = int(games.loc[games["result"].isna(), "season"].max())
        years = [cur - 1, cur]
    
    if stat_type not in NGS_URLS:
        raise ValueError(f"stat_type must be one of {list(NGS_URLS.keys())}")
    
    frames = []
    for yr in years:
        raw_path = os.path.join(CACHE, f"raw_ngs_{stat_type}_{yr}.csv")
        agg_path = os.path.join(CACHE, f"agg_ngs_{stat_type}_{yr}.csv")
        
        if not _fresh(raw_path, NGS_CACHE_H * 3600):
            try:
                _download_raw(NGS_URLS[stat_type].format(year=yr), raw_path)
            except Exception as e:
                warnings.warn(f"Could not download NGS {stat_type} {yr}: {e}")
                continue
        
        if _fresh(agg_path, NGS_CACHE_H * 3600):
            df = pd.read_csv(agg_path)
            frames.append(df)
            continue
        
        raw = pd.read_csv(raw_path, low_memory=False)
        # Keep core columns
        keep = ["player_id", "player_display_name", "team", "season", "week"]
        if stat_type == "rushing":
            keep.append("ryoe")
        elif stat_type == "receiving":
            keep.extend(["separation", "cushion"])
        elif stat_type == "passing":
            keep.append("time_to_throw")
        
        missing = [c for c in keep if c not in raw.columns]
        if missing:
            warnings.warn(f"NGS {stat_type} {yr} missing columns {missing}")
            continue
        
        agg = raw[keep].copy()
        agg["team"] = agg["team"].replace({"LA": "LAR"})
        agg.to_csv(agg_path, index=False)
        frames.append(agg)
    
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df

# ----------------------------------------------------------------------
# 4. ESPN QBR grades
# ----------------------------------------------------------------------

QBR_URL = "https://github.com/nflverse/nflverse-data/releases/download/espn_qbr/qbr_week_level.csv"
QBR_CACHE_H = 24  # rate limit: 1/day maybe; use 24h cache

def load_qbr():
    """
    QB week‑level QBR grades.
    
    Returns DataFrame columns:
        player_id, player_name, team, season, week, qbr_total, qbr_raw, qbr_clutch
    """
    raw_path = os.path.join(CACHE, "raw_qbr.csv")
    agg_path = os.path.join(CACHE, "agg_qbr.csv")
    
    if not _fresh(raw_path, QBR_CACHE_H * 3600):
        try:
            _download_raw(QBR_URL, raw_path)
        except Exception as e:
            warnings.warn(f"Could not download QBR: {e}")
            return pd.DataFrame()
    
    if _fresh(agg_path, QBR_CACHE_H * 3600):
        return pd.read_csv(agg_path)
    
    raw = pd.read_csv(raw_path, low_memory=False)
    # Select columns
    cols = ["player_id", "player_name", "team_abbr", "season", "week",
            "qbr_total", "qbr_raw", "qbr_clutch"]
    missing = [c for c in cols if c not in raw.columns]
    if missing:
        warnings.warn(f"QBR missing columns {missing}")
        return pd.DataFrame()
    
    agg = raw[cols].copy()
    agg.rename(columns={"team_abbr": "team", "player_name": "player_display_name"}, inplace=True)
    agg["team"] = agg["team"].replace({"LA": "LAR"})
    agg.to_csv(agg_path, index=False)
    return agg

# ----------------------------------------------------------------------
# 5. FTN charting
# ----------------------------------------------------------------------

FTN_URL = "https://github.com/nflverse/nflverse-data/releases/download/ftn_charting/ftn_charting_{year}.csv"
FTN_CACHE_H = 12

def load_ftn(years=None):
    """
    FTN charting data: pressures, drops, adjusted INTs.
    
    Returns DataFrame columns:
        player_id, player_name, team, season, week,
        pressures, sacks, hits, hurries, drops, adj_ints
    """
    if years is None:
        games = dl.load_games()
        cur = int(games.loc[games["result"].isna(), "season"].max())
        years = [cur - 1, cur]
    
    frames = []
    for yr in years:
        raw_path = os.path.join(CACHE, f"raw_ftn_{yr}.csv")
        agg_path = os.path.join(CACHE, f"agg_ftn_{yr}.csv")
        
        if not _fresh(raw_path, FTN_CACHE_H * 3600):
            try:
                _download_raw(FTN_URL.format(year=yr), raw_path)
            except Exception as e:
                warnings.warn(f"Could not download FTN {yr}: {e}")
                continue
        
        if _fresh(agg_path, FTN_CACHE_H * 3600):
            df = pd.read_csv(agg_path)
            frames.append(df)
            continue
        
        raw = pd.read_csv(raw_path, low_memory=False)
        keep = ["player_id", "player_name", "team", "season", "week",
                "pressures", "sacks", "hits", "hurries", "drops", "adj_ints"]
        missing = [c for c in keep if c not in raw.columns]
        if missing:
            warnings.warn(f"FTN {yr} missing columns {missing}")
            continue
        
        agg = raw[keep].copy()
        agg.rename(columns={"player_name": "player_display_name"}, inplace=True)
        agg["team"] = agg["team"].replace({"LA": "LAR"})
        agg.to_csv(agg_path, index=False)
        frames.append(agg)
    
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df

# ----------------------------------------------------------------------
# 6. Depth charts
# ----------------------------------------------------------------------

DEPTH_URL = "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{year}.csv"
DEPTH_CACHE_H = 12

def load_depth_charts(years=None):
    """
    Official starter lists by team/position.
    
    Returns DataFrame columns:
        team, season, week, position, player_id, player_display_name, depth_team, order
    """
    if years is None:
        games = dl.load_games()
        cur = int(games.loc[games["result"].isna(), "season"].max())
        years = [cur - 1, cur]
    
    frames = []
    for yr in years:
        raw_path = os.path.join(CACHE, f"raw_depth_{yr}.csv")
        agg_path = os.path.join(CACHE, f"agg_depth_{yr}.csv")
        
        if not _fresh(raw_path, DEPTH_CACHE_H * 3600):
            try:
                _download_raw(DEPTH_URL.format(year=yr), raw_path)
            except Exception as e:
                warnings.warn(f"Could not download depth charts {yr}: {e}")
                continue
        
        if _fresh(agg_path, DEPTH_CACHE_H * 3600):
            df = pd.read_csv(agg_path)
            frames.append(df)
            continue
        
        raw = pd.read_csv(raw_path, low_memory=False)
        # Map columns
        raw.rename(columns={
            "club_code": "team",
            "gsis_id": "player_id",
            "full_name": "player_display_name",
            "depth_position": "order"
        }, inplace=True)
        # Ensure required columns exist
        required = ["team", "season", "week", "position", "player_id", "player_display_name", "depth_team", "order"]
        missing = [c for c in required if c not in raw.columns]
        if missing:
            warnings.warn(f"Depth charts {yr} missing columns {missing}")
            continue
        
        agg = raw[required].copy()
        agg["team"] = agg["team"].replace({"LA": "LAR"})
        agg.to_csv(agg_path, index=False)
        frames.append(agg)
    
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df