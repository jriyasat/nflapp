import sys, pandas as pd, json, math
sys.path.insert(0, '/app')
import data as dl
import predictor as pr
import db

class YPPModelFlipped:
    """YPP model with sign flipped: spread = +(alpha + beta * ypp_diff) (positive = home favored)"""
    def __init__(self):
        with open('/app/data/model_fits/ypp_coefficients.json', 'r') as f:
            coeff = json.load(f)
        self.alpha = coeff.get('alpha', 0.0)
        self.beta = coeff.get('beta', 0.0)
    def _load_team_stats(self):
        raw, _ = db.cache_get('team_ypp_history')
        if raw is None:
            raw, _ = db.cache_get('sgo_team_stats')
            if raw is None:
                return pd.DataFrame()
        rows = json.loads(raw)
        df = pd.DataFrame(rows)
        if 'date' not in df.columns and 'start_date' in df.columns:
            df['date'] = pd.to_datetime(df['start_date']).dt.date
        elif 'startsAt' in df.columns:
            df['date'] = pd.to_datetime(df['startsAt']).dt.date
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.date
        if 'net_ypp' not in df.columns:
            if all(col in df.columns for col in ['off_ypp', 'def_ypp']):
                df['net_ypp'] = df['off_ypp'] - df['def_ypp']
            elif all(col in df.columns for col in ['off_yards', 'off_plays', 'def_yards_allowed', 'def_plays']):
                df['off_ypp'] = df['off_yards'] / df['off_plays'].replace(0, pd.NA)
                df['def_ypp'] = df['def_yards_allowed'] / df['def_plays'].replace(0, pd.NA)
                df['net_ypp'] = df['off_ypp'] - df['def_ypp']
            else:
                df['net_ypp'] = 0.0
        return df
    def get_team_ypp_stats(self, team, date=None):
        df = self._load_team_stats()
        if df.empty:
            return 0.0, 0
        mask = df['team'] == team.upper()
        if date is not None:
            if 'date' in df.columns:
                mask &= df['date'] < pd.to_datetime(date).date()
        team_df = df[mask].sort_values('date', ascending=False).head(4)
        if team_df.empty:
            return 0.0, 0
        avg_net_ypp = team_df['net_ypp'].mean()
        return avg_net_ypp, len(team_df)
    def predict_spread(self, away_team, home_team, date=None):
        away_net, away_n = self.get_team_ypp_stats(away_team, date)
        home_net, home_n = self.get_team_ypp_stats(home_team, date)
        if away_n == 0 or home_n == 0:
            ypp_diff = 0.0
        else:
            ypp_diff = home_net - away_net
        spread = (self.alpha + self.beta * ypp_diff)   # FLIPPED: positive = home favored
        return spread

# Quick backtest on first 200 games
games = dl.load_games()
g = games[(games["result"].notna()) & (games["season"] >= 2021)
          & (games["game_type"] == "REG")].sort_values(["season", "week", "gameday"])
g = g.head(200)
ratings = {}
hist = []
a = b = None
rows = []
for _, r in g.iterrows():
    if a is None:
        a, b = 0.033, 0.0
    ra = ratings.get(r["away_team"], pr.START)
    rh = ratings.get(r["home_team"], pr.START)
    p_home = 1 / (1 + 10 ** (-((rh + pr.HFA) - ra) / 400))
    if pd.notna(r["spread_line"]):
        p_c = min(max(p_home, 0.02), 0.98)
        elo_spread = a * math.log(p_c / (1 - p_c)) + b
        market_spread = -float(r["spread_line"])
        ypp = YPPModelFlipped()
        ypp_spread = ypp.predict_spread(r["away_team"], r["home_team"], r.get("gameday"))
        # blend weights
        market_weight = 0.85
        nonmarket_weight = 0.15
        ypp_weight = 0.85
        elo_weight = 0.15
        total = ypp_weight + elo_weight
        if total > 0:
            ypp_weight /= total
            elo_weight /= total
        nonmarket_spread = ypp_spread * ypp_weight + elo_spread * elo_weight
        adj = 0.0
        ar, hr = r.get("away_rest"), r.get("home_rest")
        if pd.notna(ar) and pd.notna(hr) and abs(ar - hr) >= 3:
            adj = -0.5 if hr > ar else 0.5
        adj = max(min(adj, pr.MAX_ADJ), -pr.MAX_ADJ)
        model_spread = market_weight * market_spread + nonmarket_weight * nonmarket_spread - adj
        edge = (-model_spread) - (-market_spread)
        home_cov = r["result"] - market_spread
        pick_home = edge > 0
        pick_won = (pick_home and home_cov > 0) or (not pick_home and home_cov < 0)
        rows.append({
            "edge": edge,
            "pick_home": pick_home,
            "home_cov": home_cov,
            "pick_won": pick_won,
        })
    home_won = r["result"] > 0
    mov = abs(r["result"])
    elo_diff = (rh + pr.HFA - ra) if home_won else (ra - rh - pr.HFA)
    mult = math.log(mov + 1) * (2.2 / (elo_diff * 0.001 + 2.2))
    shift = pr.K * mult * ((1 if home_won else 0) - p_home)
    ratings[r["home_team"]] = rh + shift
    ratings[r["away_team"]] = ra - shift

df = pd.DataFrame(rows)
print(f"Games processed: {len(df)}")
for thresh in [1.5, 2.0]:
    sub = df[df["edge"].abs() >= thresh]
    dec = sub[sub["home_cov"] != 0]
    if len(dec) == 0:
        print(f"Threshold {thresh}: n=0")
        continue
    wins = dec["pick_won"].sum()
    win_pct = wins / len(dec) * 100
    profit = wins * (100 / 110) - (len(dec) - wins)
    roi = profit / len(dec) * 100
    clv = sub["edge"].mean()
    print(f"Threshold {thresh}: n={len(dec)}, win%={win_pct:.1f}, ROI={roi:.1f}%, avg CLV={clv:.2f} pts")