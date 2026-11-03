"""
Sentiment Lab page view.
"""
import streamlit as st
import pandas as pd
import analytics as an

def sentiment_lab_page(ctx):
    import data as dl
    import sentiment as stm

    games = dl.load_games()
    season, week = dl.current_season_week(games)

    st.header(f"🧠 Sentiment Lab — Week {week} ({season})")
    st.caption("Sentiment analysis for all current-week matchups. Composite diff = home composite - away composite.")

    week_games = games[(games["season"] == season) & (games["week"] == week)].sort_values(["gameday", "gametime"])

    if week_games.empty:
        st.warning(f"No games found for Week {week}.")
        return

    rows = []
    for idx, g in week_games.iterrows():
        away, home = g["away_team"], g["home_team"]

        # Get sentiment scores from the shared cache (Turso)
        away_score = stm.get_sentiment_score(away, season, week, 'combined')
        home_score = stm.get_sentiment_score(home, season, week, 'combined')

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
    
    st.write(f"Built {len(rows)} rows")
    
    # Display as dataframe
    df = pd.DataFrame(rows)
    if df.empty:
        st.warning("No data to display")
        return
    
    # Add styling for picks
