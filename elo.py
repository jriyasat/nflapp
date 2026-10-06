"""
Stub elo module for compatibility with sentiment_forward_test.py.
Provides EloModel as alias to predictor.Elo.
"""

from predictor import Elo

EloModel = Elo

# Optional: provide calculate_spread if needed (not used currently).
def calculate_spread(*args, **kwargs):
    raise NotImplementedError("calculate_spread not implemented; use predictor.Elo.predict")