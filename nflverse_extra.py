"""
Real nflverse_extra module loading snap data from agg_snap CSV files.
Provides load_snaps() returning DataFrame with columns expected by backtest_props_v2.py.
"""

import pandas as pd
import os
import re

def _normalize_name(name):
    """Normalize player display name: lower-case, strip punctuation, spaces to underscores."""
    if not isinstance(name, str):
        return ''
    # remove suffixes like Jr., III, etc.
    cleaned = re.sub(r'\s+([JS]r\.|I{2,3}|IV|V)$', '', name)
    # lower case, replace non-alphanumeric with underscore, collapse multiple underscores
    normalized = re.sub(r'[^a-z0-9]+', '_', cleaned.lower())
    return normalized.strip('_')

def load_snaps(years=None):
    """Return aggregated snap data for given years (list or range)."""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    files = [f for f in os.listdir(data_dir) if f.startswith('agg_snap_') and f.endswith('.csv')]
    if not files:
        # fallback to empty DataFrame with expected columns
        columns = ['player_id', 'player_display_name', 'position', 'team', 'season', 'week',
                   'offense_snaps', 'offense_pct', 'defense_snaps', 'defense_pct',
                   'special_teams_snaps', 'special_teams_pct']
        return pd.DataFrame(columns=columns)
    
    dfs = []
    for f in files:
        # extract year from filename agg_snap_2022.csv
        try:
            year = int(f.split('_')[2].split('.')[0])
        except:
            continue
        if years is not None and year not in years:
            continue
        path = os.path.join(data_dir, f)
        try:
            df = pd.read_csv(path)
            df['season'] = year
            dfs.append(df)
        except Exception as e:
            print(f"Warning: could not read {path}: {e}")
    
    if not dfs:
        columns = ['player_id', 'player_display_name', 'position', 'team', 'season', 'week',
                   'offense_snaps', 'offense_pct', 'defense_snaps', 'defense_pct',
                   'special_teams_snaps', 'special_teams_pct']
        return pd.DataFrame(columns=columns)
    
    combined = pd.concat(dfs, ignore_index=True)
    # add norm_name column for merging
    combined['norm_name'] = combined['player_display_name'].apply(_normalize_name)
    # rename columns to match backtest expectations
    # backtest expects 'snap_counts' and 'snap_pct'? Not used; we'll keep offense_snaps and offense_pct
    # Ensure we have required columns
    required = ['player_id', 'player_display_name', 'position', 'team', 'season', 'week',
                'offense_snaps', 'offense_pct', 'defense_snaps', 'defense_pct',
                'special_teams_snaps', 'special_teams_pct', 'norm_name']
    for col in required:
        if col not in combined.columns:
            combined[col] = None
    
    return combined[required]

# Keep other stub functions for compatibility
def load_other_data():
    raise NotImplementedError("nflverse_extra currently only provides load_snaps")