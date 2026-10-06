#!/usr/bin/env python
"""
SGO rate‑limit monitor daemon — runs hourly checks indefinitely.
"""
import os
import sys
import time
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data as dl

def check_rate():
    api_key = dl.sgo_api_key()
    if not api_key:
        return {"error": "No API key"}
    import urllib.request
    import urllib.error
    import json
    url = dl.SGO_EVENTS
    params = {
        "leagueID": "NFL",
        "startsAfter": "2030-01-01T00:00:00Z",
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
    pid_file = os.path.join(log_dir, 'sgo_monitor.pid')
    # Write PID file
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))
    # Log start
    with open(log_file, 'a') as f:
        f.write(f"{datetime.utcnow().isoformat()} Monitor daemon started (PID {os.getpid()})\\n")
    # Loop hourly
    while True:
        try:
            result = check_rate()
            line = f"{datetime.utcnow().isoformat()} {json.dumps(result)}\\n"
            with open(log_file, 'a') as f:
                f.write(line)
            # If quota resets (status != 403/429) maybe alert
            if result.get('status') != 403 and result.get('status') != 429:
                with open(log_file, 'a') as f:
                    f.write(f"{datetime.utcnow().isoformat()} API QUOTA RESTORED!\\n")
        except Exception as e:
            with open(log_file, 'a') as f:
                f.write(f"{datetime.utcnow().isoformat()} Error in check: {e}\\n")
        time.sleep(3600)  # one hour

if __name__ == '__main__':
    import json
    main()