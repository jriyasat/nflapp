"""Snapshot the Turso database (users, journals, pick'em, predictions, usage)
into a local SQLite file under data/backups/. Pure insurance — the app never
reads from backups; restore is a manual table-copy if disaster ever strikes.

Keeps the 12 most recent snapshots. Run weekly via cron.
"""

import glob
import os
import sqlite3
import sys
import time

sys.path.insert(0, "/Users/jeff/nfl-edge")
os.environ.pop("PYTHONPATH", None)

import db

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "backups")
KEEP = 12


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    dest_path = os.path.join(BACKUP_DIR, f"nfl_edge_{stamp}.db")
    if os.path.exists(dest_path):
        os.remove(dest_path)  # same-day rerun = fresh snapshot

    dest = sqlite3.connect(dest_path)
    with db._connect() as src:
        tables = [r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        total = 0
        for t in tables:
            ddl = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()[0]
            dest.execute(ddl)
            rows = [tuple(r) for r in src.execute(f"SELECT * FROM {t}").fetchall()]
            cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})").fetchall()]
            if rows:
                dest.executemany(
                    f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    rows)
            total += len(rows)
            print(f"  {t}: {len(rows)} rows", flush=True)
    dest.commit()
    dest.close()

    # prune old snapshots
    snaps = sorted(glob.glob(os.path.join(BACKUP_DIR, "nfl_edge_*.db")))
    for old in snaps[:-KEEP]:
        os.remove(old)
    print(f"backup -> {dest_path} ({total} rows across {len(tables)} tables, "
          f"{os.path.getsize(dest_path) // 1024} KB)", flush=True)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)  # Turso client threads can hang interpreter exit
