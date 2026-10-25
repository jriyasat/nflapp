"""Unit tests for predictor.py's odds/kelly math: american_to_prob, devig,
and the cover-probability + quarter-Kelly formulas inside predict_game().
Pins USE_YPP/SENTIMENT_WEIGHT/MARKET_WEIGHT so results are deterministic
regardless of env vars or config/model_weights.json tuning.
Run with: pytest -v tests/test_predictor_math.py (or: python3 tests/test_predictor_math.py)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import predictor as pr


def test_american_to_prob():
    assert math.isclose(pr.american_to_prob(-150), 0.6, rel_tol=1e-9)
    assert math.isclose(pr.american_to_prob(150), 0.4, rel_tol=1e-9)
    assert pr.american_to_prob(None) is None


def test_devig_normalizes_to_one():
    ph, pa = pr.american_to_prob(-150), pr.american_to_prob(130)
    p_home = pr.devig(ph, pa)
    # de-vigged home + away probs should sum to 1
    p_away = pr.devig(pa, ph)
    assert math.isclose(p_home + p_away, 1.0, rel_tol=1e-9)
    assert pr.devig(0, 0) is None


class _FakeElo:
    _a, _b = 400.0, 0.0
    def predict(self, away, home):
        return 0.5, 0.0  # neutral: no elo lean, no spread


def test_predict_game_cover_prob_and_kelly(monkeypatch):
    monkeypatch.setattr(pr, "USE_YPP", False)
    monkeypatch.setattr(pr, "SENTIMENT_WEIGHT", 0.0)
    monkeypatch.setattr(pr, "MARKET_WEIGHT", 0.85)
    monkeypatch.setattr(pr, "NONMARKET_WEIGHT", 0.15)

    game_row = {"away_team": "AWY", "home_team": "HOM", "gameday": "2026-10-19",
                "game_type": "REG", "week": 5, "away_rest": 7, "home_rest": 7}
    books = {"bk1": {"home_ml": -150, "away_ml": 130, "home_spread": -3.5, "total": 47.0}}

    pred = pr.predict_game(game_row, _FakeElo(), books=books, espn=None, injuries=None, wind_mph=None)

    # hand-computed expected values, mirroring predict_game's formula
    ph, pa = pr.american_to_prob(-150), pr.american_to_prob(130)
    p_home_market = pr.devig(ph, pa)
    model_spread = 0.85 * -3.5 + 0.15 * 0.0
    model_margin = -model_spread
    z = (model_margin - 3.5) / 13.3
    expected_p_home_cover = 0.5 * (1 + math.erf(z / math.sqrt(2)))

    assert math.isclose(pred["p_market"], p_home_market, rel_tol=1e-9)
    assert math.isclose(pred["p_home_cover"], expected_p_home_cover, rel_tol=1e-9)

    b = 100 / 110
    for side, p in (("home", expected_p_home_cover), ("away", 1 - expected_p_home_cover)):
        expected_ev = p * b - (1 - p)
        expected_kelly = max((b * p - (1 - p)) / b, 0) / 4
        assert math.isclose(pred[f"ev_{side}"], expected_ev, rel_tol=1e-9), side
        assert math.isclose(pred[f"kelly_{side}"], expected_kelly, rel_tol=1e-9), side

    # quarter-Kelly must never exceed a quarter of the raw full-Kelly edge,
    # and must be 0 (not negative) when there's no edge
    assert pred["kelly_home"] >= 0
    assert pred["kelly_away"] >= 0


class _FakeMonkeypatch:
    def __init__(self):
        self._saved = []

    def setattr(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._saved):
            setattr(obj, name, old)


if __name__ == "__main__":
    test_american_to_prob()
    test_devig_normalizes_to_one()

    mp = _FakeMonkeypatch()
    try:
        test_predict_game_cover_prob_and_kelly(mp)
    finally:
        mp.undo()

    print("OK - all predictor odds/kelly math tests passed")
