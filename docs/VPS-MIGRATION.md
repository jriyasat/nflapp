# VPS Migration Plan — NFL Edge Finder

Move the app from Streamlit Community Cloud (free, sleeps) to a $5-10/mo VPS we own.
Target audience: whoever executes this (agent or human). Every command is copy-pasteable.

## 0. Cost / effort summary

| Item | Monthly | One-time |
|---|---|---|
| VPS (Hetzner CX22 or DO 2GB) | $4.5-6 | — |
| (alt) AWS Lightsail 2GB | $10 | — |
| Domain | ~$1 ($12/yr) | purchase |
| Execution time | — | ~2-3 hours |

## 1. Host head-to-head

| | Hetzner CX22 ⭐ | DigitalOcean 2GB | AWS Lightsail 2GB |
|---|---|---|---|
| Price | ~$4.5/mo | $6/mo | $10/mo |
| RAM/CPU | 4GB / 2 vCPU | 2GB / 1 vCPU | 2GB / 1 vCPU |
| Transfer | 20TB | 2TB | 3TB |
| Gotcha | EU-centric (US regions exist, check latency) | bandwidth overage $ | AWS console complexity |

**Recommendation: Hetzner CX22** (most machine per dollar; 4GB is double headroom).
Pick the **US-East region**. If the user prefers staying in AWS: Lightsail $10 works identically.

## 2. Box setup (Ubuntu 24.04 LTS)

```bash
# as root on the fresh box
apt update && apt upgrade -y
apt install -y python3.13 python3.13-venv python3-pip nginx certbot python3-certbot-nginx ufw git

# app user (don't run as root)
useradd -m -s /bin/bash nfledge
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw enable

# deploy the code (repo is PUBLIC today)
sudo -u nfledge git clone https://github.com/jriyasat/nflapp.git /home/nfledge/nflapp
cd /home/nfledge/nflapp
sudo -u nfledge python3.13 -m venv .venv
sudo -u nfledge env -u PYTHONPATH .venv/bin/pip install -r requirements.txt
```

**Private-repo option:** if the repo goes private, create a read-only **deploy key**
(box's `~nfledge/.ssh/id_ed25519` pub → GitHub repo → Settings → Deploy keys) and
clone via `git@github.com:jriyasat/nflapp.git`. Otherwise public clone is fine.

## 3. Secrets

```bash
# copy from the Mac (run ON the Mac):
scp /Users/jeff/nfl-edge/.streamlit/secrets.toml <box-ip>:/home/nfledge/nflapp/.streamlit/secrets.toml
# on the box:
chmod 600 /home/nfledge/nflapp/.streamlit/secrets.toml
chown nfledge:nfledge /home/nfledge/nflapp/.streamlit/secrets.toml
```
Also add to that file: `TELEGRAM_BOT_TOKEN="..."` and `JEFF_TELEGRAM_CHAT_ID="..."`
(copied from `~/.hermes/.env` on the Mac) — cron scripts deliver Telegram themselves
on the box (no Hermes there). `scripts/notify.py` reads these.

## 4. Streamlit as a systemd service

`/etc/systemd/system/nfledge.service`:
```ini
[Unit]
Description=NFL Edge Finder (Streamlit)
After=network-online.target

[Service]
User=nfledge
WorkingDirectory=/home/nfledge/nflapp
ExecStart=/usr/bin/env -u PYTHONPATH /home/nfledge/nflapp/.venv/bin/streamlit run app.py --server.headless true --server.port 8501 --server.address 127.0.0.1
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload && systemctl enable --now nfledge
systemctl status nfledge   # expect: active (running)
```

## 5. nginx + SSL

`/etc/nginx/sites-available/nfledge`:
```nginx
server {
    server_name YOURDOMAIN.com;
    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;      # websockets — REQUIRED
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```
```bash
ln -s /etc/nginx/sites-available/nfledge /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
# DNS first: A record YOURDOMAIN.com -> box IP (set TTL 300s before cutover)
certbot --nginx -d YOURDOMAIN.com     # free SSL, auto-renews
```

## 6. Cron migration

On the box: `sudo -u nfledge crontab -e` (all times ET — set `timedatectl set-timezone America/New_York` first):
```cron
0 8 * * *      /home/nfledge/nflapp/scripts/morning_brief.sh >> /tmp/brief.log 2>&1
*/15 11-23 * * 0,1,4,6  /home/nfledge/nflapp/scripts/inactives_watch.sh >> /tmp/inactives.log 2>&1
*/30 15-21 * * 3,4,5    /home/nfledge/nflapp/scripts/injury_report_watch.sh >> /tmp/injwatch.log 2>&1
0 23 * * 0     /home/nfledge/nflapp/scripts/db_backup.sh >> /tmp/backup.log 2>&1
```
Notes:
- **Keep-alive job: DELETE** (no sleep on a VPS). Wake-bot too (Streamlit-Cloud-only problem).
- Delivery: scripts print → nobody delivers on a box. Before cutover, verify each script's
  telegram path calls `notify.send_telegram(JEFF_CHAT_ID, text)` directly (small patch to
  the 4 scripts: replace bare `print(full)` with print + notify call). Email path unchanged.
- The 2 one-shot Hermes reminder jobs (Nov 1, Dec 1) stay on the Mac's Hermes — they're
  agent messages, not scripts.

## 7. Cutover runbook (zero downtime)

1. ✅ Box built + service running + `curl localhost:8501/healthz` → ok on the box
2. ✅ HTTPS works: `https://YOURDOMAIN.com` shows the login screen
3. ✅ Login as jeff → verify Turso data present (journal, track record)
4. ✅ Run each cron script once manually on the box; confirm Telegram + email arrive
5. 🔀 Switch DNS A record to the box (TTL 300s → propagates in minutes)
6. Watch 24h. Streamlit Cloud app stays up as instant rollback (delete/pause later)
7. Disable the Mac-side cron jobs (morning brief, inactives, injury watch, keep-alive, wake-bot)

**Rollback:** point DNS back to Streamlit Cloud / re-enable Mac jobs. Nothing is destructive.

## 8. Post-move ops

- **Update app:** on the box `cd nflapp && git pull && systemctl restart nfledge`
  (or add a 5-min cron that pulls+restarts on change — your call)
- **Logs:** `journalctl -u nfledge -f` (app) • `/tmp/*.log` (crons)
- **Monitoring:** box cron `*/10 * * * * curl -sf localhost:8501/healthz || systemctl restart nfledge`
- **Backups:** existing Turso backup script runs on-box (Sunday 11pm line above)

## 9. Quirks that MUST survive the move

- Every python invocation: `env -u PYTHONPATH` (baked into the .sh wrappers already)
- Scripts end `os._exit(0)` (libsql threads hang exit)
- Watch scripts carry a 240s `signal.alarm` deadline
- `requirements.txt` is the only dependency source (cloud/VPS parity)
