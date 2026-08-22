"""Data layer for NFL Edge Finder.

Sources:
- nflverse games.csv: full schedule/results + closing lines (spread_line, total_line),
  rest days, div_game, roof, temp/wind for every game since 1999.
- ESPN scoreboard API: per-week odds fallback (no key needed).
- ESPN injuries API: latest injury report (no key needed).
- The Odds API (optional, free key): multi-book live lines for line shopping.
"""

import json
import os
import time

import pandas as pd
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "data")
os.makedirs(CACHE, exist_ok=True)

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
ODDS_API = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"

GAMES_CACHE_H = 12
ESPN_CACHE_MIN = 10
ODDS_CACHE_MIN = 45  # free tier is 500 req/month -- be stingy


def _fresh(path, max_age_sec):
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_sec


_MEMO = {}


def load_games():
    """Full nflverse schedule/results table, cached 12h on disk; memoized in
    memory by file mtime so repeat calls in one process are free.
    Derived ATS/O-U columns added."""
    path = os.path.join(CACHE, "games.csv")
    if not _fresh(path, GAMES_CACHE_H * 3600):
        r = requests.get(GAMES_URL, timeout=60)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
    mt = os.path.getmtime(path)
    if _MEMO.get("games_mt") == mt:
        return _MEMO["games"]
    df = pd.read_csv(path, low_memory=False)
    for col in ["away_score", "home_score", "spread_line", "total_line",
                "away_rest", "home_rest", "away_moneyline", "home_moneyline"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["gameday"] = pd.to_datetime(df["gameday"], errors="coerce")
    played = df["result"].notna()
    # nflverse convention: spread_line is from the AWAY team's perspective (neg = away favored)
    df["home_cover_margin"] = df["result"] - df["spread_line"]  # >0 home covered
    df.loc[played, "ats_winner"] = df.loc[played, "home_cover_margin"].apply(
        lambda m: "PUSH" if m == 0 else ("HOME" if m > 0 else "AWAY"))
    df.loc[played, "ou_result"] = df.loc[played].apply(
        lambda r: "PUSH" if r["total"] == r["total_line"]
        else ("OVER" if r["total"] > r["total_line"] else "UNDER"), axis=1)
    _MEMO["games"] = df
    _MEMO["games_mt"] = mt
    return df


def current_season_week(df):
    """Next unplayed REG week (falls back to latest played)."""
    reg = df[df["game_type"] == "REG"]
    unplayed = reg[reg["result"].isna()].sort_values(["season", "week"])
    if len(unplayed):
        g = unplayed.iloc[0]
        return int(g["season"]), int(g["week"])
    last = reg.sort_values(["season", "week"]).iloc[-1]
    return int(last["season"]), int(last["week"])


_ESPN_DOWN_UNTIL = 0.0  # in-process circuit breaker: skip ESPN for 30min after a WAF ban


def _get_json(url, cache_name, max_age_min, params=None, service=None):
    if service == "espn" and time.time() < _ESPN_DOWN_UNTIL:
        raise requests.HTTPError("ESPN circuit open (rate-limited recently)")
    path = os.path.join(CACHE, cache_name)
    if _fresh(path, max_age_min * 60):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    last_err = None
    attempts = 1 if service == "espn" else 3  # ESPN WAF bans are IP+time based; retrying is pointless
    for attempt in range(attempts):
        try:
            r = requests.get(url, params=params, timeout=30,
                             headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                    "Chrome/126.0 Safari/537.36",
                                      "Accept": "application/json",
                                      "Referer": "https://www.espn.com/"})
            r.raise_for_status()
            data = r.json()
            with open(path, "w") as f:
                json.dump(data, f)
            return data
        except Exception as e:
            last_err = e
            if service == "espn" and getattr(getattr(e, "response", None), "status_code", None) == 403:
                globals()["_ESPN_DOWN_UNTIL"] = time.time() + 1800
            time.sleep(1.5 * (attempt + 1))
    # fall back to stale cache if we have one
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    raise last_err


def espn_week_odds(season, week, seasontype=2):
    """ESPN lines for a week (seasontype: 1=PRE, 2=REG, 3=POST). {} if not posted."""
    data = _get_json(ESPN_SCOREBOARD, f"espn_{season}_{seasontype}_{week}.json",
                     ESPN_CACHE_MIN, service="espn",
                     params={"dates": season, "seasontype": seasontype, "week": week, "limit": 100})
    out = {}
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        odds = (comp.get("odds") or [{}])[0]
        if not odds:
            continue
        home = away = None
        for c in comp.get("competitors", []):
            abbr = c.get("team", {}).get("abbreviation")
            if c.get("homeAway") == "home":
                home = abbr
            else:
                away = abbr
        if not home or not away:
            continue
        out[(away, home)] = {
            "provider": odds.get("provider", {}).get("name", "ESPN"),
            "details": odds.get("details"),          # e.g. "KC -3.0"
            "spread": odds.get("spread"),
            "over_under": odds.get("overUnder"),
            "home_ml": (odds.get("homeTeamOdds") or {}).get("moneyLine"),
            "away_ml": (odds.get("awayTeamOdds") or {}).get("moneyLine"),
        }
    return out


def espn_injuries():
    """Latest injury report: {TEAM_ABBR: [ {name, position, status, detail} ] }.
    Parsed result memoized by cache-file mtime (the raw JSON is ~9MB)."""
    cache_path = os.path.join(CACHE, "espn_injuries.json")
    if os.path.exists(cache_path) and _MEMO.get("inj_mt") == os.path.getmtime(cache_path):
        return _MEMO["inj"]
    data = _get_json(ESPN_INJURIES, "espn_injuries.json", 360, service="espn")
    out = {}
    for block in data.get("injuries", []):
        team = block.get("team", {}).get("abbreviation", "?")
        rows = []
        for inj in block.get("injuries", []):
            rows.append({
                "name": inj.get("athlete", {}).get("displayName", "?"),
                "position": inj.get("athlete", {}).get("position", {}).get("abbreviation", ""),
                "status": inj.get("status", ""),
                "detail": (inj.get("details") or {}).get("type", ""),
                "comment": inj.get("shortComment", ""),
            })
        out[team] = rows
    if os.path.exists(cache_path):
        _MEMO["inj"] = out
        _MEMO["inj_mt"] = os.path.getmtime(cache_path)
    return out


def odds_api_lines(api_key):
    """Multi-book lines from The Odds API. Returns {game_key: {book: {...}}}."""
    data = _get_json(ODDS_API, "odds_api.json", ODDS_CACHE_MIN, params={
        "apiKey": api_key, "regions": "us", "markets": "h2h,spreads,totals",
        "oddsFormat": "american"})
    out = {}
    for g in data:
        key = (g.get("away_team", ""), g.get("home_team", ""))
        books = {}
        for bk in g.get("bookmakers", []):
            entry = {"title": bk.get("title", bk.get("key"))}
            for m in bk.get("markets", []):
                if m["key"] == "spreads":
                    for o in m["outcomes"]:
                        if o["name"] == g.get("home_team"):
                            entry["home_spread"] = o.get("point")
                            entry["home_spread_price"] = o.get("price")
                        else:
                            entry["away_spread"] = o.get("point")
                            entry["away_spread_price"] = o.get("price")
                elif m["key"] == "totals":
                    for o in m["outcomes"]:
                        if o["name"] == "Over":
                            entry["total"] = o.get("point")
                            entry["over_price"] = o.get("price")
                        else:
                            entry["under_price"] = o.get("price")
                elif m["key"] == "h2h":
                    for o in m["outcomes"]:
                        if o["name"] == g.get("home_team"):
                            entry["home_ml"] = o.get("price")
                        else:
                            entry["away_ml"] = o.get("price")
            books[bk.get("key", bk.get("title"))] = entry
        out[key] = books
    return out


PLAYER_STATS_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
                    "stats_player/stats_player_week_%d.csv")
_PS_COLS = ["player_id", "player_display_name", "position", "position_group",
            "team", "season", "week", "season_type", "opponent_team",
            "attempts", "passing_yards", "passing_tds", "carries", "rushing_yards",
            "receptions", "targets", "receiving_yards", "receiving_tds"]


def load_player_stats():
    """Weekly player stats: last completed season + current. Cached 12h."""
    games = load_games()
    cur = int(games.loc[games["result"].isna(), "season"].max())
    frames = []
    for s in (cur, cur - 1):
        path = os.path.join(CACHE, f"player_stats_{s}.csv")
        if not _fresh(path, 12 * 3600):
            try:
                r = requests.get(PLAYER_STATS_URL % s, timeout=120)
                if r.status_code == 200 and len(r.content) > 100:
                    with open(path, "wb") as f:
                        f.write(r.content)
                else:
                    continue
            except Exception:
                continue
        if os.path.exists(path):
            frames.append(pd.read_csv(path, usecols=lambda c: c in _PS_COLS,
                                      low_memory=False))
    if not frames:
        raise RuntimeError("player stats unavailable")
    return pd.concat(frames, ignore_index=True)


ODDS_EVENTS = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events"
ODDS_EVENT_ODDS = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/%s/odds/"
PROP_MARKETS = "player_pass_yds,player_rush_yds,player_reception_yds,player_receptions"


def odds_api_event_props(api_key, away_name, home_name):
    """Player prop lines for ONE game (event-level; costs ~4 credits). Cached 45 min.
    Returns {market: {player_name: {"point": x, "over_price": p, "under_price": p, "book": b}}}"""
    ev = _get_json(ODDS_EVENTS, "odds_events.json", ODDS_CACHE_MIN,
                   params={"apiKey": api_key})
    event_id = None
    for g in ev:
        if g.get("home_team") == home_name and g.get("away_team") == away_name:
            event_id = g["id"]
            break
    if not event_id:
        return {}
    safe = f"props_{event_id}.json"
    data = _get_json(ODDS_EVENT_ODDS % event_id, safe, ODDS_CACHE_MIN, params={
        "apiKey": api_key, "regions": "us", "markets": PROP_MARKETS,
        "oddsFormat": "american"})
    raw = {}
    for bk in data.get("bookmakers", []):
        for m in bk.get("markets", []):
            mkt = raw.setdefault(m["key"], {})
            for o in m.get("outcomes", []):
                player = o.get("description")
                if not player or o.get("point") is None:
                    continue
                e = mkt.setdefault(player, {"points": [], "over": [], "under": []})
                e["points"].append(o["point"])
                if o.get("name") == "Over":
                    e["over"].append((o.get("price") or -110, bk.get("key")))
                else:
                    e["under"].append((o.get("price") or -110, bk.get("key")))
    out = {}
    for mkt, players in raw.items():
        out[mkt] = {}
        for player, e in players.items():
            out[mkt][player] = {
                "point": float(np_median(e["points"])),
                "over_price": max(e["over"])[0] if e["over"] else None,
                "over_book": max(e["over"])[1] if e["over"] else None,
                "under_price": max(e["under"])[0] if e["under"] else None,
                "under_book": max(e["under"])[1] if e["under"] else None,
                "n_books": len(e["points"]),
            }
    return out


def np_median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


NFLVERSE_INJ = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_%d.csv"

_PRACTICE_SHORT = {"Did Not Participate In Practice": "DNP",
                   "Limited Participation in Practice": "LP",
                   "Full Participation in Practice": "FP"}


def nflverse_injuries(season=None):
    """Official NFL injury report via nflverse. Returns {team: [rows]}, plus a label
    like '2025 W18 (REG)'. Falls back to prior season file if current not published."""
    games = load_games()
    if season is None:
        season = int(games.loc[games["result"].isna(), "season"].max())
    df = None
    for s in (season, season - 1):
        path = os.path.join(CACHE, f"nflverse_injuries_{s}.csv")
        if not _fresh(path, GAMES_CACHE_H * 3600):
            try:
                r = requests.get(NFLVERSE_INJ % s, timeout=60)
                if r.status_code == 200 and len(r.content) > 100:
                    with open(path, "wb") as f:
                        f.write(r.content)
                else:
                    continue
            except Exception:
                continue
        if os.path.exists(path):
            df = pd.read_csv(path)
            season = s
            break
    if df is None:
        return {}, "unavailable"
    out = {}
    for team, grp in df.groupby("team"):
        latest = grp[grp["week"] == grp["week"].max()]
        rows = []
        for _, r in latest.iterrows():
            status_v = r.get("report_status")
            detail_v = r.get("report_primary_injury")
            practice_v = r.get("practice_status")
            rows.append({
                "name": r["full_name"], "position": r.get("position", ""),
                "status": status_v if pd.notna(status_v) else "",
                "detail": detail_v if pd.notna(detail_v) else "",
                "practice": _PRACTICE_SHORT.get(practice_v, "") if pd.notna(practice_v) else "",
            })
        gt = latest.iloc[0].get("game_type", latest.iloc[0].get("season_type", "REG"))
        out[team] = {"rows": rows, "label": f"{season} W{int(latest.iloc[0]['week'])} ({gt})"}
    return out, "ok"


# The Odds API uses full team names; map to nflverse/ESPN abbreviations.
TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
