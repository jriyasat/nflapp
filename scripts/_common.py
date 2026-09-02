"""Shared bootstrap for standalone cron scripts.

Every script gets: repo+scripts path setup, PYTHONPATH guard (the Hermes agent
session leaks its venv), and a guaranteed-clean process exit (the Turso libsql
client spawns non-daemon threads that hang the interpreter otherwise — this
also fixes error paths hanging instead of exiting non-zero).

Usage:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import run

    def main():
        ...

    if __name__ == "__main__":
        run(main)
"""

import json
import os
import sys


def bootstrap():
    os.environ.pop("PYTHONPATH", None)


def run(main):
    bootstrap()
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        die(1)
    die(0)


def die(code=0):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def load_snap(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def save_snap(path, obj):
    json.dump(obj, open(path, "w"))
