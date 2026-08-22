"""Stateful storage for NFL Edge Finder: SQLite.

- bets: per-user bet journal (user column; private per login)
- predictions: global model pick log (shared across users)

Local dev: file at data/nfl_edge.db.
Cloud deploy: _connect() is the single seam to swap to a hosted SQLite
(Turso/libsql) via env vars NFL_EDGE_TURSO_URL / NFL_EDGE_TURSO_TOKEN.
Migrates legacy data/bets.csv + data/predictions.csv on first run.
"""

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
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_lh ON line_history(game, ts)"]


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
                     ("bankroll", "REAL"), ("unit", "REAL")):
        if col not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")


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


def user_level(username):
    with _connect() as c:
        r = c.execute("SELECT level FROM users WHERE username=?", (username,)).fetchone()
    return r[0] if r else "user"


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
