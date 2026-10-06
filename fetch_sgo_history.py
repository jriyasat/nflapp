#!/usr/bin/env python
"""
Fetch historical SGO events with results and open/close odds.
Produces a team-week CSV with yards per play differential and other stats.
Usage: python fetch_sgo_history.py [start_date] [output_csv]
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl

def fetch_historical(start_date='2024-01-01', api_key=None):
    """Fetch all events from start_date onward."""
    if api_key is None:
        api_key = dl.sgo_api_key()
        if not api_key:
            raise ValueError('SGO API key not found in env, secrets, or data/sgo_api_key.txt')
    
    SGO_EVENTS = dl.SGO_EVENTS  # from data module
    CACHE = dl.CACHE
    
    all_events = []
    offset = 0
    limit = 200  # max per request
    
    # Set time window: start_date up to now
    starts_after = start_date + "T00:00:00Z"
    starts_before = pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    
    while True:
        # Use data._get_json with caching (1440 minutes = 24h)
        data = dl._get_json(SGO_EVENTS, f"sgo_historical_{start_date.replace('-','')}.json",
                            1440, params={
                                "leagueID": "NFL",
                                "startsAfter": starts_after,
                                "startsBefore": starts_before,
                                "bookmakerID": dl.SGO_BOOKS,
                                "limit": limit,
                                "offset": offset
                            }, extra_headers={"x-api-key": api_key})
        events = data.get("data", [])
        if not events:
            break
        all_events.extend(events)
        offset += len(events)
        if len(events) < limit:
            break
        print(f"Fetched {offset} events...")
    
    print(f"Total events: {len(all_events)}")
    
    team_rows = []
    for e in all_events:
        if "results" not in e:
            continue
        results = e.get("results")
        if not isinstance(results, dict):
            continue
        game = results.get("game")
        if not isinstance(game, dict):
            continue
        
        # Determine season and week
        starts_at = (e.get("status") or {}).get("startsAt")
        if starts_at:
            try:
                dt = pd.to_datetime(starts_at)
                season = dt.year
            except Exception:
                season = None
        else:
            season = None
        
        # Parse week from info.seasonWeek
        season_week = (e.get("info") or {}).get("seasonWeek", "")
        week = None
        if season_week and "Week" in season_week:
            import re
            m = re.search(r'Week\s+(\d+)', season_week)
            if m:
                week = int(m.group(1))
        
        # Determine home/away team names
        teams = e.get("teams", {})
        home_name = teams.get("home", {}).get("names", {}).get("short", "")
        away_name = teams.get("away", {}).get("names", {}).get("short", "")
        
        home_stats = game.get("home", {})
        away_stats = game.get("away", {})
        
        # Process home team
        off_yards = home_stats.get("yards", 0)
        off_plays = home_stats.get("offense_plays", 0)
        def_yards = away_stats.get("yards", 0)
        def_plays = away_stats.get("offense_plays", 0)
        off_ypp = off_yards / off_plays if off_plays > 0 else 0.0
        def_ypp = def_yards / def_plays if def_plays > 0 else 0.0
        net_ypp = off_ypp - def_ypp
        
        row_home = {
            "season": season,
            "week": week,
            "team": "home",
            "team_name": home_name,
            "opponent": "away",
            "opponent_name": away_name,
            "points": home_stats.get("points", 0),
            "yards": off_yards,
            "plays": off_plays,
            "turnovers": home_stats.get("turnovers", 0),
            "firstDowns": home_stats.get("firstDowns", 0),
            "thirdDownConversions": home_stats.get("offense_thirdDownConversions", 0),
            "thirdDowns": home_stats.get("offense_thirdDownAttempts", 0),
            "redZoneTrips": home_stats.get("offense_redZoneTrips", 0),
            "redZoneTouchdowns": home_stats.get("offense_redZoneTouchdowns", 0),
            "off_ypp": off_ypp,
            "def_ypp": def_ypp,
            "net_ypp": net_ypp,
            "eventID": e.get("eventID"),
        }
        team_rows.append(row_home)
        
        # Process away team
        off_yards = away_stats.get("yards", 0)
        off_plays = away_stats.get("offense_plays", 0)
        def_yards = home_stats.get("yards", 0)
        def_plays = home_stats.get("offense_plays", 0)
        off_ypp = off_yards / off_plays if off_plays > 0 else 0.0
        def_ypp = def_yards / def_plays if def_plays > 0 else 0.0
        net_ypp = off_ypp - def_ypp
        
        row_away = {
            "season": season,
            "week": week,
            "team": "away",
            "team_name": away_name,
            "opponent": "home",
            "opponent_name": home_name,
            "points": away_stats.get("points", 0),
            "yards": off_yards,
            "plays": off_plays,
            "turnovers": away_stats.get("turnovers", 0),
            "firstDowns": away_stats.get("firstDowns", 0),
            "thirdDownConversions": away_stats.get("offense_thirdDownConversions", 0),
            "thirdDowns": away_stats.get("offense_thirdDownAttempts", 0),
            "redZoneTrips": away_stats.get("offense_redZoneTrips", 0),
            "redZoneTouchdowns": away_stats.get("offense_redZoneTouchdowns", 0),
            "off_ypp": off_ypp,
            "def_ypp": def_ypp,
            "net_ypp": net_ypp,
            "eventID": e.get("eventID"),
        }
        team_rows.append(row_away)
    
    df = pd.DataFrame(team_rows)
    return df

if __name__ == "__main__":
    start_date = sys.argv[1] if len(sys.argv) > 1 else "2024-01-01"
    output_csv = sys.argv[2] if len(sys.argv) > 2 else f"sgo_historical_{start_date.replace('-','')}.csv"
    output_path = os.path.join(os.path.dirname(dl.__file__), "data", output_csv)
    
    print(f"Fetching SGO historical results from {start_date}...")
    try:
        df = fetch_historical(start_date)
        df.to_csv(output_path, index=False)
        print(f"Saved {len(df)} rows to {output_path}")
        print(df.head())
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)