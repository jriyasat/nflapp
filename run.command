#!/bin/bash
# NFL Edge Finder launcher — double-click or run: ./run.command
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/streamlit run app.py --server.headless true --server.port 8501
