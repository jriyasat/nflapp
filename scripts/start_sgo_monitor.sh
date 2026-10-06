#!/bin/bash
# Hourly SGO rate‑limit monitor
LOG=/app/data/sgo_rate_check.log
PID=/tmp/sgo_monitor.pid
# Ensure log directory
mkdir -p /app/data
# Already running?
if [ -f $PID ]; then
    if kill -0 $(cat $PID) 2>/dev/null; then
        echo "Monitor already running (PID $(cat $PID)). Exiting."
        exit 0
    fi
fi
echo $$ > $PID
trap "rm -f $PID" EXIT
while true; do
    echo "$(date -Is) Starting hourly check..." >> $LOG
    /usr/local/bin/python3 /app/scripts/check_sgo_rate.py >> $LOG 2>&1
    # Wait one hour (3600 seconds)
    sleep 3600
done
