"""Wind forecasts for outdoor stadiums via Open-Meteo (free, no key).

Validated angles (2021-25, n=897 outdoor, vs closing totals): sustained wind
10-14 mph unders 61% (production -1.2 rule ✓); sustained 15+ unders 55%
(production -2.7 rule — softer than the original 60.9%/n=87 calibration);
GUSTS are the sharper instrument: 20-25 mph unders 60% (z=-2.99), 25-30 mph
unders 71% (z=-4.24), weakening at 30+ (market prices headline weather).
Forecasts reach 16 days out; kickoff-hour wind is what matters.
"""

import hashlib
import json
import os
import time

import pandas as pd
import requests

import data as dl

# Outdoor/roof-exposed venues on the 2026 schedule (lat, lon)
STADIUM_WX = {
    "Acrisure Stadium": (40.4468, -80.0158),
    "Bank of America Stadium": (35.2258, -80.8530),
    "Empower Field at Mile High": (39.7439, -105.0201),
    "Estadio Banorte": (19.3029, -99.1505),
    "EverBank Stadium": (30.3240, -81.6373),
    "GEHA Field at Arrowhead Stadium": (39.0489, -94.4839),
    "Gillette Stadium": (42.0909, -71.2643),
    "Hard Rock Stadium": (25.9580, -80.2389),
    "Highmark Stadium": (42.7738, -78.7870),
    "Huntington Bank Field": (41.5061, -81.6995),
    "Lambeau Field": (44.5013, -88.0622),
    "Levi's Stadium": (37.4030, -121.9700),
    "Lincoln Financial Field": (39.9008, -75.1675),
    "Lumen Field": (47.5952, -122.3316),
    "M&T Bank Stadium": (39.2780, -76.6227),
    "MetLife Stadium": (40.8128, -74.0742),
    "Nissan Stadium": (36.1665, -86.7713),
    "Northwest Stadium": (38.9076, -76.8645),
    "Paycor Stadium": (39.0954, -84.5160),
    "Raymond James Stadium": (27.9759, -82.5033),
    "Soldier Field": (41.8623, -87.6167),
    "Tottenham Hotspur Stadium": (51.6043, -0.0664),
    "Wembley Stadium": (51.5560, -0.2796),
}

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
CACHE_H = 3
WIND_FLAG = 15.0
WIND_NOTE = 10.0


def _kickoff_hourly(stadium, gameday):
    """Cached hourly forecast payload (wind + gusts) for a stadium-day."""
    coords = STADIUM_WX.get(stadium)
    if not coords or pd.isna(gameday):
        return None
    day = gameday.strftime("%Y-%m-%d")
    key = hashlib.md5(f"{stadium}|{day}".encode()).hexdigest()[:12]
    safe = f"wx_{key}.json"
    path = os.path.join(dl.CACHE, safe)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_H * 3600:
        data = json.load(open(path))
        if "wind_gusts_10m" in (data.get("hourly") or {}):  # legacy caches lack gusts → refetch
            return data
    try:
        r = requests.get(OPEN_METEO, params={
            "latitude": coords[0], "longitude": coords[1],
            "hourly": "wind_speed_10m,wind_gusts_10m", "wind_speed_unit": "mph",
            "timezone": "America/New_York",
            "start_date": day, "end_date": day}, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        json.dump(data, open(path, "w"))
        return data
    except Exception:
        return None


def _at_kickoff(data, gameday, gametime, field):
    """Field value at kickoff hour (best available hour that day as fallback)."""
    day = gameday.strftime("%Y-%m-%d")
    times = (data.get("hourly") or {}).get("time") or []
    vals = (data.get("hourly") or {}).get(field) or []
    if not times:
        return None  # beyond forecast window
    try:
        hour = int(str(gametime).split(":")[0])
    except Exception:
        hour = 13
    target = f"{day}T{hour:02d}:00"
    for t, w in zip(times, vals):
        if t == target:
            try:
                return float(w)
            except (TypeError, ValueError):
                break
    for w in vals:
        try:
            return float(w)
        except (TypeError, ValueError):
            continue
    return None


def kickoff_wind(stadium, gameday, gametime):
    """Forecast sustained wind (mph) at kickoff hour, or None if indoor /
    beyond the 16-day forecast window / fetch failure."""
    d = _kickoff_hourly(stadium, gameday)
    return _at_kickoff(d, gameday, gametime, "wind_speed_10m") if d else None


def kickoff_gust(stadium, gameday, gametime):
    """Forecast wind GUSTS (mph) at kickoff hour — the sharper under signal
    (backtest 2021-25: gust 20-29mph unders 60-70% vs closing totals)."""
    d = _kickoff_hourly(stadium, gameday)
    return _at_kickoff(d, gameday, gametime, "wind_gusts_10m") if d else None


def wind_for_game(game_row):
    """(mph or None, flag) where flag: 'under' | 'breezy' | None.

    Weather is a nice-to-have badge: any failure returns (None, None)
    rather than ever breaking the Games page."""
    try:
        if str(game_row.get("roof", "")).lower() not in ("outdoors", "open"):
            return None, None
        mph = kickoff_wind(game_row.get("stadium"), game_row.get("gameday"),
                           game_row.get("gametime"))
    except Exception:
        return None, None
    if mph is None:
        return None, None
    flag = "under" if mph >= WIND_FLAG else ("breezy" if mph >= WIND_NOTE else None)
    return mph, flag
