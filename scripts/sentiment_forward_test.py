"""Forward‑test sentiment layer for Week 4 (Oct 4‑5).
Collects missing sentiment scores, runs baseline vs enhanced vs sentiment‑only picks.
Logs results to data/sentiment_picks_week4.csv for Monday review.
Run via weekend cron (Sat 8 AM ET)."""

import sys
import os
import json
import pandas as pd
from datetime import datetime

# Ensure we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("PYTHONPATH", None)

import data as dl
import predictor as pr
import sentiment as stm
import elo
from ypp_model import YPPModel

SEASON = 2026
WEEK = 4
SENTIMENT_WEIGHT_ENHANCED = 0.1  # from config/model_weights.json
SENTIMENT_THRESHOLD = 0.5        # default threshold for sentiment‑only picks

def ensure_all_scores():
    """Make sure sentiment scores exist for all 32 teams."""
    print("Ensuring sentiment scores for Week", WEEK)
    # This will skip teams already scored
    stm.ensure_sentiment_for_week(SEASON, WEEK, teams=None)
    # Count scored teams
    scored = 0
    for team in stm.TEAM_TO_FULL.keys():
        if stm.get_sentiment_score(team, SEASON, WEEK, 'combined'):
            scored += 1
    print(f"  {scored}/32 teams have sentiment scores")

def load_week_games():
    """Return DataFrame of Week 4 games."""
    df = dl.load_games()
    week_games = df[(df['season'] == SEASON) & (df['week'] == WEEK)].copy()
    if week_games.empty:
        raise RuntimeError(f"No games found for {SEASON} week {WEEK}")
    return week_games

def compute_pick(game_row, elo_model, ypp_model, sentiment_weight):
    """Return (predicted_spread, side_pick) with given sentiment_weight."""
    # Temporarily override global SENTIMENT_WEIGHT
    original_weight = pr.SENTIMENT_WEIGHT
    pr.SENTIMENT_WEIGHT = sentiment_weight
    try:
        pred = pr.predict_game(game_row, elo_model)
        spread = pred.get('model_spread', 0.0)
        # pick = 'home' if spread <= 0 else 'away' (negative spread means home favored)
        pick = 'home' if spread <= 0 else 'away'
        return spread, pick
    finally:
        pr.SENTIMENT_WEIGHT = original_weight

def sentiment_only_pick(away, home):
    """Return binary pick based on composite difference threshold.
       Returns 'home' if home composite - away composite > THRESHOLD,
       else 'away' (no 'push' for now)."""
    away_scores = stm.get_sentiment_score(away, SEASON, WEEK, 'combined')
    home_scores = stm.get_sentiment_score(home, SEASON, WEEK, 'combined')
    if away_scores is None or home_scores is None:
        return None
    diff = home_scores['composite'] - away_scores['composite']
    if diff > SENTIMENT_THRESHOLD:
        return 'home'
    else:
        return 'away'

def main():
    print(f"=== Sentiment forward‑test Week {WEEK} ===")
    ensure_all_scores()
    
    # Load games
    week_games = load_week_games()
    print(f"Found {len(week_games)} games")
    all_games = dl.load_games()
    
    # Initialize models
    elo_model = elo.EloModel(all_games)
    ypp_model = YPPModel() if pr.USE_YPP else None
    
    rows = []
    for _, game in week_games.iterrows():
        away, home = game['away_team'], game['home_team']
        
        # Baseline (sentiment weight 0)
        baseline_spread, baseline_pick = compute_pick(game, elo_model, ypp_model, 0.0)
        # Enhanced (sentiment weight 0.1)
        enhanced_spread, enhanced_pick = compute_pick(game, elo_model, ypp_model, SENTIMENT_WEIGHT_ENHANCED)
        # Sentiment‑only binary pick
        sent_only = sentiment_only_pick(away, home)
        
        rows.append({
            'game_id': game['game_id'],
            'away': away,
            'home': home,
            'baseline_spread': baseline_spread,
            'baseline_pick': baseline_pick,
            'enhanced_spread': enhanced_spread,
            'enhanced_pick': enhanced_pick,
            'sentiment_only_pick': sent_only,
            'composite_diff': None,  # to be filled
        })
    
    # Compute composite diff for each game (for reference)
    for row in rows:
        away_scores = stm.get_sentiment_score(row['away'], SEASON, WEEK, 'combined')
        home_scores = stm.get_sentiment_score(row['home'], SEASON, WEEK, 'combined')
        if away_scores and home_scores:
            row['composite_diff'] = home_scores['composite'] - away_scores['composite']
    
    # Write CSV
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'sentiment_picks_week4.csv')
    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False)
    print(f"Results saved to {out_path}")
    print(df[['away', 'home', 'baseline_pick', 'enhanced_pick', 'sentiment_only_pick']].to_string())
    
    # Summary stats
    changed = sum(1 for r in rows if r['baseline_pick'] != r['enhanced_pick'])
    print(f"\nPicks changed by sentiment layer: {changed}/{len(rows)}")
    
if __name__ == '__main__':
    main()