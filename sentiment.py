"""
Sentiment analysis layer for NFL Edge.

Collects news, Reddit posts, and web search snippets for each team,
scores via LLM (confidence, morale, controversy), stores in Turso.
"""

import os
import json
import time
import uuid
from datetime import datetime, timedelta
import re
import subprocess

import requests

import data as dl
# import db (replaced with sqlite3)
import sqlite3
DB_PATH = '/app/data/nfl_edge.db'

# ---------- configuration ----------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_AVAILABLE = bool(OPENROUTER_API_KEY)

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
OPENROUTER_MODEL = 'deepseek/deepseek-v3.2'

# team name mapping for searches
TEAM_TO_FULL = {
    'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals',
    'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos',
    'DET': 'Detroit Lions', 'GB': 'Green Bay Packers', 'HOU': 'Houston Texans',
    'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
    'KC': 'Kansas City Chiefs', 'LAC': 'Los Angeles Chargers',
    'LAR': 'Los Angeles Rams', 'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints',
    'NYG': 'New York Giants', 'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles',
    'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks', 'SF': 'San Francisco 49ers',
    'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans',
    'WAS': 'Washington Commanders',
}

# subreddit mapping (lowercase, without r/)
TEAM_TO_SUBREDDIT = {
    'ATL': 'falcons', 'BAL': 'ravens', 'BUF': 'buffalobills',
    'CAR': 'panthers', 'CHI': 'chibears', 'CIN': 'bengals',
    'CLE': 'browns', 'DAL': 'cowboys', 'DEN': 'denverbroncos',
    'DET': 'detroitlions', 'GB': 'GreenBayPackers', 'HOU': 'Texans',
    'IND': 'Colts', 'JAX': 'Jaguars', 'KC': 'KansasCityChiefs',
    'LAC': 'Chargers', 'LAR': 'LosAngelesRams', 'LV': 'raiders',
    'MIA': 'miamidolphins', 'MIN': 'minnesotavikings', 'NE': 'Patriots',
    'NO': 'Saints', 'NYG': 'NYGiants', 'NYJ': 'nyjets', 'PHI': 'eagles',
    'PIT': 'steelers', 'SEA': 'Seahawks', 'SF': '49ers',
    'TB': 'buccaneers', 'TEN': 'Tennesseetitans', 'WAS': 'Commanders',
}

# ---------- table management ----------
def ensure_sentiment_table():
    """Create sentiment_scores table if it doesn't exist."""
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS sentiment_scores (
            id TEXT PRIMARY KEY,
            team TEXT NOT NULL,
            season INT,
            week INT,
            source TEXT,
            confidence REAL,
            morale REAL,
            controversy REAL,
            created_at TEXT
        )""")

# ---------- data collection ----------

def collect_news_snippets(team_abbr, days_back=7):
    """Return list of text snippets from ESPN/CBS news for the team."""
    full_name = TEAM_TO_FULL.get(team_abbr, team_abbr)
    keywords = [full_name, team_abbr]
    # get recent news
    items = dl.merged_news(limit=100)
    snippets = []
    for item in items:
        text = (item.get('title', '') + ' ' + item.get('desc', '')).lower()
        if any(kw.lower() in text for kw in keywords):
            snippets.append(text[:500])
    return snippets

def collect_exa_snippets(team_abbr, query_suffix='week 4 news', limit=5):
    """Use Exa AI search via mcporter to find recent articles."""
    full_name = TEAM_TO_FULL.get(team_abbr, team_abbr)
    query = f'{full_name} {query_suffix}'
    cmd = f"mcporter call 'exa.web_search_exa(query: \"{query}\", numResults: {limit})'"
    try:
        output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        # parse output (simple line-based)
        lines = output.split('\n')
        snippets = []
        for line in lines:
            if line.startswith('Highlights:'):
                # the Highlights line contains the snippet
                snippet = line.replace('Highlights:', '').strip()
                if snippet:
                    snippets.append(snippet[:500])
        return snippets
    except Exception as e:
        print(f'Exa search error for {team_abbr}: {e}')
        return []

def collect_reddit_snippets(team_abbr, limit=10):
    """Fetch recent posts from team subreddit via OpenCLI."""
    subreddit = TEAM_TO_SUBREDDIT.get(team_abbr)
    if not subreddit:
        return []
    # use OpenCLI profile from env
    profile = os.environ.get('OPENCLI_PROFILE', '2s5wdubd')
    cmd = f'OPENCLI_PROFILE={profile} opencli reddit search "subreddit:{subreddit}" -f yaml --limit {limit}'
    try:
        output = subprocess.check_output(cmd, shell=True, text=True, timeout=30, stderr=subprocess.DEVNULL)
        import yaml
        posts = yaml.safe_load(output)
        if not isinstance(posts, list):
            return []
        snippets = []
        for post in posts:
            title = post.get('title', '')
            selftext = post.get('selftext', '')
            if selftext:
                snippets.append(f'{title}: {selftext}'[:500])
            elif title:
                snippets.append(title[:500])
        return snippets
    except subprocess.TimeoutExpired:
        print(f'Reddit timeout for {team_abbr}')
        return []
    except Exception as e:
        print(f'Reddit error for {team_abbr}: {e}')
        return []

def collect_all_snippets(team_abbr, season, week):
    """Aggregate snippets from all sources (news + Exa only)."""
    snippets = []
    snippets.extend(collect_news_snippets(team_abbr))
    snippets.extend(collect_exa_snippets(team_abbr, f'week {week} news'))
    # Reddit disabled for speed
    # snippets.extend(collect_reddit_snippets(team_abbr))
    # deduplicate by simple hash
    seen = set()
    unique = []
    for s in snippets:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:20]  # cap total

# ---------- LLM scoring ----------

def score_sentiment_llm(snippets):
    """Send snippets to LLM, return dict with confidence, morale, controversy."""
    if not snippets:
        # neutral fallback
        return {'confidence': 0.0, 'morale': 0.0, 'controversy': 0.0}
    
    # build context
    if not OPENROUTER_AVAILABLE:
        return {"confidence": 0.0, "morale": 0.0, "controversy": 0.0}
    context = '\n'.join([f'- {s}' for s in snippets[:10]])  # up to 10 snippets
    prompt = f"""You are analyzing sentiment around an NFL team based on recent news, social media, and fan discussions.

Relevant excerpts:
{context}

Score the team's current situation on three dimensions (range -1.0 to +1.0):

- **confidence**: How confident is the team/fanbase about upcoming performance? High positive = strong belief in success, high negative = doubt.
- **morale**: Overall team morale (player mood, locker room vibe). Positive = upbeat, negative = low spirits.
- **controversy**: Level of external drama, conflict, or distraction (0 = calm, +1 = high controversy).

Return ONLY a JSON object with keys "confidence", "morale", "controversy" (floats). No commentary."""
    
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
    }
    data = {
        'model': OPENROUTER_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.1,
        'max_tokens': 200,
    }
    try:
        resp = requests.post(OPENROUTER_URL, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        content = result['choices'][0]['message']['content'].strip()
        # parse JSON
        parsed = json.loads(content)
        # clamp values
        for key in ('confidence', 'morale', 'controversy'):
            val = parsed.get(key, 0.0)
            if not isinstance(val, (int, float)):
                val = 0.0
            parsed[key] = max(-1.0, min(1.0, float(val)))
        return parsed
    except Exception as e:
        print(f'LLM scoring error: {e}')
        # fallback neutral
        return {'confidence': 0.0, 'morale': 0.0, 'controversy': 0.0}

# ---------- storage ----------

def store_sentiment_score(team, season, week, source, scores):
    """Insert or replace sentiment score in Turso."""
    ensure_sentiment_table()
    with sqlite3.connect(DB_PATH) as c:
        id_val = str(uuid.uuid4())
        created = datetime.now().isoformat()
        c.execute("""INSERT OR REPLACE INTO sentiment_scores
            (id, team, season, week, source, confidence, morale, controversy, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (id_val, team, season, week, source,
             scores['confidence'], scores['morale'], scores['controversy'], created))

def get_sentiment_score(team, season, week, source='combined'):
    """Retrieve stored sentiment scores."""
    ensure_sentiment_table()
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("""
            SELECT confidence, morale, controversy, created_at
            FROM sentiment_scores
            WHERE team = ? AND season = ? AND week = ? AND source = ?
            ORDER BY created_at DESC LIMIT 1
        """, (team, season, week, source)).fetchall()
        if rows:
            return {
                'confidence': rows[0][0],
                'morale': rows[0][1],
                'controversy': rows[0][2],
                'composite': rows[0][0] + rows[0][1] - rows[0][2],
                'created_at': rows[0][3],
            }
    return None
def compute_combined_score(team, season, week):
    """Compute weighted average across sources (simple average for now)."""
    ensure_sentiment_table()
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("""
            SELECT confidence, morale, controversy
            FROM sentiment_scores
            WHERE team = ? AND season = ? AND week = ? AND source IN ('news', 'reddit', 'exa')
        """, (team, season, week)).fetchall()
        if not rows:
            return None
        conf = sum(r[0] for r in rows) / len(rows)
        mor = sum(r[1] for r in rows) / len(rows)
        cont = sum(r[2] for r in rows) / len(rows)
        # store combined
        store_sentiment_score(team, season, week, 'combined', {
            'confidence': conf, 'morale': mor, 'controversy': cont
        })
        return {'confidence': conf, 'morale': mor, 'controversy': cont, 'composite': conf + mor - cont}

# ---------- main pipeline ----------

def ensure_sentiment_for_week(season, week, teams=None):
    """Ensure sentiment scores exist for given teams (or all NFL teams)."""
    if teams is None:
        teams = list(TEAM_TO_FULL.keys())
    for team in teams:
        # check if already scored this week
        existing = get_sentiment_score(team, season, week, 'combined')
        if existing:
            print(f'{team} week {week} sentiment already scored')
            continue
        print(f'Collecting sentiment for {team} week {week}...')
        snippets = collect_all_snippets(team, season, week)
        if not snippets:
            print(f'  No snippets found')
            continue
        print(f'  {len(snippets)} snippets')
        scores = score_sentiment_llm(snippets)
        print(f'  scores: {scores}')
        # store per source (currently combined)
        store_sentiment_score(team, season, week, 'combined', scores)
        # Also store snippets for word clouds
        store_snippets(team, season, week, 'combined', snippets)
        time.sleep(1)  # rate limit
    print('Sentiment collection complete')

# ---------- word cloud generation ----------
def ensure_snippets_table():
    """Create sentiment_snippets table if it doesn't exist."""
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS sentiment_snippets (
                team TEXT NOT NULL,
                season INT NOT NULL,
                week INT NOT NULL,
                source TEXT NOT NULL,
                snippets TEXT,
                created_at TEXT,
                PRIMARY KEY (team, season, week, source)
            )
        """)


def store_snippets(team, season, week, source, snippets):
    """Store snippets in a dedicated table for word cloud generation."""
    ensure_snippets_table()
    snippet_text = " ".join(snippets)
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            INSERT OR REPLACE INTO sentiment_snippets 
            (team, season, week, source, snippets, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (team, season, week, source, snippet_text))


def get_wordcloud_url(team, season, week, source='combined'):
    """Return QuickChart.io URL for a word cloud of the team's sentiment snippets.
    
    Returns None if no snippets available.
    """
    # First get snippets (they're stored in the DB)
    ensure_snippets_table()
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("""
            SELECT snippets 
            FROM sentiment_snippets 
            WHERE team = ? AND season = ? AND week = ? AND source = ?
            ORDER BY created_at DESC LIMIT 1
        """, (team, season, week, source)).fetchall()
    
    # If snippets table doesn't exist or is empty, try to extract from news
    if not rows:
        # Fallback: collect news snippets now
        snippets = collect_news_snippets(team)
        if not snippets:
            return None
        # Store for future use
        store_snippets(team, season, week, source, snippets)
        snippet_text = " ".join(snippets)
    else:
        snippet_text = rows[0][0] or ""
    
    if not snippet_text.strip():
        return None
    
    # Extract top words (simple tokenization)
    import re
    from collections import Counter
    import string
    
    # Clean and tokenize: remove punctuation, split on whitespace
    # Convert to lowercase first
    text_lower = snippet_text.lower()
    # Remove punctuation manually (keep letters and spaces)
    # Replace punctuation with space to avoid glued words
    translator = str.maketrans(string.punctuation, ' ' * len(string.punctuation))
    cleaned = text_lower.translate(translator)
    # Split on whitespace
    words = cleaned.split()
    # Keep only words with at least 3 letters (no numbers)
    words = [w for w in words if w.isalpha() and len(w) >= 3]
    
    # Remove common stopwords
    stopwords = {'the', 'and', 'for', 'are', 'with', 'this', 'that', 'was', 
                 'were', 'have', 'has', 'had', 'but', 'not', 'you', 'your',
                 'they', 'their', 'them', 'from', 'about', 'will', 'would',
                 'should', 'could', 'when', 'where', 'which', 'who', 'whom',
                 'what', 'how', 'why', 'then', 'than', 'also', 'just', 'like',
                 'more', 'most', 'some', 'such', 'only', 'out', 'into', 'over',
                 'under', 'after', 'before', 'during', 'while', 'because',
                 'since', 'until', 'through', 'again', 'further', 'too', 'very'}
    
    filtered_words = [w for w in words if w not in stopwords]
    
    if not filtered_words:
        return None
    
    # Count frequencies
    word_counts = Counter(filtered_words)
    top_words = word_counts.most_common(25)  # Get top 25
    
    # Build text param: repeat words by frequency
    text_parts = []
    for word, count in top_words:
        # Repeat word proportional to frequency (max 10 repeats)
        repeats = min(count, 10)
        text_parts.extend([word] * repeats)
    
    text_param = "+".join(text_parts)
    
    # Colors: team-specific or neutral (JSON arrays as required by QuickChart)
    team_colors = {
        'ATL': '[\"red\",\"black\"]', 'BAL': '[\"purple\",\"black\",\"gold\"]', 'BUF': '[\"blue\",\"red\",\"white\"]',
        'CAR': '[\"black\",\"blue\"]', 'CHI': '[\"navy\",\"orange\"]', 'CIN': '[\"orange\",\"black\"]',
        'CLE': '[\"brown\",\"orange\"]', 'DAL': '[\"navy\",\"silver\"]', 'DEN': '[\"orange\",\"navy\"]',
        'DET': '[\"honolulublue\",\"silver\"]', 'GB': '[\"green\",\"gold\"]', 'HOU': '[\"navy\",\"red\"]',
        'IND': '[\"royalblue\",\"white\"]', 'JAX': '[\"teal\",\"gold\",\"black\"]', 'KC': '[\"red\",\"gold\"]',
        'LAC': '[\"powderblue\",\"gold\"]', 'LAR': '[\"royalblue\",\"gold\"]', 'LV': '[\"black\",\"silver\"]',
        'MIA': '[\"aqua\",\"orange\"]', 'MIN': '[\"purple\",\"gold\"]', 'NE': '[\"navy\",\"red\",\"silver\"]',
        'NO': '[\"black\",\"gold\"]', 'NYG': '[\"blue\",\"red\"]', 'NYJ': '[\"green\",\"white\"]',
        'PHI': '[\"green\",\"silver\",\"black\"]', 'PIT': '[\"black\",\"gold\"]', 'SEA': '[\"navy\",\"green\"]',
        'SF': '[\"red\",\"gold\"]', 'TB': '[\"pewter\",\"red\"]', 'TEN': '[\"navy\",\"columbiablue\",\"red\"]',
        'WAS': '[\"burgundy\",\"gold\"]'
    }
    
    colors = team_colors.get(team, '[\"navy\",\"forestgreen\",\"maroon\"]')
    
    # Build QuickChart URL (parameters per QuickChart documentation)
    base_url = "https://quickchart.io/wordcloud"
    params = {
        'text': text_param,
        'format': 'png',
        'width': '800',
        'height': '400',
        'colors': colors,  # JSON array string
        'backgroundColor': 'white',
        'fontFamily': 'sans-serif',
        'scale': 'sqrt',   # frequency scaling method: linear, sqrt, or log
        'fontScale': '25', # size of largest font (roughly)
        'maxNumWords': '50',
        'rotation': '20',  # maximum angle of rotation for words (degrees)
        'removeStopwords': 'true',
        'cleanWords': 'true',
        'language': 'en',
    }
    
    import urllib.parse
    query_string = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"{base_url}?{query_string}"


if __name__ == '__main__':
    # test with current week
    import sys
    if len(sys.argv) >= 3:
        s, w = int(sys.argv[1]), int(sys.argv[2])
    else:
        # default to week 4 2026
        s, w = 2026, 4
    ensure_sentiment_for_week(s, w)