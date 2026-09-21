"""
Yards‑Per‑Play (YPP) differential model for NFL spread prediction.
Replaces the Elo component in the 85/15 blend with a linear regression
fitted on historical SGO results (net YPP differential vs closing spread).
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import db

class YPPModel:
    def __init__(self, coeff_path=None):
        """
        Load regression coefficients from JSON file (created by fit_ypp_model.py).
        Expected keys: 'alpha' (intercept), 'beta' (coefficient).
        """
        if coeff_path is None:
            coeff_path = os.path.join(
                os.path.dirname(__file__),
                "data", "model_fits", "ypp_coefficients.json"
            )
        with open(coeff_path, 'r') as f:
            coeff = json.load(f)
        self.alpha = coeff.get('alpha', 0.0)
        self.beta = coeff.get('beta', 0.0)  # coefficient for YPP diff
        self.r_squared = coeff.get('r_squared', 0.0)
        self.training_n = coeff.get('sample_size', 0)
        
    def _load_team_stats(self):
        """
        Load team stats from shared_cache table 'sgo_team_stats'.
        Returns a pandas DataFrame with columns including 'team', 'net_ypp', 'date'.
        If cache empty, returns empty DataFrame.
        """
        raw, _ = db.cache_get('sgo_team_stats')
        if raw is None:
            return pd.DataFrame()
        try:
            rows = json.loads(raw)
        except Exception:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        # Ensure date column
        if 'date' not in df.columns and 'start_date' in df.columns:
            df['date'] = pd.to_datetime(df['start_date']).dt.date
        elif 'startsAt' in df.columns:
            df['date'] = pd.to_datetime(df['startsAt']).dt.date
        # Compute net_ypp if missing
        if 'net_ypp' not in df.columns:
            if all(col in df.columns for col in ['off_ypp', 'def_ypp']):
                df['net_ypp'] = df['off_ypp'] - df['def_ypp']
            elif all(col in df.columns for col in ['off_yards', 'off_plays', 'def_yards_allowed', 'def_plays']):
                df['off_ypp'] = df['off_yards'] / df['off_plays'].replace(0, np.nan)
                df['def_ypp'] = df['def_yards_allowed'] / df['def_plays'].replace(0, np.nan)
                df['net_ypp'] = df['off_ypp'] - df['def_ypp']
            else:
                # Cannot compute net_ypp
                df['net_ypp'] = 0.0
        return df
    
    def get_team_ypp_stats(self, team, date=None):
        """
        Retrieve YPP differential (net_ypp = off_ypp - def_ypp_allowed) for a team
        up to a given date (exclusive), using a rolling window of the last 4 games.
        
        Returns: (net_ypp_avg, game_count) where net_ypp_avg is the average
        net YPP over the last 4 eligible games (or fewer if insufficient data).
        """
        df = self._load_team_stats()
        if df.empty:
            return 0.0, 0
        
        # Filter for team and games before date (if date provided)
        mask = df['team'] == team.upper()
        if date is not None:
            if 'date' in df.columns:
                mask &= df['date'] < pd.to_datetime(date)
        team_df = df[mask].sort_values('date', ascending=False).head(4)
        
        if team_df.empty:
            return 0.0, 0
        
        avg_net_ypp = team_df['net_ypp'].mean()
        return avg_net_ypp, len(team_df)
    
    def predict_spread(self, away_team, home_team, date=None):
        """
        Predict point spread (home team advantage) based on YPP differential model.
        Returns: predicted spread from home perspective (positive = home favored).
        """
        away_net, away_n = self.get_team_ypp_stats(away_team, date)
        home_net, home_n = self.get_team_ypp_stats(home_team, date)
        
        # If insufficient data for either team, fallback to neutral (0)
        if away_n == 0 or home_n == 0:
            # Use league-average net_ypp (approx 0) as fallback
            ypp_diff = 0.0
        else:
            ypp_diff = home_net - away_net
        
        spread = self.alpha + self.beta * ypp_diff
        return spread
    
    def predict_proba(self, away_team, home_team, date=None):
        """
        Predict probability of home team covering a hypothetical spread
        (not yet implemented; placeholder).
        """
        spread = self.predict_spread(away_team, home_team, date)
        # map spread to probability via logistic curve (reuse Elo parameters)
        # For now return 0.5
        return 0.5