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
import uuid

import pandas as pd

import data as dl

DB_PATH = os.path.join(dl.CACHE, "nfl_edge.db")

_BETS_COLS = ["id", "user", "date", "season", "week", "game", "bet_type",
              "selection", "line", "odds", "stake", "book", "status", "profit", "clv"]
_PICKS_COLS = ["id", "logged_at", "season", "week", "game", "pick_type", "side",
               "model_val", "market_val_log", "edge_log", "p_cover_log",
               "closing_line", "grade", "profit"]


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS bets (
        id TEXT PRIMARY KEY, user TEXT NOT NULL, date TEXT, season INT, week INT,
        game TEXT, bet_type TEXT, selection TEXT, line REAL, odds REAL,
        stake REAL, book TEXT, status TEXT DEFAULT 'pending',
        profit REAL, clv REAL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS predictions (
        id TEXT PRIMARY KEY, logged_at TEXT, season INT, week INT, game TEXT,
        pick_type TEXT, side TEXT, model_val REAL, market_val_log REAL,
        edge_log REAL, p_cover_log REAL, closing_line REAL,
        grade TEXT DEFAULT 'pending', profit REAL,
        UNIQUE(game, pick_type))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_user ON bets(user)")
    return conn


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


# ---------------- bets (per-user) ----------------
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
