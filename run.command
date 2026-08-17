#!/bin/bash
# NFL Edge Finder launcher — double-click or run: ./run.command
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
# env -u PYTHONPATH: the Hermes agent session leaks its own venv into PYTHONPATH,
# which breaks numpy/pandas for this project's Python 3.13 venv.
exec env -u PYTHONPATH .venv/bin/streamlit run app.py --server.headless true --server.port 8501
