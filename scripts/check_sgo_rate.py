#!/usr/bin/env python
"""
Hourly check for SGO API rate‑limit reset.
Logs timestamp and remaining quota (if available).
"""
import os
import sys
import json
import time
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl

def check_rate():
    api_key = dl.sgo_api_key()
    if not api_key:
        return {"error": "No API key"}
    # Make a minimal request: one event, limit=1, far future start date
    import urllib.request
    import urllib.error
    url = dl.SGO_EVENTS
    params = {
        "leagueID": "NFL",
        "startsAfter": "2030-01-01T00:00:00Z",  # no events, cheap
        "limit": 1,
        "offset": 0,
    }
    headers = {"x-api-key": api_key}
    query = "&".join([f"{k}={v}" for k, v in params.items()])
    full_url = f"{url}?{query}"
    req = urllib.request.Request(full_url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        status = resp.status
        remaining = resp.headers.get('X-RateLimit-Remaining')
        limit = resp.headers.get('X-RateLimit-Limit')
        reset = resp.headers.get('X-RateLimit-Reset')
        body = resp.read()
        data = json.loads(body)
        return {
            "status": status,
            "remaining": remaining,
            "limit": limit,
            "reset": reset,
            "data_len": len(data.get('data', [])),
            "error": None
        }
    except urllib.error.HTTPError as e:
        status = e.code
        remaining = e.headers.get('X-RateLimit-Remaining')
        limit = e.headers.get('X-RateLimit-Limit')
        reset = e.headers.get('X-RateLimit-Reset')
        return {
            "status": status,
            "remaining": remaining,
            "limit": limit,
            "reset": reset,
            "error": str(e)
        }
    except Exception as e:
        return {"status": None, "error": str(e)}

def main():
    log_dir = dl.CACHE
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'sgo_rate_check.log')
    # Simple logging
    result = check_rate()
    timestamp = datetime.utcnow().isoformat()
    line = f"{timestamp} {json.dumps(result)}\n"
    with open(log_file, 'a') as f:
        f.write(line)
    print(line.strip())

if __name__ == '__main__':
    main()