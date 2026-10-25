"""Unit test for views.game_detail.form_df() — the last-3-games table builder.
This is the exact kind of formatting logic that was silently corrupted by the
app.py -> views/ split (see CHANGELOG.md 2026-10-25). Mocks analytics.last_n
Run with: pytest -v tests/test_form_df.py (or: python3 tests/test_form_df.py)
"""
import math
import os
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import views.game_detail as gd


def _fake_rows():
    return [
        {"date": "2026-09-14", "loc": "vs", "opp": "DAL", "score": "27-24",
         "result": "W", "line": -3.5, "ats": "W", "total_line": 47.0, "ou": "O"},
        {"date": "2026-09-21", "loc": "@", "opp": "PHI", "score": "17-30",
         "result": "L", "line": 2.5, "ats": "L", "total_line": 44.5, "ou": "U"},
        {"date": "2026-09-28", "loc": "vs", "opp": "NYG", "score": "21-21",
         "result": "T", "line": float("nan"), "ats": "-", "total_line": float("nan"), "ou": "-"},
    ]


def test_form_df_maps_columns_and_formats_signs(monkeypatch):
    monkeypatch.setattr(gd.an, "last_n", lambda games, team, n: _fake_rows())
    ctx = SimpleNamespace(games=None)
    df = gd.form_df(ctx, "SEA")

    assert list(df.columns) == ["Date", "Game", "Score", "W/L", "Line", "ATS", "Total", "O/U"]
    assert len(df) == 3

    row0 = df.iloc[0]
    assert row0["Game"] == "vs DAL"
    assert row0["Score"] == "27-24"
    assert row0["W/L"] == "W"
    assert row0["Line"] == "-3.5"   # f"{-3.5:+.1f}" -> "-3.5"
    assert row0["Total"] == "47.0"

    row1 = df.iloc[1]
    assert row1["Line"] == "+2.5"  # positive spreads get an explicit '+'
    assert row1["Game"] == "@ PHI"

    row2 = df.iloc[2]
    assert row2["Line"] == "-"     # NaN line -> dash, not "nan"
    assert row2["Total"] == "-"


def test_form_df_returns_none_when_no_games(monkeypatch):
    monkeypatch.setattr(gd.an, "last_n", lambda games, team, n: [])
    ctx = SimpleNamespace(games=None)
    assert gd.form_df(ctx, "SEA") is None


class _FakeMonkeypatch:
    """Minimal monkeypatch.setattr stand-in so this runs without pytest."""
    def __init__(self):
        self._saved = []

    def setattr(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._saved):
            setattr(obj, name, old)


if __name__ == "__main__":
    mp = _FakeMonkeypatch()
    try:
        test_form_df_maps_columns_and_formats_signs(mp)
    finally:
        mp.undo()

    mp = _FakeMonkeypatch()
    try:
        test_form_df_returns_none_when_no_games(mp)
    finally:
        mp.undo()

    print("OK - all form_df tests passed")
