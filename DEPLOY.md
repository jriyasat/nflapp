# NFL Edge Finder — Operations Manual

## Architecture

| Piece | Runs where | State |
|---|---|---|
| Streamlit app (cloud) | Streamlit Community Cloud (auto-deploys from `main`) | Stateless; reads/writes Turso |
| Streamlit app (local) | Jeff's Mac (`./run.command` → localhost:8501) | Same code, same Turso DB |
| Morning brief | Jeff's Mac, Hermes cron job `7062a432915e`, daily 8:00 AM ET | Writes predictions to Turso, delivers Telegram + email fan-out |
| Database | Turso (libsql) — users, bets (per-user), predictions | Shared by all three |

## Update pipeline

1. Make changes locally
2. Verify: `env -u PYTHONPATH .venv/bin/python` — unit checks + AppTest smoke test (exceptions must be zero)
3. `git add -A && git commit -m "..."`
4. `git push` → Streamlit Cloud auto-redeploys in ~1-2 min; users just refresh

## Rules

- **`main` is always deployable.** No push without the verification pass.
- **Additive-only schema changes.** New columns/tables yes; drops/renames no. The brief, local app, and cloud app share the DB — additive-only keeps them compatible across versions. Migrations run automatically on connect (`db._ensure_user_cols` pattern).
- **Secrets live in exactly two places:** `.streamlit/secrets.toml` (local, gitignored) and the Streamlit Cloud secrets dashboard. Never in git.

## Rollback

```
git revert HEAD && git push    # cloud redeploys the previous state in ~2 min
```

## Secrets inventory (locations only)

- `.streamlit/secrets.toml`: `NFL_EDGE_TURSO_URL`, `NFL_EDGE_TURSO_TOKEN`, `ODDS_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `[cookie]`
- Streamlit Cloud dashboard: same keys (set at deploy time)
- `~/.hermes/.env`: `TELEGRAM_BOT_TOKEN` (read at runtime by `scripts/notify.py`; never copied)
- `auth.yaml`: cookie config + bootstrap credentials (gitignored)

## Morning brief (stays on the Mac — it never turns off)

- Job: `NFL Morning Brief` (Hermes cron), daily 8:00 AM ET, watchdog mode — silent when nothing changed
- Script: `~/.hermes/scripts/nfl_morning_brief.sh` → `scripts/morning_brief.py`
- Logs picks (|edge| ≥ 2) to Turso `predictions`, grades settled picks, sends digest to Jeff's Telegram + opted-in users (email via Gmail SMTP, Telegram DMs via Bot API)
- Manage: `cronjob` tool in Hermes (pause/resume/remove by job id `7062a432915e`)

## Monitoring

- Cloud app errors: Streamlit Cloud dashboard → app logs
- Brief failures: Hermes cron alerts Jeff on non-zero exit
- DB: Turso dashboard (usage, rows)

## Repo map

```
app.py            Streamlit UI (all pages + tabs)
data.py           Data feeds (nflverse, ESPN, Odds API, Open-Meteo) + caching
predictor.py      Market-blend model (Elo + consensus + adjustments, sides + totals)
props_model.py    Injury-aware player prop projections
sgp.py            SGP correlation engine
analytics.py      H2H, form, situational spots, line shopping
journal.py        Per-user bet journal + CLV (db-backed)
tracker.py        Model pick log + closing-line grading (db-backed)
db.py             SQLite/Turso backend (single seam: _connect)
auth_setup.py     streamlit-authenticator wiring (DB-backed users)
weather.py        Kickoff wind forecasts
scripts/morning_brief.py   Daily watchdog digest
scripts/notify.py          Email + Telegram senders
```
