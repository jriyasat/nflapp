#!/usr/bin/env python
"""
Test SGO historical fetch without bookmakerID.
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl

def test_fetch(start_date='2024-09-01', api_key=None):
    if api_key is None:
        api_key = dl.sgo_api_key()
    SGO_EVENTS = dl.SGO_EVENTS
    CACHE = dl.CACHE
    
    starts_after = start_date + "T00:00:00Z"
    starts_before = pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # Try without bookmakerID
    data = dl._get_json(SGO_EVENTS, f"sgo_test_{start_date.replace('-','')}.json",
                        5, params={
                            "leagueID": "NFL",
                            "startsAfter": starts_after,
                            "startsBefore": starts_before,
                            "limit": 10,
                        }, extra_headers={"x-api-key": api_key})
    events = data.get("data", [])
    print(f"Total events (no bookmakerID): {len(events)}")
    for e in events[:5]:
        print(f"  {e.get('eventID')} start={e.get('status',{}).get('startsAt')}")
    return events

if __name__ == "__main__":
    events = test_fetch('2024-09-01')
    print(f"First event keys: {list(events[0].keys()) if events else 'none'}")