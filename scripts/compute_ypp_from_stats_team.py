#!/usr/bin/env python
"""
Compute YPP differential per team-week from nflverse stats_team CSV.
Output stored in Turso shared_cache as 'team_ypp_history' (JSON array).
Works offline with cached stats_team CSV files.
"""
import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl
import db

def download_stats_team(year):
    """Download stats_team CSV for a season, save locally."""
    cache_dir = dl.CACHE
    os.makedirs(cache_dir, exist_ok=True)
    local_path = os.path.join(cache_dir, f'stats_team_{year}.csv')
    # If file exists and fresh (less than 7 days), reuse
    if os.path.exists(local_path):
        mod_time = os.path.getmtime(local_path)
        if datetime.now().timestamp() - mod_time < 7 * 86400:
            print(f'Using cached stats_team_{year}.csv')
            return local_path
    # Download from nflverse releases
    url = f'https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{year}.csv'
    print(f'Downloading stats_team {year}...')
    try:
        import urllib.request
        req = urllib.request.urlopen(url, timeout=60)
        content = req.read()
        with open(local_path, 'wb') as f:
            f.write(content)
        print(f'Downloaded {len(content)} bytes')
    except Exception as e:
        print(f'Download failed for {year}: {e}')
        return None
    return local_path

def compute_ypp_for_season(year):
    """Aggregate yards/plays per team-week from stats_team CSV."""
    csv_path = download_stats_team(year)
    if csv_path is None:
        return pd.DataFrame()
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f'Failed to read CSV {csv_path}: {e}')
        return pd.DataFrame()
    # Ensure required columns
    required = ['season', 'week', 'team', 'opponent_team', 'passing_yards', 'rushing_yards', 'attempts', 'carries']
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f'Missing columns {missing} in stats_team CSV')
        return pd.DataFrame()
    # Compute offensive yards and plays
    df['off_yards'] = df['passing_yards'] + df['rushing_yards']
    df['off_plays'] = df['attempts'] + df['carries']
    # Need opponent's offensive stats to compute defensive yards allowed
    # Merge with self on opponent_team to get opponent's offensive stats
    opp = df[['season', 'week', 'team', 'off_yards', 'off_plays']].copy()
    opp = opp.rename(columns={'team': 'opponent_team', 'off_yards': 'def_yards_allowed', 'off_plays': 'def_plays'})
    merged = pd.merge(df, opp, on=['season', 'week', 'opponent_team'], how='left')
    # Compute YPP
    merged['off_ypp'] = merged['off_yards'] / merged['off_plays'].replace(0, np.nan)
    merged['def_ypp'] = merged['def_yards_allowed'] / merged['def_plays'].replace(0, np.nan)
    merged['net_ypp'] = merged['off_ypp'] - merged['def_ypp']
    # Convert team abbreviations to uppercase, replace LA with LAR
    merged['team'] = merged['team'].str.upper().replace({'LA': 'LAR'})
    merged['opponent'] = merged['opponent_team'].str.upper().replace({'LA': 'LAR'})
    # Load games.csv to add game date
    games = dl.load_games()
    games['game_date'] = pd.to_datetime(games['gameday'])
    home = games[['season', 'week', 'home_team', 'game_date']].copy()
    home.rename(columns={'home_team': 'team'}, inplace=True)
    away = games[['season', 'week', 'away_team', 'game_date']].copy()
    away.rename(columns={'away_team': 'team'}, inplace=True)
    date_map = pd.concat([home, away], ignore_index=True).drop_duplicates(subset=['season', 'week', 'team'], keep='first')
    date_map['team'] = date_map['team'].str.upper().replace({'LA': 'LAR'})
    merged = merged.merge(date_map, on=['season', 'week', 'team'], how='left')
    merged['date'] = merged['game_date'].dt.date  # Python date object for JSON
    # Keep essential columns
    result = merged[[
        'season', 'week', 'team', 'opponent', 'off_yards', 'off_plays',
        'def_yards_allowed', 'def_plays', 'off_ypp', 'def_ypp', 'net_ypp', 'date'
    ]]
    print(f'Computed YPP for {year}: {len(result)} team-game rows')
    return result

def main(years=(2020, 2021, 2022,7141999, 2024)):
    """Compute YPP history for given years and upload to shared_cache."""
    all_rows = []
    for yr in years:
        df = compute_ypp_for_season(yr)
        if not df.empty:
            all_rows.append(df)
    if not all_rows:
        print('No data computed.')
        return
    full = pd.concat(all_rows, ignore_index=True)
    # Convert NaN to None for JSON serialization
    records = full.replace({np.nan: None}).to_dict(orient='records')
    for r in records:
        if r.get('date'):
            r['date'] = r['date'].isoformat()
    # Upload to shared_cache
    raw = json.dumps(records)
    db.cache_set('team_ypp_history', raw)
    print(f'Uploaded {len(records)} team-game rows to shared_cache \'team_ypp_history\'')
    # Also save local backup
    backup_path = os.path.join(dl.CACHE, 'team_ypp_history.json')
    with open(backup_path, 'w') as f:
        json.dump(records, f, indent=2)
    print(f'Local backup saved to {backup_path}')
    # Print sample
    print('\nSample row:')
    print(json.dumps(records[0], indent=2))

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--years', nargs='+', type=int, default=[2020, 2021, 2022, 2023, 2024],
                        help='Seasons to compute (default 2020-2024)')
    args = parser.parse_args()
    main(tuple(args.years))