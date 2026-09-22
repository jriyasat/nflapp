#!/usr/bin/env python
"""
Fit YPP model using team_ypp_history (nflverse PBP aggregated) and games.csv spreads.
Saves coefficients to data/model_fits/ypp_coefficients.json.
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import TimeSeriesSplit
import matplotlib.pyplot as plt

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl
import db

def load_team_ypp_history():
    """Load team_ypp_history from Turso shared_cache."""
    raw, _ = db.cache_get('team_ypp_history')
    if raw is None:
        raise ValueError("team_ypp_history not found in shared_cache")
    rows = json.loads(raw)
    df = pd.DataFrame(rows)
    # Ensure numeric columns
    num_cols = ['season', 'week', 'off_yards', 'off_plays', 'def_yards_allowed', 'def_plays',
                'off_ypp', 'def_ypp', 'net_ypp']
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    # Convert date string to date
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date']).dt.date
    return df

def load_nflverse_games():
    """Load nflverse games.csv (cached)."""
    games_path = os.path.join(os.path.dirname(dl.__file__), "data", "games.csv")
    df = pd.read_csv(games_path)
    # Keep relevant columns
    cols = ['season', 'week', 'home_team', 'away_team', 'spread_line', 'total_line',
            'result', 'home_score', 'away_score', 'game_id']
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f'Missing columns in games.csv: {missing}')
    return df[cols]

def merge_ypp_games(ypp_df, games_df):
    """
    Merge team_ypp_history with games.csv.
    ypp_df has one row per team-game (team vs opponent).
    We need to pivot to get home/away net_ypp per game.
    """
    # Ensure team abbreviations match (already uppercase)
    ypp_df['team'] = ypp_df['team'].str.upper()
    ypp_df['opponent'] = ypp_df['opponent'].str.upper()
    
    # Split into home and away stats
    # We'll join games_df with ypp_df on season, week, home_team = team (home perspective)
    # and away_team = opponent (away perspective)
    # But we need net_ypp for home team (team) and away team (opponent)
    # So we can create two temporary DataFrames: home_stats and away_stats.
    home_stats = ypp_df.rename(columns={'team': 'home_team', 'opponent': 'away_team', 'net_ypp': 'home_net_ypp'})
    away_stats = ypp_df.rename(columns={'team': 'away_team', 'opponent': 'home_team', 'net_ypp': 'away_net_ypp'})
    
    # Merge games with home_stats
    merged = pd.merge(games_df,
                      home_stats[['season', 'week', 'home_team', 'away_team', 'home_net_ypp']],
                      on=['season', 'week', 'home_team', 'away_team'],
                      how='inner')
    # Merge again with away_stats to get away_net_ypp
    merged = pd.merge(merged,
                      away_stats[['season', 'week', 'home_team', 'away_team', 'away_net_ypp']],
                      on=['season', 'week', 'home_team', 'away_team'],
                      how='inner')
    
    # Drop duplicates (if any)
    merged = merged.drop_duplicates(subset=['season', 'week', 'home_team', 'away_team'])
    return merged

def fit_model(merged_df):
    """Fit linear model: spread_line = α + β * (home_net_ypp - away_net_ypp)."""
    merged_df['strength_diff'] = merged_df['home_net_ypp'] - merged_df['away_net_ypp']
    X = merged_df[['strength_diff']].values
    y = merged_df['spread_line'].values
    
    model = LinearRegression()
    model.fit(X, y)
    
    alpha = model.intercept_
    beta = model.coef_[0]
    y_pred = model.predict(X)
    residuals = y - y_pred
    mae = np.mean(np.abs(residuals))
    rmse = np.sqrt(np.mean(residuals**2))
    r2 = model.score(X, y)
    
    return {
        'alpha': alpha,
        'beta': beta,
        'mae': mae,
        'rmse': rmse,
        'r2': r2,
        'n_samples': len(X),
        'merged_df': merged_df,
        'model': model,
        'y_pred': y_pred,
    }

def cross_validate_time(merged_df, n_splits=5):
    """Time-series cross-validation."""
    tscv = TimeSeriesSplit(n_splits=n_splits)
    merged_df = merged_df.sort_values(['season', 'week'])
    X = merged_df[['strength_diff']].values
    y = merged_df['spread_line'].values
    
    results = []
    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        model = LinearRegression()
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        mae = np.mean(np.abs(y_test - y_pred))
        rmse = np.sqrt(np.mean((y_test - y_pred)**2))
        results.append({
            'fold': fold,
            'train_size': len(X_train),
            'test_size': len(X_test),
            'alpha': model.intercept_,
            'beta': model.coef_[0],
            'mae': mae,
            'rmse': rmse,
        })
    return results

def plot_scatter(merged_df, alpha, beta, output_path):
    """Scatter plot strength_diff vs spread_line with regression line."""
    plt.figure(figsize=(8,6))
    plt.scatter(merged_df['strength_diff'], merged_df['spread_line'], alpha=0.5, s=10)
    x_min = merged_df['strength_diff'].min()
    x_max = merged_df['strength_diff'].max()
    x_range = np.linspace(x_min, x_max, 100)
    y_range = alpha + beta * x_range
    plt.plot(x_range, y_range, color='red', linewidth=2,
             label=f'y = {alpha:.3f} + {beta:.3f}*diff')
    plt.xlabel('Strength differential (home_net_ypp - away_net_ypp)')
    plt.ylabel('Closing spread (home)')
    plt.title(f'YPP differential vs Spread (n={len(merged_df)})')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(output_path, dpi=150)
    plt.close()

if __name__ == "__main__":
    output_dir = os.path.join(os.path.dirname(dl.__file__), "data", "model_fits")
    os.makedirs(output_dir, exist_ok=True)
    
    print("Loading team_ypp_history from Turso cache...")
    ypp_df = load_team_ypp_history()
    print(f"Loaded {len(ypp_df)} team‑game rows")
    
    print("Loading nflverse games.csv...")
    games_df = load_nflverse_games()
    print(f"Loaded {len(games_df)} games")
    
    print("Merging datasets...")
    merged = merge_ypp_games(ypp_df, games_df)
    print(f"Merged dataset: {len(merged)} games")
    
    # Fit model
    result = fit_model(merged)
    print("\n--- Regression results ---")
    print(f"Alpha (intercept): {result['alpha']:.4f}")
    print(f"Beta (coefficient): {result['beta']:.4f}")
    print(f"MAE: {result['mae']:.3f}")
    print(f"RMSE: {result['rmse']:.3f}")
    print(f"R²: {result['r2']:.3f}")
    print(f"Sample size: {result['n_samples']}")
    
    # Cross-validation
    cv_results = cross_validate_time(merged, n_splits=5)
    print("\n--- Time-series CV ---")
    # Save coefficients to JSON for predictor integration
    coeffs = {
        'alpha': result['alpha'],
        'beta': result['beta'],
        'mae': result['mae'],
        'rmse': result['rmse'],
        'r2': result['r2'],
        'n_samples': result['n_samples'],
        'last_updated': pd.Timestamp.now().isoformat(),
    }
    json_path = os.path.join(output_dir, "ypp_coefficients.json")
    with open(json_path, 'w') as f:
        json.dump(coeffs, f, indent=2)
    print(f"Coefficients saved to {json_path}")
    
    # Try to plot (optional)
    plot_path = os.path.join(output_dir, "ypp_vs_spread_v2.png")
    try:
        plot_scatter(merged, result['alpha'], result['beta'], plot_path)
        print(f"Plot saved to {plot_path}")
    except Exception as e:
        print(f"Plot failed (permission?): {e}")
