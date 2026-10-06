#!/usr/bin/env python
"""
Fit linear model: yards-per-play differential vs. spread residual.
Uses team_ypp_history cache (nflverse stats_team aggregated) and nflverse games.csv.
Outputs regression coefficients (alpha, beta) and validation metrics.
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
    """Load team-week stats from shared_cache 'team_ypp_history'."""
    raw, _ = db.cache_get('team_ypp_history')
    if raw is None:
        # fallback to local JSON
        backup_path = os.path.join(dl.CACHE, 'team_ypp_history.json')
        if os.path.exists(backup_path):
            with open(backup_path, 'r') as f:
                raw = f.read()
        else:
            raise ValueError('team_ypp_history not found in cache or local backup')
    rows = json.loads(raw)
    df = pd.DataFrame(rows)
    # Convert date string to datetime
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date']).dt.date
    # Ensure numeric columns
    for col in ['season', 'week', 'off_yards', 'off_plays', 'def_yards_allowed', 'def_plays', 'off_ypp', 'def_ypp', 'net_ypp']:
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
    """Map team abbreviation to uppercase, replace LA->LAR."""
    name = str(name).upper()
    if name == 'LA':
        return 'LAR'
    return name

def merge_ypp_games(ypp_df, games_df):
    """Merge YPP team stats with nflverse games."""
    # Create home and away dataframes
    ypp_df['team_abbr'] = ypp_df['team'].apply(map_team_name_to_abbr)
    # We need each game row with home and away stats
    # Create mapping: (season, week, team_abbr) -> net_ypp
    team_map = ypp_df.set_index(['season', 'week', 'team_abbr'])['net_ypp'].to_dict()
    # Apply to home and away columns
    games_df['home_net_ypp'] = games_df.apply(
        lambda row: team_map.get((row['season'], row['week'], map_team_name_to_abbr(row['home_team'])), np.nan), axis=1)
    games_df['away_net_ypp'] = games_df.apply(
        lambda row: team_map.get((row['season'], row['week'], map_team_name_to_abbr(row['away_team'])), np.nan), axis=1)
    # Drop rows where either net_ypp missing
    merged = games_df.dropna(subset=['home_net_ypp', 'away_net_ypp', 'spread_line'])
    return merged

def fit_model(merged_df):
    """Fit linear model: spread_residual = α + β * strength_diff."""
    # Compute strength differential = home_net_ypp - away_net_ypp
    merged_df['strength_diff'] = merged_df['home_net_ypp'] - merged_df['away_net_ypp']
    # Spread_line is home spread (negative means home favored)
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
    output_dir = os.path.join(os.path.dirname(dl.__file__), "data", "model_fits")
    os.makedirs(output_dir, exist_ok=True)
    
    print("Loading team_ypp_history...")
    ypp_df = load_team_ypp_history()
    print(f"Loaded {len(ypp_df)} team-week rows")
    
    print("Loading games.csv...")
    games_df = load_nflverse_games()
    print(f"Games: {len(games_df)} rows")
    
    merged = merge_ypp_games(ypp_df, games_df)
    print(f"Merged dataset: {len(merged)} games")
    if merged.empty:
        print("No overlapping games. Exiting.")
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
    plot_path = os.path.join(output_dir, "ypp_vs_spread_cache.png")
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
    with open(json_path, 'w') as f:
        json.dump(coeffs, f, indent=2)
    print(f"Coefficients saved to {json_path}")