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
ESPN_NEWS = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
CBS_RSS = "https://www.cbssports.com/rss/headlines/nfl/"

# betting-relevant headline keywords (injuries + roster movement)
NEWS_INJURY_KW = ("injur", "placed on ir", "injured reserve", "activated", "waived", "waive",
                  "released", "release", "signed", "signs", "trade", "questionable", "doubtful",
                  " out ", "concussion", "hamstring", "ankle", "knee", "shoulder", "acl",
                  "achilles", "fracture", "sprain", "torn", "surgery", "suspend", "roster",
                  "cut ", "practice squad", "pup list", "returns", "return from")

GAMES_CACHE_H = 12
ESPN_CACHE_MIN = 10
ODDS_CACHE_MIN = 45  # free tier is 500 req/month -- be stingy
PROP_CACHE_MIN = 6 * 24 * 60  # player props: 6-day shared disk cache, warmed Mon+Sat by prop_warm.py cron (spread/total lines stay at 45 min)


def _fresh(path, max_age_sec):
    return os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age_sec


_MEMO = {}


def load_games():
    """Full nflverse schedule/results table, cached 12h on disk; memoized in
    memory by file mtime so repeat calls in one process are free.
    Derived ATS/O-U columns added."""
    path = os.path.join(CACHE, "games.csv")

    def _download():
        r = requests.get(GAMES_URL, timeout=60)
        r.raise_for_status()
        tmp = path + ".tmp"  # atomic: concurrent readers never see a partial file
        with open(tmp, "wb") as f:
            f.write(r.content)
        os.replace(tmp, path)

    if not _fresh(path, GAMES_CACHE_H * 3600):
        _download()
    mt = os.path.getmtime(path)
    df = _MEMO["games"] if _MEMO.get("games_mt") == mt else None
    # auto-refresh stale results: nflverse posts ~1h after finals. If any game is
    # >4h past kickoff with no result and the cache is >1h old, refetch (throttled
    # to 1 attempt/hour) so finals reach Completed without waiting out the 12h TTL.
    # This runs BEFORE the memo early-return — previously it sat behind it, was
    # dead code in steady state, and finals lagged up to 12h on long-lived
    # (cloud) processes.
    if time.time() - mt > 3600 and time.time() - _MEMO.get("games_refetch_ts", 0) > 3600:
        try:
            src = df if df is not None else pd.read_csv(path, low_memory=False)
            _gd = pd.to_datetime(src["gameday"], errors="coerce")
            _gt = src["gametime"].fillna("0:0").astype(str).str.split(":", expand=True)
            _ko = _gd + pd.to_timedelta(pd.to_numeric(_gt[0], errors="coerce").fillna(0), unit="h") \
                      + pd.to_timedelta(pd.to_numeric(_gt[1], errors="coerce").fillna(0), unit="m")
            _overdue = bool((src["result"].isna() & _gd.notna()
                             & (_ko < pd.Timestamp.now() - pd.Timedelta(hours=4))).any())
        except Exception:
            _overdue = False
        if _overdue:
            _MEMO["games_refetch_ts"] = time.time()
            try:
                _download()
                mt = os.path.getmtime(path)
                df = None  # force re-read + re-derive below
            except Exception:
                pass  # serve what we have — try again in an hour
    if df is not None:
        return df
    if _MEMO.get("games_mt") == mt:
        return _MEMO["games"]
    df = pd.read_csv(path, low_memory=False)
    # nflverse calls the Rams "LA"; the rest of the app (divisions, logos, ESPN) uses "LAR".
    # Without this the Rams silently miss standings, rankings, injury adj, and logos.
    df[["home_team", "away_team"]] = df[["home_team", "away_team"]].replace({"LA": "LAR"})
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
_ODDS_DOWN_UNTIL = 0.0  # same for The Odds API after a quota/auth failure (401/429)


def _get_json(url, cache_name, max_age_min, params=None, service=None, extra_headers=None):
    path = os.path.join(CACHE, cache_name)
    if service == "espn" and time.time() < _ESPN_DOWN_UNTIL:
        # circuit open (recent WAF ban): serve stale cache if we have one
        # instead of raising — degraded data beats a broken page
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        raise requests.HTTPError("ESPN circuit open (rate-limited recently)")
    if service != "espn" and time.time() < _ODDS_DOWN_UNTIL:
        # quota/auth breaker: a dead key must never cost retry-sleeps per call
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        raise requests.HTTPError("Odds API circuit open (quota/auth failure recently)")
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
            hdrs = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/126.0 Safari/537.36",
                    "Accept": "application/json",
                    "Referer": "https://www.espn.com/"}
            if extra_headers:
                hdrs.update(extra_headers)
            r = requests.get(url, params=params, timeout=15, headers=hdrs)
            r.raise_for_status()
            data = r.json()
            tmp = path + ".tmp"  # atomic: concurrent readers never see a partial file
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
            return data
        except Exception as e:
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if service == "espn" and status == 403:
                globals()["_ESPN_DOWN_UNTIL"] = time.time() + 1800
            if service != "espn" and status in (401, 429):
                # dead/exhausted key: retrying burns 9s of sleeps for nothing —
                # open the breaker for 6h and serve stale from now on
                globals()["_ODDS_DOWN_UNTIL"] = time.time() + 6 * 3600
                break
            if attempt < attempts - 1:
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


def espn_live_scores(season, week, seasontype=2):
    """Live/current scoreboard for a week (60s cache).
    [{label, away, home, a_score, h_score, state ('pre'|'in'|'post'), clock, period, detail}]"""
    try:
        data = _get_json(ESPN_SCOREBOARD, f"espn_live_{season}_{seasontype}_{week}.json", 1,
                         params={"dates": season, "seasontype": seasontype, "week": week,
                                 "limit": 100}, service="espn")
    except Exception:
        return []
    out = []
    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        st = comp.get("status", {})
        comps = {c["homeAway"]: c for c in comp["competitors"]}
        h, a = comps.get("home", {}), comps.get("away", {})
        out.append({
            "label": f"{a.get('team', {}).get('abbreviation', '?')} @ "
                     f"{h.get('team', {}).get('abbreviation', '?')}",
            "away": a.get("team", {}).get("abbreviation", "?"),
            "home": h.get("team", {}).get("abbreviation", "?"),
            "a_score": int(a.get("score", 0) or 0), "h_score": int(h.get("score", 0) or 0),
            "state": st.get("type", {}).get("state", "pre"),
            "clock": st.get("displayClock", ""), "period": st.get("period", 0),
            "detail": st.get("type", {}).get("shortDetail", ""),
        })
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


SGO_EVENTS = "https://api.sportsgameodds.com/v2/events/"
SGO_BOOKS = "draftkings,fanduel,betmgm,caesars,espnbet"  # verified on amateur tier (others 400)
SGO_CACHE_MIN = 120  # free tier = 2,500 objects/mo (~156 weekly-slate fetches) — be stingy


def sgo_api_key():
    """SportsGameOdds key: SGO_API_KEY env, st.secrets, or data/sgo_api_key.txt. '' if none."""
    k = os.environ.get("SGO_API_KEY", "").strip()
    if k:
        return k
    try:
        import streamlit as st
        k = (st.secrets.get("SGO_API_KEY") or "").strip()
        if k:
            return k
    except Exception:
        pass
    try:
        return open(os.path.join(CACHE, "sgo_api_key.txt")).read().strip()
    except Exception:
        return ""


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    f = _f(v)
    return int(f) if f is not None else None


def _sgo_event_books(e):
    """Parse one SGO event into ((away_long, home_long), books) or None."""
    home = ((e.get("teams") or {}).get("home") or {}).get("names", {}).get("long", "")
    away = ((e.get("teams") or {}).get("away") or {}).get("names", {}).get("long", "")
    if not home or not away:
        return None
    odds = e.get("odds") or {}

    def _bk(odd_id):
        return (odds.get(odd_id) or {}).get("byBookmaker") or {}

    sph, spa = _bk("points-home-game-sp-home"), _bk("points-away-game-sp-away")
    mlh, mla = _bk("points-home-game-ml-home"), _bk("points-away-game-ml-away")
    ovr, und = _bk("points-all-game-ou-over"), _bk("points-all-game-ou-under")
    books = {}
    for bk in set(sph) | set(spa) | set(mlh) | set(ovr):
        entry = {"title": bk}
        if bk in sph:
            entry["home_spread"] = _f(sph[bk].get("spread"))
            entry["home_spread_price"] = _i(sph[bk].get("odds"))
        if bk in spa:
            entry["away_spread"] = _f(spa[bk].get("spread"))
            entry["away_spread_price"] = _i(spa[bk].get("odds"))
        if bk in ovr:
            entry["total"] = _f(ovr[bk].get("overUnder"))
            entry["over_price"] = _i(ovr[bk].get("odds"))
        if bk in und:
            entry["under_price"] = _i(und[bk].get("odds"))
        if bk in mlh:
            entry["home_ml"] = _i(mlh[bk].get("odds"))
        if bk in mla:
            entry["away_ml"] = _i(mla[bk].get("odds"))
        books[bk] = entry
    return ((away, home), books) if books else None


SGO_PROP_STATS = {"passing_yards": "player_pass_yds", "rushing_yards": "player_rush_yds",
                  "receiving_yards": "player_reception_yds", "receptions": "player_receptions"}


def _sgo_event_props(e):
    """Player prop lines from one SGO event -> _parse_props shape
    {market: {player: {point (median), over/under price+book, n_books}}}.
    Props ride free inside the 16-object slate fetch — no extra objects."""
    players = e.get("players") or {}
    odds = e.get("odds") or {}
    raw = {}
    for o in odds.values():
        mkt = SGO_PROP_STATS.get(o.get("statID"))
        if not mkt or o.get("betTypeID") != "ou":
            continue
        name = (players.get(o.get("playerID") or "") or {}).get("name")
        if not name:
            continue
        ent = raw.setdefault((mkt, name), {"points": [], "over": [], "under": []})
        for bk, b in (o.get("byBookmaker") or {}).items():
            if b.get("available") is False:
                continue
            pt, pr = _f(b.get("overUnder")), _i(b.get("odds"))
            if pt is not None:
                ent["points"].append(pt)
            (ent["over"] if o.get("sideID") == "over" else ent["under"]).append(
                (pr if pr is not None else -110, bk))
    out = {}
    for (mkt, name), ent in raw.items():
        if not ent["points"]:
            continue
        out.setdefault(mkt, {})[name] = {
            "point": float(np_median(ent["points"])),
            "over_price": max(ent["over"])[0] if ent["over"] else None,
            "over_book": max(ent["over"])[1] if ent["over"] else None,
            "under_price": max(ent["under"])[0] if ent["under"] else None,
            "under_book": max(ent["under"])[1] if ent["under"] else None,
            "n_books": len(ent["points"]),
        }
    return out


def _sgo_board_raw():
    """The shared SGO board payload: Turso single-fetcher copy (<8h) first,
    then local disk (<SGO_CACHE_MIN). Returns (payload_dict, epoch) or (None, None).
    Memoized in-process by updated_at/mtime — the payload is ~19MB, so it is
    parsed once per change, never per call."""
    try:
        import db
        ts = db.cache_get_meta("sgo_board_pregame")
        if ts and (time.time() - ts) < 8 * 3600:
            if _MEMO.get("sgo_board_ts") == ts:
                return _MEMO["sgo_board"], ts
            payload, ts2 = db.cache_get("sgo_board_pregame")
            if payload:
                parsed = json.loads(payload)
                _MEMO["sgo_board"], _MEMO["sgo_board_ts"] = parsed, ts2
                return parsed, ts2
    except Exception:
        pass
    path = os.path.join(CACHE, "sgo_odds.json")
    if _fresh(path, SGO_CACHE_MIN * 60):
        try:
            mt = os.path.getmtime(path)
            if _MEMO.get("sgo_disk_mt") == mt:
                return _MEMO["sgo_disk"], mt
            with open(path) as f:
                parsed = json.load(f)
            _MEMO["sgo_disk"], _MEMO["sgo_disk_mt"] = parsed, mt
            return parsed, mt
        except Exception:
            pass
    return None, None


def sgo_push_shared(api_key):
    """WRITER (single-fetcher): fetch the SGO board (2h TTL) and push a
    KICKOFF-FROZEN payload into the Turso shared cache: pre-start events update
    normally; started events keep their last pre-start snapshot (SGO serves
    live in-game odds — the model must never compare itself to a 4th-quarter
    line)."""
    data = _get_json(SGO_EVENTS, "sgo_odds.json", SGO_CACHE_MIN, params={
        "leagueID": "NFL",
        "startsAfter": (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "startsBefore": (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 50, "bookmakerID": SGO_BOOKS},
        extra_headers={"x-api-key": api_key})
    import db
    prev_raw, _ = db.cache_get("sgo_board_pregame")
    prev_events = {}
    if prev_raw:
        try:
            for e in json.loads(prev_raw).get("data", []):
                prev_events[e.get("eventID")] = e
        except Exception:
            pass
    merged = []
    for e in (data.get("data", []) if isinstance(data, dict) else []):
        if (e.get("status") or {}).get("started"):
            prev_e = prev_events.get(e.get("eventID"))
            if prev_e is not None:
                merged.append(prev_e)          # frozen pre-game version
            else:
                merged.append(dict(e, odds={}))  # no pre-game snapshot: strip live lines
        else:
            merged.append(e)
    out = dict(data, data=merged) if isinstance(data, dict) else data
    db.cache_set("sgo_board_pregame", json.dumps(out))
    return len(merged)


def sgo_live_scores(api_key):
    """Live/in-progress + just-finished scores from SportsGameOdds — the ESPN
    fallback when their WAF bans us. Same shape as espn_live_scores.
    5-min shared disk cache; ~1 object per live event."""
    data = _get_json(SGO_EVENTS, "sgo_live.json", 5, params={
        "leagueID": "NFL", "live": "true", "limit": 25},
        extra_headers={"x-api-key": api_key})
    out = []
    for e in (data.get("data", []) if isinstance(data, dict) else []):
        st_ = e.get("status") or {}
        teams = e.get("teams") or {}
        h, a = teams.get("home") or {}, teams.get("away") or {}
        ha, aa = (h.get("names") or {}).get("short", "?"), (a.get("names") or {}).get("short", "?")
        period_raw = str(st_.get("currentPeriodID") or "").lower()   # "1q".."4q", "ot"
        period = "OT" if "ot" in period_raw else (period_raw[0] if period_raw[:1].isdigit() else "")
        state = "post" if (st_.get("completed") or st_.get("ended")) else "in"
        out.append({"label": f"{aa} @ {ha}", "away": aa, "home": ha,
                    "a_score": int(a.get("score") or 0), "h_score": int(h.get("score") or 0),
                    "state": state,
                    "clock": "", "period": period,
                    "detail": ("Final" if state == "post" else f"🔴 Q{period}".strip())})
    return out


def cached_sgo_lines():
    """Board lines from the shared payload (Turso/disk) — NO network, NO objects."""
    raw, _ = _sgo_board_raw()
    if not raw:
        return None
    out = {}
    for e in (raw.get("data", []) if isinstance(raw, dict) else []):
        parsed = _sgo_event_books(e)
        if parsed:
            out[parsed[0]] = parsed[1]
    return out


def sgo_lines(api_key):
    """Multi-book lines from SportsGameOdds — SAME output shape as odds_api_lines:
    {(away_long, home_long): {book: {title, home_spread, home_spread_price,
    away_spread, away_spread_price, total, over_price, under_price,
    home_ml, away_ml}}}. Per-event pricing: ~16 objects per weekly slate.

    Lines FREEZE at kickoff: SGO serves live in-game odds, so any event whose
    status.started is true keeps its books from the previous cache snapshot —
    the model must always compare itself to a pre-game line, never a 4th-
    quarter one."""
    cache_path = os.path.join(CACHE, "sgo_odds.json")
    prev = {}
    try:  # read the PREVIOUS snapshot before _get_json may overwrite it
        with open(cache_path) as f:
            prev_raw = json.load(f)
        for e in (prev_raw.get("data", []) if isinstance(prev_raw, dict) else []):
            parsed = _sgo_event_books(e)
            if parsed:
                prev[parsed[0]] = parsed[1]
    except Exception:
        pass
    now = pd.Timestamp.now(tz="UTC")
    data = _get_json(SGO_EVENTS, "sgo_odds.json", SGO_CACHE_MIN, params={
        "leagueID": "NFL",
        "startsAfter": (now - pd.Timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "startsBefore": (now + pd.Timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 50, "bookmakerID": SGO_BOOKS},
        extra_headers={"x-api-key": api_key})
    events = data.get("data", []) if isinstance(data, dict) else data
    out = {}
    for e in events:
        parsed = _sgo_event_books(e)
        if not parsed:
            continue
        key, books = parsed
        if (e.get("status") or {}).get("started") and key in prev:
            out[key] = prev[key]  # frozen pre-game line — never a live one
        else:
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
                    tmp = path + ".tmp"  # atomic: concurrent readers never see a partial file
                    with open(tmp, "wb") as f:
                        f.write(r.content)
                    os.replace(tmp, path)
                else:
                    continue
            except Exception:
                continue
        if os.path.exists(path):
            frames.append(pd.read_csv(path, usecols=lambda c: c in _PS_COLS,
                                      low_memory=False))
    if not frames:
        raise RuntimeError("player stats unavailable")
    ps = pd.concat(frames, ignore_index=True)
    # nflverse player stats use 'LA' for the Rams; the rest of the app uses 'LAR'
    # (mirrors the load_games normalization) — without this, Rams projections
    # silently return empty
    ps["team"] = ps["team"].replace({"LA": "LAR"})
    ps["opponent_team"] = ps["opponent_team"].replace({"LA": "LAR"})
    return ps


ODDS_EVENTS = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events"
ODDS_EVENT_ODDS = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/%s/odds/"
PROP_MARKETS = "player_pass_yds,player_rush_yds,player_reception_yds,player_receptions"


def _event_id_for(away_name, home_name, ev):
    for g in ev:
        if g.get("home_team") == home_name and g.get("away_team") == away_name:
            return g["id"]
    return None


def _parse_props(data):
    """Raw event-odds payload -> {market: {player: {point, prices, books}}}.
    Line = median across books; prices = best available."""
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


def _props_cache_path(event_id):
    return os.path.join(CACHE, f"props_{event_id}.json")


def odds_api_event_props(api_key, away_name, home_name):
    """Player prop lines for ONE game (event-level; ~4 credits on a real fetch).
    Cached 24h on disk and shared by all users — the first load of the day is the
    only one that spends quota. Returns {} when no props are posted yet."""
    ev = _get_json(ODDS_EVENTS, "odds_events.json", PROP_CACHE_MIN,
                   params={"apiKey": api_key})
    event_id = _event_id_for(away_name, home_name, ev)
    if not event_id:
        return {}
    data = _get_json(ODDS_EVENT_ODDS % event_id, f"props_{event_id}.json", PROP_CACHE_MIN,
                     params={"apiKey": api_key, "regions": "us", "markets": PROP_MARKETS,
                             "oddsFormat": "american"})
    parsed = _parse_props(data)
    try:  # single-fetcher: share this fetch with every environment via Turso
        import db
        db.cache_set(f"props:{away_name}@{home_name}", json.dumps(parsed))
    except Exception:
        pass
    return parsed


def cached_event_props(away_name, home_name):
    """Prop lines for one game, NO network/credits. Returns (props_dict, epoch)
    or (None, None). Chain: SGO shared board (props ride the slate fetch) ->
    Turso single-fetcher copy of legacy Odds-API props -> local disk cache."""
    # 1) SGO shared board — covers every env (Cloud included) with zero extra spend
    raw, ts = _sgo_board_raw()
    if raw:
        for e in (raw.get("data", []) if isinstance(raw, dict) else []):
            h = ((e.get("teams") or {}).get("home") or {}).get("names", {}).get("long", "")
            a = ((e.get("teams") or {}).get("away") or {}).get("names", {}).get("long", "")
            if (a, h) == (away_name, home_name):
                props = _sgo_event_props(e)
                if props:
                    return props, ts
    # 2) Turso copy of legacy Odds-API props (name-keyed, no event_id needed)
    try:
        import db
        payload, ts2 = db.cache_get(f"props:{away_name}@{home_name}")
        if payload and ts2 and (time.time() - ts2) < PROP_CACHE_MIN * 60:
            return json.loads(payload), ts2
    except Exception:
        pass
    # 3) legacy local disk cache
    try:
        with open(os.path.join(CACHE, "odds_events.json")) as f:
            ev = json.load(f)
        event_id = _event_id_for(away_name, home_name, ev)
        if not event_id:
            return None, None
        path = _props_cache_path(event_id)
        if not _fresh(path, PROP_CACHE_MIN * 60):
            return None, None
        with open(path) as f:
            return _parse_props(json.load(f)), os.path.getmtime(path)
    except Exception:
        return None, None


def bust_event_props_cache(away_name, home_name):
    """Delete a game's cached prop lines — the next load fetches fresh from the API.
    Returns True when a cache file was actually removed."""
    try:
        with open(os.path.join(CACHE, "odds_events.json")) as f:
            ev = json.load(f)
        event_id = _event_id_for(away_name, home_name, ev)
        if event_id:
            path = _props_cache_path(event_id)
            if os.path.exists(path):
                os.remove(path)
                return True
    except Exception:
        pass
    return False


def np_median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


NFLVERSE_INJ = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_%d.csv"

_PRACTICE_SHORT = {"Did Not Participate In Practice": "DNP",
                   "Limited Participation in Practice": "LP",
                   "Full Participation in Practice": "FP"}


def nflverse_injuries(season=None, max_age_h=1):
    """Official NFL injury report via nflverse. Returns {team: [rows]}, plus a label
    like '2025 W18 (REG)'. Falls back to prior season file if current not published.
    max_age_h controls disk-cache freshness — the Injury Report Watch passes 0.5h
    so report drops surface within one 30-min tick instead of up to 12h."""
    games = load_games()
    if season is None:
        season = int(games.loc[games["result"].isna(), "season"].max())
    # Never serve last season's file once the current season has started — a failed
    # fetch must surface as "unavailable", not as ancient mislabeled data (the 2026
    # file 404'd once mid-week and the app briefly showed 2025 playoff injuries).
    sg = games[games["season"] == season]
    started = bool(sg["result"].notna().any()) or \
        bool((pd.to_datetime(sg["gameday"], errors="coerce") <= pd.Timestamp.now()).any())
    df = None
    for s in ((season,) if started else (season, season - 1)):
        path = os.path.join(CACHE, f"nflverse_injuries_{s}.csv")
        if not _fresh(path, max_age_h * 3600):
            try:
                r = requests.get(NFLVERSE_INJ % s, timeout=60)
                if r.status_code == 200 and len(r.content) > 100:
                    tmp = path + ".tmp"  # atomic: concurrent readers never see a partial file
                    with open(tmp, "wb") as f:
                        f.write(r.content)
                    os.replace(tmp, path)
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
        # nflverse calls the Rams "LA"; the rest of the app uses "LAR" (same fix as load_games)
        out["LAR" if team == "LA" else team] = {"rows": rows, "label": f"{season} W{int(latest.iloc[0]['week'])} ({gt})"}
    return out, "ok"


# The Odds API uses full team names; map to nflverse/ESPN abbreviations.
TEAM_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


# ---------------- news feeds ----------------
def espn_news(limit=50):
    """ESPN league news (JSON). [{title, desc, link, published, source}]"""
    out = []
    try:
        data = _get_json(ESPN_NEWS, "espn_news.json", 15, params={"limit": limit}, service="espn")
        for a in data.get("articles", []):
            link = (a.get("links", {}).get("web", {}) or {}).get("href", "")
            imgs = a.get("images", [])
            out.append({"title": a.get("headline", ""), "desc": a.get("description", ""),
                        "link": link, "published": a.get("published", ""), "source": "ESPN",
                        "img": imgs[0].get("url", "") if imgs else ""})
    except Exception:
        pass
    return out


def cbs_news():
    """CBS Sports NFL RSS feed (stdlib XML parse, 15-min disk cache)."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    out = []
    path = os.path.join(CACHE, "cbs_news.xml")
    try:
        if not _fresh(path, 15 * 60):
            r = requests.get(CBS_RSS, timeout=20,
                             headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                      "AppleWebKit/537.36"})
            r.raise_for_status()
            with open(path, "w") as f:
                f.write(r.text)
        root = ET.parse(path).getroot()
        for item in root.iter("item"):
            pub = item.findtext("pubDate", "")
            try:
                pub = parsedate_to_datetime(pub).isoformat()
            except Exception:
                pass
            img = ""
            enc = item.find("enclosure")
            if enc is not None:
                img = enc.get("url", "")
            out.append({"title": (item.findtext("title") or "").strip(),
                        "desc": (item.findtext("description") or "").strip()[:280],
                        "link": (item.findtext("link") or "").strip(),
                        "published": pub, "source": "CBS", "img": img})
    except Exception:
        pass
    return out


def merged_news(limit=40):
    """ESPN + CBS merged, deduped by title, newest first."""
    seen, items = set(), []
    for it in espn_news() + cbs_news():
        key = " ".join(it["title"].lower().split())[:80]
        if it["title"] and key not in seen:
            seen.add(key)
            items.append(it)
    items.sort(key=lambda x: x.get("published", ""), reverse=True)
    return items[:limit]


def is_injury_news(item):
    txt = (item["title"] + " " + item.get("desc", "")).lower()
    return any(k in txt for k in NEWS_INJURY_KW)
