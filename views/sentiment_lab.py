"""
Sentiment Lab page view.
"""
import streamlit as st
import pandas as pd
import analytics as an

def sentiment_lab_page(ctx):
    st.header("🧠 Sentiment Lab — Week 4 (Forward‑Test)")
    st.caption("Sentiment analysis for all Week 4 matchups. Composite diff = home composite - away composite.")
    
    # Use direct SQLite connection to avoid db import hang
    import sqlite3
    import pandas as pd
    import data as dl
    
    # Sentiment Lab is fixed to Week 4, 2026 for forward-test
    season = 2026
    week = 4
    st.write(f"Sentiment Lab — Week {week} (fixed for forward‑test)")
    
    # Load Week 4 games
    games = dl.load_games()
    week_games = games[(games["season"] == season) & (games["week"] == week)].sort_values(["gameday", "gametime"])
    st.write(f"Week games found: {len(week_games)}")
    
    if week_games.empty:
        st.warning("No games found for Week 4.")
        return
    
    # Connect to database
    DB_PATH = "/app/data/nfl_edge.db"
    import os
    if not os.path.exists(DB_PATH):
        st.error(f"Database not found at {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    rows = []
    for idx, g in week_games.iterrows():
        away, home = g["away_team"], g["home_team"]
        
        # Get sentiment scores from DB
        away_score = None
        home_score = None
        for team in (away, home):
            c.execute("""
                SELECT confidence, morale, controversy 
                FROM sentiment_scores 
                WHERE team = ? AND season = ? AND week = ? AND source = 'combined'
                ORDER BY created_at DESC LIMIT 1
            """, (team, season, week))
            row = c.fetchone()
            if row:
                conf, mor, cont = row
                composite = conf + mor - cont
                if team == away:
                    away_score = {'confidence': conf, 'morale': mor, 'controversy': cont, 'composite': composite}
                else:
                    home_score = {'confidence': conf, 'morale': mor, 'controversy': cont, 'composite': composite}
        
        away_comp = away_score['composite'] if away_score else None
        home_comp = home_score['composite'] if home_score else None
        diff = home_comp - away_comp if (away_comp is not None and home_comp is not None) else None
        
        pick = None
        if diff is not None:
            pick = home if diff > 0 else away
        
        rows.append({
            "Game": f"{away} @ {home}",
            "Away": away,
            "Home": home,
            "Away Composite": f"{away_comp:.2f}" if away_comp is not None else "—",
            "Home Composite": f"{home_comp:.2f}" if home_comp is not None else "—",
            "Composite Diff": f"{diff:+.2f}" if diff is not None else "—",
            "Sentiment Pick": pick if pick else "—",
            "Word Cloud": "View" if (away_score and home_score) else "N/A"
        })
    
    conn.close()
    st.write(f"Built {len(rows)} rows")
    
    # Display as dataframe
    df = pd.DataFrame(rows)
    if df.empty:
        st.warning("No data to display")
        return
    
    # Add styling for picks
