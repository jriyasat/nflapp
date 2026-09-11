"""Stateful storage for NFL Edge Finder: SQLite.

- bets: per-user bet journal (user column; private per login)
- predictions: global model pick log (shared across users)

Local dev: file at data/nfl_edge.db.
Cloud deploy: _connect() is the single seam to swap to a hosted SQLite
(Turso/libsql) via env vars NFL_EDGE_TURSO_URL / NFL_EDGE_TURSO_TOKEN.
Migrates legacy data/bets.csv + data/predictions.csv on first run.
"""

import json
import os
import sqlite3
import time
import uuid

import pandas as pd

import data as dl

DB_PATH = os.path.join(dl.CACHE, "nfl_edge.db")

_BETS_COLS = ["id", "user", "date", "season", "week", "game", "bet_type",
              "selection", "line", "odds", "stake", "book", "status", "profit", "clv"]
_PICKS_COLS = ["id", "logged_at", "season", "week", "game", "pick_type", "side",
               "model_val", "market_val_log", "edge_log", "p_cover_log",
               "closing_line", "grade", "profit"]

_TURSO_CLIENT = None
_TURSO_SCHEMA_DONE = False


def _turso_cfg():
    """Turso credentials from env or .streamlit/secrets.toml. Returns (url, token)."""
    url = os.environ.get("NFL_EDGE_TURSO_URL")
    token = os.environ.get("NFL_EDGE_TURSO_TOKEN")
    if not (url and token):
        try:
            import tomllib
            sp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              ".streamlit", "secrets.toml")
            if os.path.exists(sp):
                with open(sp, "rb") as f:
                    s = tomllib.load(f)
                url = url or s.get("NFL_EDGE_TURSO_URL")
                token = token or s.get("NFL_EDGE_TURSO_TOKEN")
        except Exception:
            pass
    if url and token:
        return url.replace("libsql://", "https://"), token
    return None, None


class _TursoCursor:
    def __init__(self, rs):
        self._rows = rs.rows

    def fetchall(self):
        return [tuple(r) for r in self._rows]

    def fetchone(self):
        return tuple(self._rows[0]) if self._rows else None


class _TursoConn:
    """sqlite3-shaped adapter over libsql_client (shared underlying client)."""

    def __init__(self, client):
        self._c = client

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass  # shared client; never close per-call

    def execute(self, sql, params=()):
        return _TursoCursor(self._c.execute(sql, params))


_SCHEMA = ["""CREATE TABLE IF NOT EXISTS bets (
    id TEXT PRIMARY KEY, user TEXT NOT NULL, date TEXT, season INT, week INT,
    game TEXT, bet_type TEXT, selection TEXT, line REAL, odds REAL,
    stake REAL, book TEXT, status TEXT DEFAULT 'pending',
    profit REAL, clv REAL)""",
    """CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY, logged_at TEXT, season INT, week INT, game TEXT,
    pick_type TEXT, side TEXT, model_val REAL, market_val_log REAL,
    edge_log REAL, p_cover_log REAL, closing_line REAL,
    grade TEXT DEFAULT 'pending', profit REAL,
    UNIQUE(game, pick_type))""",
    "CREATE INDEX IF NOT EXISTS idx_bets_user ON bets(user)",
    """CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, name TEXT, email TEXT,
    level TEXT DEFAULT 'user', pw_hash TEXT, created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS line_history (
    game TEXT, ts TEXT, spread_away REAL, total REAL)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_lh ON line_history(game, ts)",
    """CREATE TABLE IF NOT EXISTS pickem (
    id TEXT PRIMARY KEY, user TEXT, season INT, week INT, game TEXT,
    pick TEXT, line REAL, created_at TEXT, grade TEXT DEFAULT 'pending')""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_pickem ON pickem(user, season, week, game)",
    """CREATE TABLE IF NOT EXISTS usage_counters (
    user TEXT, day TEXT, kind TEXT, n INT DEFAULT 0)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_usage ON usage_counters(user, day, kind)",
    """CREATE TABLE IF NOT EXISTS parlays (
    id TEXT PRIMARY KEY, user TEXT, kind TEXT DEFAULT 'parlay',
    combined_odds REAL, stake REAL, book TEXT,
    status TEXT DEFAULT 'pending', profit REAL, created_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS parlay_legs (
    id TEXT PRIMARY KEY, parlay_id TEXT, season INT, week INT, game TEXT, bet_type TEXT,
    selection TEXT, line REAL, leg_odds REAL, closing_line REAL,
    grade TEXT DEFAULT 'pending', created_at TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_legs_parlay ON parlay_legs(parlay_id)"]


def _connect():
    url, token = _turso_cfg()
    if url:
        global _TURSO_CLIENT, _TURSO_SCHEMA_DONE
        if _TURSO_CLIENT is None:
            import libsql_client
            _TURSO_CLIENT = libsql_client.create_client_sync(url, auth_token=token)
        conn = _TursoConn(_TURSO_CLIENT)
        if not _TURSO_SCHEMA_DONE:
            for stmt in _SCHEMA:
                conn.execute(stmt)
            _ensure_user_cols(conn)
            _TURSO_SCHEMA_DONE = True
        return conn
    conn = sqlite3.connect(DB_PATH)
    for stmt in _SCHEMA:
        conn.execute(stmt)
    _ensure_user_cols(conn)
    return conn


def _ensure_user_cols(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    for col, ddl in (("email_enabled", "INTEGER DEFAULT 0"),
                     ("telegram_enabled", "INTEGER DEFAULT 0"),
                     ("telegram_chat_id", "TEXT"),
                     ("alert_prefs", "TEXT"),
                     ("bankroll", "REAL"), ("unit", "REAL")):
        if col not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")


# ---------------- per-user alert preferences (matrix: alert x channel) ----------------
ALERT_TYPES = {"brief": "☀️ Morning Brief (8 AM)",
               "radar": "🚨 Value Radar (line moves)",
               "inactives": "🚫 Gameday Inactives",
               "injury": "🏥 Injury Report Watch",
               "propscan": "🎯 Prop Scan (Thursday)"}
ALERT_CHANNELS = ("off", "telegram", "email", "both")


def _default_alert_prefs(email_enabled, telegram_enabled):
    """Mirror pre-matrix behavior: brief + inactives on whichever channels were
    enabled; everything else opt-in (off)."""
    ch = ("both" if email_enabled and telegram_enabled
          else "email" if email_enabled
          else "telegram" if telegram_enabled else "off")
    return {"brief": ch, "radar": "off", "inactives": ch, "injury": "off", "propscan": "off"}


def get_alert_prefs(username):
    with _connect() as c:
        r = c.execute("SELECT alert_prefs, email_enabled, telegram_enabled"
                      " FROM users WHERE username=?", (username,)).fetchone()
    if not r:
        return _default_alert_prefs(0, 0)
    prefs = _default_alert_prefs(r[1] or 0, r[2] or 0)
    if r[0]:
        try:
            prefs.update({k: v for k, v in json.loads(r[0]).items()
                          if k in ALERT_TYPES and v in ALERT_CHANNELS})
        except Exception:
            pass
    return prefs


def set_alert_pref(username, alert, channel):
    if alert not in ALERT_TYPES or channel not in ALERT_CHANNELS:
        return
    prefs = get_alert_prefs(username)
    prefs[alert] = channel
    with _connect() as c:
        c.execute("UPDATE users SET alert_prefs=? WHERE username=?",
                  (json.dumps(prefs), username))


def users_for_alert(alert, channel):
    """Users whose pref for `alert` includes `channel` ('telegram'/'email';
    'both' counts as each). Returns full user dicts for the fan-out."""
    out = []
    with _connect() as c:
        rows = c.execute(
            "SELECT username, name, email, email_enabled, telegram_enabled,"
            " telegram_chat_id, alert_prefs FROM users").fetchall()
    for uname, name, email, ee, te, chat_id, raw in rows:
        prefs = _default_alert_prefs(ee or 0, te or 0)
        if raw:
            try:
                prefs.update(json.loads(raw))
            except Exception:
                pass
        if prefs.get(alert) in (channel, "both"):
            out.append({"username": uname, "name": name, "email": email,
                        "telegram_chat_id": chat_id,
                        "email_enabled": ee, "telegram_enabled": te})
    return out


def migrate_legacy():
    """One-time import of bets.csv / predictions.csv if tables are empty."""
    with _connect() as c:
        if c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0:
            path = os.path.join(dl.CACHE, "predictions.csv")
            if os.path.exists(path):
                df = pd.read_csv(path)
                for _, r in df.iterrows():
                    c.execute("""INSERT OR IGNORE INTO predictions
                        (id, logged_at, season, week, game, pick_type, side,
                         model_val, market_val_log, edge_log, p_cover_log,
                         closing_line, grade, profit)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (r.get("id") or uuid.uuid4().hex[:8], r["logged_at"],
                         r["season"], r["week"], r["game"], r["pick_type"], r["side"],
                         r["model_val"], r["market_val_log"], r["edge_log"],
                         r.get("p_cover_log"), r.get("closing_line"),
                         r.get("grade", "pending"), r.get("profit")))
        if c.execute("SELECT COUNT(*) FROM bets").fetchone()[0] == 0:
            path = os.path.join(dl.CACHE, "bets.csv")
            if os.path.exists(path):
                df = pd.read_csv(path)
                for _, r in df.iterrows():
                    c.execute("""INSERT OR IGNORE INTO bets
                        (id, user, date, season, week, game, bet_type, selection,
                         line, odds, stake, book, status, profit, clv)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (r.get("id") or uuid.uuid4().hex[:8], "jeff", r.get("date"),
                         r["season"], r["week"], r["game"], r["bet_type"],
                         r["selection"], r.get("line"), r.get("odds"), r.get("stake"),
                         r.get("book"), r.get("status", "pending"),
                         r.get("profit"), r.get("clv")))


migrate_legacy()


# ---------------- users (admin-managed) ----------------
def list_users():
    with _connect() as c:
        rows = c.execute(
            "SELECT username, name, email, level, created_at, email_enabled,"
            " telegram_enabled, telegram_chat_id FROM users ORDER BY created_at"
        ).fetchall()
    return [{"username": u, "name": n, "email": e, "level": l, "created_at": t,
             "email_enabled": ee, "telegram_enabled": te, "telegram_chat_id": tc}
            for u, n, e, l, t, ee, te, tc in rows]


def get_user(username):
    with _connect() as c:
        r = c.execute("SELECT username, name, email, level, pw_hash, email_enabled,"
                      " telegram_enabled, telegram_chat_id, bankroll, unit FROM users WHERE username=?",
                      (username,)).fetchone()
    if not r:
        return None
    return {"username": r[0], "name": r[1], "email": r[2], "level": r[3],
            "pw_hash": r[4], "email_enabled": r[5], "telegram_enabled": r[6],
            "telegram_chat_id": r[7], "bankroll": r[8] if len(r) > 8 else None,
            "unit": r[9] if len(r) > 9 else None}


def update_email(username, email):
    with _connect() as c:
        c.execute("UPDATE users SET email=? WHERE username=?", (email, username))


def update_prefs(username, email_enabled=None, telegram_enabled=None):
    with _connect() as c:
        if email_enabled is not None:
            c.execute("UPDATE users SET email_enabled=? WHERE username=?",
                      (int(email_enabled), username))
        if telegram_enabled is not None:
            c.execute("UPDATE users SET telegram_enabled=? WHERE username=?",
                      (int(telegram_enabled), username))


def update_bankroll(username, bankroll, unit):
    with _connect() as c:
        c.execute("UPDATE users SET bankroll=?, unit=? WHERE username=?",
                  (bankroll, unit, username))


def link_telegram(username, chat_id):
    with _connect() as c:
        c.execute("UPDATE users SET telegram_chat_id=? WHERE username=?",
                  (chat_id, username))


# ---------------- line movement history ----------------
def append_line_history(game, spread_away, total, ts):
    with _connect() as c:
        c.execute("INSERT OR IGNORE INTO line_history (game, ts, spread_away, total)"
                  " VALUES (?,?,?,?)", (game, ts, spread_away, total))


def line_history(game):
    with _connect() as c:
        rows = c.execute("SELECT ts, spread_away, total FROM line_history"
                         " WHERE game=? ORDER BY ts", (game,)).fetchall()
    return pd.DataFrame(rows, columns=["ts", "spread_away", "total"])


# ---------------- usage counters (per-user daily quotas) ----------------
def usage_today(user, kind):
    day = time.strftime("%Y-%m-%d")
    with _connect() as c:
        r = c.execute("SELECT n FROM usage_counters WHERE user=? AND day=? AND kind=?",
                      (user, day, kind)).fetchone()
    return r[0] if r else 0


def bump_usage(user, kind):
    day = time.strftime("%Y-%m-%d")
    with _connect() as c:
        c.execute("INSERT INTO usage_counters (user, day, kind, n) VALUES (?,?,?,1)"
                  " ON CONFLICT(user, day, kind) DO UPDATE SET n = n + 1", (user, day, kind))


# ---------------- pick'em league ----------------
PICK_LOCK = pd.Timedelta(minutes=5)  # picks lock 5 min before kickoff (server-enforced)

def save_pickem(user, season, week, game, pick, line):
    # numpy int64 from the games df serializes as a BLOB in libsql — coerce to
    # plain int or rows become invisible to integer queries (the "model picks" bug)
    season, week = int(season), int(week)
    # server-side kickoff lock (UI buttons alone are not enforcement)
    try:
        games = dl.load_games()
        away, home = game.split(" @ ")
        m = games[(games["season"] == season) & (games["week"] == week)
                  & (games["away_team"] == away) & (games["home_team"] == home)]
        if not m.empty:
            g = m.iloc[0]
            gt = str(g.get("gametime", "13:00"))
            hh, mm = int(gt.split(":")[0]), int(gt.split(":")[1])
            kickoff = g["gameday"] + pd.Timedelta(hours=hh, minutes=mm)
            if pd.Timestamp.now() > kickoff - PICK_LOCK:
                raise ValueError(f"picks locked 5 min before kickoff ({game})")
    except ValueError:
        raise
    except Exception:
        pass  # data lookup failed → allow; UI still guards
    with _connect() as c:
        # INSERT OR REPLACE = re-picking overwrites side AND line (last change wins)
        c.execute("INSERT OR REPLACE INTO pickem (id, user, season, week, game, pick, line, created_at, grade)"
                  " VALUES (?,?,?,?,?,?,?,?, COALESCE((SELECT grade FROM pickem WHERE user=? AND season=? AND week=? AND game=?), 'pending'))",
                  (str(uuid.uuid4())[:8], user, season, week, game, pick, line,
                   time.strftime("%Y-%m-%d %H:%M"), user, season, week, game))


def delete_pickem(user, season, week, game):
    """Remove a pick (frees a slot in the 5). Same 5-min lock as saving."""
    season, week = int(season), int(week)
    try:
        games = dl.load_games()
        away, home = game.split(" @ ")
        m = games[(games["season"] == season) & (games["week"] == week)
                  & (games["away_team"] == away) & (games["home_team"] == home)]
        if not m.empty:
            g = m.iloc[0]
            gt = str(g.get("gametime", "13:00"))
            hh, mm = int(gt.split(":")[0]), int(gt.split(":")[1])
            kickoff = g["gameday"] + pd.Timedelta(hours=hh, minutes=mm)
            if pd.Timestamp.now() > kickoff - PICK_LOCK:
                raise ValueError(f"picks locked 5 min before kickoff ({game})")
    except ValueError:
        raise
    except Exception:
        pass  # data lookup failed → allow; UI still guards
    with _connect() as c:
        c.execute("DELETE FROM pickem WHERE user=? AND season=? AND week=? AND game=?",
                  (user, season, week, game))


def load_pickem(user, season, week):
    season, week = int(season), int(week)
    with _connect() as c:
        rows = c.execute("SELECT game, pick, line, grade, created_at FROM pickem"
                         " WHERE user=? AND season=? AND week=?", (user, season, week)).fetchall()
    return pd.DataFrame(rows, columns=["game", "pick", "line", "grade", "created_at"])


def load_pickem_week(season, week):
    season, week = int(season), int(week)
    with _connect() as c:
        rows = c.execute("SELECT user, game, pick, line, grade FROM pickem"
                         " WHERE season=? AND week=?", (season, week)).fetchall()
    return pd.DataFrame(rows, columns=["user", "game", "pick", "line", "grade"])


def grade_pickem(games, season, week):
    """Grade pending picks for a completed week (team-perspective line: neg = favorite)."""
    season, week = int(season), int(week)
    wk = games[(games["season"] == season) & (games["week"] == week)
               & games["result"].notna()]
    if wk.empty:
        return
    with _connect() as c:
        pending = c.execute("SELECT id, game, pick, line FROM pickem"
                            " WHERE season=? AND week=? AND grade='pending'",
                            (season, week)).fetchall()
        for pid, game, pick, line in pending:
            try:
                away, home = game.split(" @ ")
                m = wk[(wk["away_team"] == away) & (wk["home_team"] == home)]
                if m.empty:
                    continue
                res = float(m.iloc[0]["result"])  # home margin
                margin = res if pick == home else -res
                diff = margin + (line or 0)
                grade = "won" if diff > 0 else ("lost" if diff < 0 else "push")
                c.execute("UPDATE pickem SET grade=? WHERE id=?", (grade, pid))
            except Exception:
                continue


def pickem_leaderboard(season):
    season = int(season)
    with _connect() as c:
        rows = c.execute("SELECT user, grade FROM pickem WHERE season=? AND grade != 'pending'",
                         (season,)).fetchall()
    if not rows:
        return []
    board = {}
    for user, grade in rows:
        b = board.setdefault(user, {"w": 0, "l": 0, "p": 0})
        b[{"won": "w", "lost": "l", "push": "p"}[grade]] += 1
    out = [{"user": u, "record": f"{b['w']}-{b['l']}-{b['p']}",
            "win_pct": b["w"] / (b["w"] + b["l"]) if (b["w"] + b["l"]) else 0.0,
            "wins": b["w"]} for u, b in board.items()]
    return sorted(out, key=lambda r: (-r["win_pct"], -r["wins"]))


# ---------------- parlays & round robins ----------------
def _american_to_dec(v):
    v = float(v)
    return 1 + (v / 100 if v > 0 else 100 / abs(v))

def save_parlay(user, legs, combined_odds, stake, book, kind="parlay"):
    pid = str(uuid.uuid4())[:8]
    now = time.strftime("%Y-%m-%d %H:%M")
    with _connect() as c:
        c.execute("INSERT INTO parlays (id, user, kind, combined_odds, stake, book, status, created_at)"
                  " VALUES (?,?,?,?,?,?,'pending',?)",
                  (pid, user, kind, combined_odds, stake, book, now))
        for leg in legs:
            c.execute("INSERT INTO parlay_legs"
                      " (id, parlay_id, season, week, game, bet_type, selection, line, leg_odds, grade, created_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?,'pending',?)",
                      (str(uuid.uuid4())[:8], pid, leg.get("season"), leg.get("week"),
                       leg["game"], leg["bet_type"], leg["selection"], leg.get("line"),
                       leg.get("odds"), now))
    return pid

def load_parlays(user):
    with _connect() as c:
        heads = c.execute("SELECT id, kind, combined_odds, stake, book, status, profit, created_at"
                          " FROM parlays WHERE user=? ORDER BY created_at DESC", (user,)).fetchall()
        out = []
        for pid, kind, co, stake, book, status, profit, ts in heads:
            legs = c.execute("SELECT game, bet_type, selection, line, leg_odds, closing_line, grade,"
                             " season, week FROM parlay_legs WHERE parlay_id=?", (pid,)).fetchall()
            out.append({"id": pid, "kind": kind, "combined_odds": co, "stake": stake, "book": book,
                        "status": status, "profit": profit, "created_at": ts,
                        "legs": [{"game": g, "bet_type": bt, "selection": s, "line": ln,
                                  "odds": lo, "closing_line": cl, "grade": gr,
                                  "season": se, "week": wk}
                                 for g, bt, s, ln, lo, cl, gr, se, wk in legs]})
        return out

def _grade_leg(games, leg):
    """Grade one leg against game result; also capture closing line (CLV per leg).
    Returns (grade, closing_line) or (None, None) if no result yet."""
    try:
        away, home = leg["game"].split(" @ ")
        m = games[(games["away_team"] == away) & (games["home_team"] == home)
                  & games["result"].notna()]
        if leg.get("season") is not None and leg.get("week") is not None:
            m = m[(m["season"] == int(leg["season"])) & (m["week"] == int(leg["week"]))]
        if m.empty:
            return None, None
        g = m.iloc[-1]  # latest meeting as fallback for legacy legs without season/week
        bt, sel, line = leg["bet_type"], leg["selection"], leg["line"]
        if bt == "total":
            if pd.isna(g["total_line"]):
                return None, None
            tot = float(g["total"])
            diff = (tot - line) if sel == "over" else (line - tot)
            closing = float(g["total_line"])
        elif bt == "ml":
            margin = float(g["result"]) if sel == home else -float(g["result"])
            diff = margin
            closing = None  # ml legs: no spread CLV
        else:  # spread, team-perspective line
            if pd.isna(g["spread_line"]):
                return None, None
            margin = float(g["result"]) if sel == home else -float(g["result"])
            diff = margin + float(line or 0)
            closing = float(g["spread_line"]) if sel == away else -float(g["spread_line"])
        grade = "won" if diff > 0 else ("lost" if diff < 0 else "push")
        return grade, closing
    except Exception:
        return None, None

def settle_parlays(games, user):
    """Grade pending legs; settle tickets when all legs decided.
    Push legs drop out; ticket reprices from remaining legs (standard house rule)."""
    for pl in load_parlays(user):
        if pl["status"] != "pending":
            continue
        if pl["kind"] == "round_robin":
            continue  # RR settles manually via settle_rr()
        with _connect() as c:
            for leg in pl["legs"]:
                if leg["grade"] != "pending":
                    continue
                grade, closing = _grade_leg(games, leg)
                if grade:
                    c.execute("UPDATE parlay_legs SET grade=?, closing_line=?"
                              " WHERE parlay_id=? AND game=? AND bet_type=? AND selection=?",
                              (grade, closing, pl["id"], leg["game"], leg["bet_type"], leg["selection"]))
                    leg["grade"], leg["closing_line"] = grade, closing
        grades = [l["grade"] for l in pl["legs"]]
        if any(gr == "pending" for gr in grades):
            continue
        active = [l for l in pl["legs"] if l["grade"] != "push"]
        if any(l["grade"] == "lost" for l in pl["legs"]):
            status, profit = "lost", -float(pl["stake"])
        elif not active:
            status, profit = "push", 0.0
        else:
            status = "won"
            if len(active) == len(pl["legs"]) and pl["combined_odds"] is not None:
                dec = _american_to_dec(pl["combined_odds"])
            else:  # pushes happened (or no manual price): reprice from leg odds
                dec = 1.0
                for l in active:
                    dec *= _american_to_dec(l["leg_odds"] or -110)
            profit = float(pl["stake"]) * (dec - 1)
        with _connect() as c:
            c.execute("UPDATE parlays SET status=?, profit=? WHERE id=?", (status, profit, pl["id"]))
    return load_parlays(user)

def settle_rr(parlay_id, result, payout):
    """Simplified round robin: one manual result for the whole ticket."""
    with _connect() as c:
        if result == "won":
            c.execute("UPDATE parlays SET status='won', profit=? WHERE id=?", (float(payout), parlay_id))
        else:
            c.execute("UPDATE parlays SET status='lost', profit=-stake WHERE id=?", (parlay_id,))

def delete_parlay(parlay_id):
    with _connect() as c:
        c.execute("DELETE FROM parlay_legs WHERE parlay_id=?", (parlay_id,))
        c.execute("DELETE FROM parlays WHERE id=?", (parlay_id,))


def admin_count():
    with _connect() as c:
        return c.execute("SELECT COUNT(*) FROM users WHERE level='admin'").fetchone()[0]


def add_user(username, name, email, level, pw_hash):
    with _connect() as c:
        c.execute("INSERT OR REPLACE INTO users (username, name, email, level, pw_hash, created_at)"
                  " VALUES (?,?,?,?,?,?)",
                  (username, name, email, level, pw_hash,
                   pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")))
    _creds_invalidate()


def delete_user(username):
    with _connect() as c:
        c.execute("DELETE FROM users WHERE username=?", (username,))
        c.execute("DELETE FROM bets WHERE user=?", (username,))  # deletes everything
    _creds_invalidate()


def set_password(username, pw_hash):
    with _connect() as c:
        c.execute("UPDATE users SET pw_hash=? WHERE username=?", (pw_hash, username))
    _creds_invalidate()


LEVELS = ("user", "paid", "admin")


def set_level(username, level):
    """user = free tier, paid = full features, admin = full + admin pages."""
    assert level in LEVELS, f"bad level {level!r}"
    with _connect() as c:
        c.execute("UPDATE users SET level=? WHERE username=?", (level, username))
    _creds_invalidate()


def user_level(username):
    """60s memo (called on every rerun for IS_ADMIN/IS_PAID) — saves a Turso
    roundtrip per click. Invalidated on any user mutation."""
    if time.time() - _LEVEL_CACHE["t"] < 60 and username in _LEVEL_CACHE["v"]:
        return _LEVEL_CACHE["v"][username]
    with _connect() as c:
        r = c.execute("SELECT level FROM users WHERE username=?", (username,)).fetchone()
    lvl = r[0] if r else "user"
    _LEVEL_CACHE["v"][username] = lvl
    _LEVEL_CACHE["t"] = time.time()
    return lvl


_LEVEL_CACHE = {"t": 0.0, "v": {}}


_CRED_CACHE = {"t": 0.0, "v": None}


def auth_credentials():
    """streamlit-authenticator credentials dict built from the users table.
    60s in-process memo — this is called on every rerun, so it saves a
    Turso roundtrip each time. Invalidated on any user mutation."""
    if time.time() - _CRED_CACHE["t"] < 60 and _CRED_CACHE["v"] is not None:
        return _CRED_CACHE["v"]
    with _connect() as c:
        rows = c.execute("SELECT username, name, email, pw_hash FROM users").fetchall()
    v = {"usernames": {u: {"name": n, "email": e, "password": h}
                       for u, n, e, h in rows}}
    _CRED_CACHE.update(t=time.time(), v=v)
    return v


def _creds_invalidate():
    _CRED_CACHE["t"] = 0.0
    _LEVEL_CACHE["t"] = 0.0
    _LEVEL_CACHE["v"] = {}


def load_bets(user):
    with _connect() as c:
        rows = c.execute(f"SELECT {','.join(_BETS_COLS)} FROM bets WHERE user=?",
                         (user,)).fetchall()
    return pd.DataFrame(rows, columns=_BETS_COLS)


def save_bet(bet, user):
    bet = dict(bet)
    bet_id = uuid.uuid4().hex[:8]
    with _connect() as c:
        c.execute("""INSERT INTO bets (id, user, date, season, week, game,
            bet_type, selection, line, odds, stake, book, status, profit, clv)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (bet_id, user, bet.get("date"), bet.get("season"), bet.get("week"),
             bet.get("game"), bet.get("bet_type"), bet.get("selection"),
             bet.get("line"), bet.get("odds"), bet.get("stake"), bet.get("book"),
             bet.get("status", "pending"), None, None))
    return bet_id


def delete_bet(bet_id, user):
    with _connect() as c:
        c.execute("DELETE FROM bets WHERE id=? AND user=?", (bet_id, user))


def update_bet_result(bet_id, user, status, profit, clv):
    with _connect() as c:
        c.execute("UPDATE bets SET status=?, profit=?, clv=? WHERE id=? AND user=?",
                  (status, profit, clv, bet_id, user))


# ---------------- predictions (global) ----------------
def load_picks():
    with _connect() as c:
        rows = c.execute(f"SELECT {','.join(_PICKS_COLS)} FROM predictions").fetchall()
    return pd.DataFrame(rows, columns=_PICKS_COLS)


def existing_pick_keys():
    with _connect() as c:
        return set(c.execute("SELECT game, pick_type FROM predictions").fetchall())


def insert_pick(row):
    with _connect() as c:
        c.execute("""INSERT OR IGNORE INTO predictions
            (id, logged_at, season, week, game, pick_type, side, model_val,
             market_val_log, edge_log, p_cover_log, closing_line, grade, profit)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex[:8], row["logged_at"], row["season"], row["week"],
             row["game"], row["pick_type"], row["side"], row["model_val"],
             row["market_val_log"], row["edge_log"], row["p_cover_log"],
             None, "pending", None))


def grade_pick(pick_id, closing_line, grade, profit):
    with _connect() as c:
        c.execute("UPDATE predictions SET closing_line=?, grade=?, profit=? WHERE id=?",
                  (closing_line, grade, profit, pick_id))
