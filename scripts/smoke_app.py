"""Headless full-page smoke test for the Streamlit app (AppTest).

Runs every nav page as user 'jeff' and reports exceptions. Used as the
pre-push gate for page-level changes (AppTest hangs if invoked inside the
Hermes agent session's Python — always run as its own process):

    env -u PYTHONPATH .venv/bin/python3 scripts/smoke_app.py
"""

import os

os.environ.pop("PYTHONPATH", None)
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
at = AppTest.from_file(_APP, default_timeout=240)
at.session_state["authentication_status"] = True
at.session_state["username"] = "jeff"
at.session_state["name"] = "Jeff"
at.run()
pages = ["Games", "📒 Bet Journal", "📈 Track Record", "🏆 Pick'em", "📰 News",
         "🏅 Standings", "📊 Power Rankings", "❓ How It Works", "📜 Terms", "⚙️ Settings"]
fail = 0
for p in pages:
    at.session_state["nav_radio"] = p
    at.run()
    if at.exception:
        fail += 1
        print(f"PAGE {p}: EXCEPTION -> {at.exception[0].value}", flush=True)
    else:
        print(f"PAGE {p}: ok", flush=True)
print("SMOKE DONE" + (f" ({fail} FAILURES)" if fail else " — all pages ok"), flush=True)
os._exit(1 if fail else 0)
