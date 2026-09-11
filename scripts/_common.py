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
    import signal
    # hard deadline: a hung network/DB call must never overlap the next cron tick
    signal.signal(signal.SIGALRM, lambda *_: os._exit(1))
    signal.alarm(600)
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


def fanout(alert_key, subject, text):
    """Deliver an alert to all users subscribed in the alert_prefs matrix
    (channel 'telegram' and/or 'email'; 'both' gets each). Never raises —
    alert delivery must never kill the calling script."""
    try:
        import db
        import notify
        for u in db.users_for_alert(alert_key, "telegram"):
            if u.get("telegram_chat_id"):
                try:
                    notify.send_telegram(u["telegram_chat_id"], text)
                except Exception:
                    pass
        for u in db.users_for_alert(alert_key, "email"):
            if u.get("email"):
                try:
                    notify.send_email(u["email"], subject, text)
                except Exception:
                    pass
    except Exception:
        pass


def load_snap(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def save_snap(path, obj):
    json.dump(obj, open(path, "w"))
