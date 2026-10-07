#!/usr/bin/env python
"""
Fit linear model: yards-per-play differential vs. spread residual.
Uses SGO historical results (team-week stats) and nflverse games.csv (closing lines).
Outputs regression coefficients (alpha, beta) and validation metrics.
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import TimeSeriesSplit
import matplotlib.pyplot as plt

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl

def load_sgo_stats(csv_path):
    """Load SGO team-week stats."""
    df = pd.read_csv(csv_path)
    # Ensure numeric columns
    for col in ['season', 'week', 'yards', 'plays', 'points', 'turnovers',
                'off_ypp', 'def_ypp', 'net_ypp']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
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

def map_team_name_to_abbr(name):
    """Map team short name (e.g., 'NYJ') to nflverse abbreviation (same)."""
    # SGO short names already match nflverse abbreviations (e.g., 'NYJ')
    return name.upper()

def merge_sgo_games(sgo_df, games_df):
    """Merge SGO team stats with nflverse games."""
    # We have SGO data per team (home/away) with team_name (short)
    # Need to join on season, week, home_team/away_team
    # We'll create two dataframes: home stats and away stats
    home_sgo = sgo_df[sgo_df['team'] == 'home'].copy()
    away_sgo = sgo_df[sgo_df['team'] == 'away'].copy()
    
    # Map team names
    home_sgo['team_abbr'] = home_sgo['team_name'].apply(map_team_name_to_abbr)
    away_sgo['team_abbr'] = away_sgo['team_name'].apply(map_team_name_to_abbr)
    
    # Merge home stats
    merged = pd.merge(
        games_df,
        home_sgo[['season', 'week', 'team_abbr', 'net_ypp', 'off_ypp', 'def_ypp']],
        left_on=['season', 'week', 'home_team'],
        right_on=['season', 'week', 'team_abbr'],
        how='inner',
        suffixes=('', '_home')
    )
    # Merge away stats
    merged = pd.merge(
        merged,
        away_sgo[['season', 'week', 'team_abbr', 'net_ypp', 'off_ypp', 'def_ypp']],
        left_on=['season', 'week', 'away_team'],
        right_on=['season', 'week', 'team_abbr'],
        how='inner',
        suffixes=('', '_away')
    )
    # Clean column names
    merged = merged.rename(columns={
        'net_ypp': 'home_net_ypp',
        'off_ypp': 'home_off_ypp',
        'def_ypp': 'home_def_ypp',
        'net_ypp_away': 'away_net_ypp',
        'off_ypp_away': 'away_off_ypp',
        'def_ypp_away': 'away_def_ypp',
    })
    return merged.dropna(subset=['home_net_ypp', 'away_net_ypp', 'spread_line'])

def fit_model(merged_df):
    """Fit linear model: spread_residual = α + β * strength_diff."""
    # Compute strength differential = home_net_ypp - away_net_ypp
    merged_df['strength_diff'] = merged_df['home_net_ypp'] - merged_df['away_net_ypp']
    
    # Spread_line is home spread (negative means home favored)
    # We want to predict spread_line using strength_diff
    X = merged_df[['strength_diff']].values
    y = merged_df['spread_line'].values
    
    model = LinearRegression()
    model.fit(X, y)
    
    alpha = model.intercept_
    beta = model.coef_[0]
    
    # Predictions
    y_pred = model.predict(X)
    residuals = y - y_pred
    
    # Metrics
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
    parser = argparse.ArgumentParser()
    parser.add_argument("sgo_csv", nargs="?", default="data/sgo_historical_2024-01-01.csv",
                        help="Path to SGO historical CSV (default: data/sgo_historical_2024-01-01.csv)")
    parser.add_argument("--cutoff-season", type=int, default=None,
                        help="Only include games with season < cutoff_season (exclusive)")
    args = parser.parse_args()

    sgo_csv = os.path.join(os.path.dirname(dl.__file__), args.sgo_csv)
    output_dir = os.path.join(os.path.dirname(dl.__file__), "data", "model_fits")
    os.makedirs(output_dir, exist_ok=True)

    print("Loading data...")
    sgo_df = load_sgo_stats(sgo_csv)
    games_df = load_nflverse_games()
    print(f"SGO stats: {len(sgo_df)} rows")
    print(f"Games: {len(games_df)} rows")

    merged = merge_sgo_games(sgo_df, games_df)
    if args.cutoff_season is not None:
        merged = merged[merged["season"] < args.cutoff_season]
        print(f"Filtered to seasons before {args.cutoff_season}: {len(merged)} games")
    print(f"Merged dataset: {len(merged)} games")

    if len(merged) == 0:
        print("ERROR: No data after filtering. Exiting.")
        sys.exit(1)

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
    for res in cv_results:
        print(f"Fold {res['fold']}: train={res['train_size']}, test={res['test_size']}, MAE={res['mae']:.3f}, RMSE={res['rmse']:.3f}")

    # Plot
    plot_path = os.path.join(output_dir, "ypp_vs_spread.png")
    plot_scatter(merged, result['alpha'], result['beta'], plot_path)
    print(f"\nPlot saved to {plot_path}")

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
    import json as json_lib
    with open(json_path, 'w') as f:
        json_lib.dump(coeffs, f, indent=2)
    print(f"Coefficients saved to {json_path}")