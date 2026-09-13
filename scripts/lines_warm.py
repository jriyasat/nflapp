"""Lines warm: push the SGO board (spreads/totals/ML + player props) into the
Turso shared cache 4x daily, so every environment (local, Docker, Cloud) reads
ONE fetch cycle. ~64 objects/day on the SGO free tier (2,500/mo budget).
Silent on success (watchdog). Run via nfl_lines_warm.sh."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop("PYTHONPATH", None)

import data as dl


def main():
    key = dl.sgo_api_key()
    if not key:
        print("⚠️ lines warm: no SGO API key found")
        return
    n = dl.sgo_push_shared(key)
    if n == 0:
        print("⚠️ lines warm: SGO board push returned 0 events")


if __name__ == "__main__":
    from _common import run
    run(main)
