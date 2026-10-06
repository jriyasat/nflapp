import sys
sys.path.insert(0, '/app')
import data as dl
import pandas as pd
import numpy as np

# load games
games = dl.load_games()
gl = []
for _, g in games[(games['game_type'] == 'REG') & games['spread_line'].notna()].iterrows():
    gl.append({'season': g['season'], 'week': g['week'], 'team': g['home_team'], 'team_line': -g['spread_line']})
    gl.append({'season': g['season'], 'week': g['week'], 'team': g['away_team'], 'team_line': g['spread_line']})
gl = pd.DataFrame(gl)

# load stats for 2021-22
w = dl.load_player_stats(season_start=2021, season_end=2022)
tw = w.groupby(['season', 'week', 'team'], as_index=False).agg(
    team_pass_att=('attempts', 'sum'),
    team_rush_att=('carries', 'sum')
)
tw = tw.merge(gl, on=['season', 'week', 'team'], how='inner')
fit = tw.dropna(subset=['team_line'])
if len(fit) > 5:
    b_pass = np.polyfit(fit['team_line'], fit['team_pass_att'], 1)
    b_rush = np.polyfit(fit['team_line'], fit['team_rush_att'], 1)
    mean_pa, mean_ra = fit['team_pass_att'].mean(), fit['team_rush_att'].mean()
    print(f'PASS_SCRIPT_SLOPE={b_pass[0]:.6f}')
    print(f'PASS_ATT_MEAN={mean_pa:.2f}')
    print(f'RUSH_SCRIPT_SLOPE={b_rush[0]:.6f}')
    print(f'RUSH_ATT_MEAN={mean_ra:.2f}')
else:
    print('Not enough data', file=sys.stderr)