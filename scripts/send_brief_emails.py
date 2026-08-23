"""Email the morning brief to opted-in Pro users.

Runs morning_brief.py as a subprocess; if the brief printed something (i.e.
a notable-change day), wraps it in HTML and sends via Resend to every user
with: email saved + email_enabled + level in (admin, paid).

Silent no-op when: email not configured, brief is silent, or no recipients.
Run via nfl_morning_brief.sh after the Telegram brief.
"""

import os
import subprocess
import sys

sys.path.insert(0, "/Users/jeff/nfl-edge")
os.environ.pop("PYTHONPATH", None)

import db
import emailer

BRIEF_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "morning_brief.py")


def main():
    if not emailer.configured():
        print("email not configured — skipping email brief", flush=True)
        return
    try:
        r = subprocess.run([sys.executable, BRIEF_SCRIPT],
                           capture_output=True, text=True, timeout=600)
        brief = (r.stdout or "").strip()
    except Exception as e:
        print(f"brief subprocess failed: {e}", flush=True)
        return
    if not brief:
        return  # silent day — nothing to send
    recips = [u for u in db.list_users()
              if u["email"] and u["email_enabled"] and u["level"] in ("admin", "paid")]
    if not recips:
        print("no opted-in pro recipients — skipping", flush=True)
        return
    subject = next((ln.strip("* #") for ln in brief.splitlines() if ln.strip()),
                   "NFL Edge — Morning Brief")
    html = emailer.brief_html(brief, footer_note="You're receiving this because you "
                              "enabled the daily email brief in ⚙️ Settings.")
    sent, errors = emailer.broadcast([u["email"] for u in recips],
                                     f"🏈 {subject}"[:120], html)
    print(f"emailed brief to {sent}/{len(recips)}"
          + (f" — errors: {'; '.join(errors)}" if errors else ""), flush=True)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)  # Turso client threads can hang interpreter exit
