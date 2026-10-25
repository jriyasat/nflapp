"""
AppContext dataclass — bundle of shared state passed to every view.
"""
from dataclasses import dataclass
from typing import Any, Optional
import pandas as pd

@dataclass
class AppContext:
    # data
    games: pd.DataFrame
    elo: Any  # predictor.Elo instance
    season: int
    week: int
    weeks: list
    week_games: pd.DataFrame
    espn_odds: dict
    books_by_abbr: dict
    injuries: dict
    injuries_err: Optional[str]
    api_key: str
    props_api_key: str
    player_stats: Optional[Any]
    def_mults: Optional[Any]
    
    # auth & user
    USER: str
    NAME: str
    LEVEL: str
    IS_ADMIN: bool
    IS_PAID: bool
    CONTACT_EMAIL: str
    
    # constants
    FEATURE_GATES: dict
    VALUE_EDGE_MIN: float
    
    # page navigation (the current radio selection)
    page: str