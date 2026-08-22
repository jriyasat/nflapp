# NFL Edge Finder — Operations Manual

## Live deployment

- **Cloud app:** https://nfledge.streamlit.app (Streamlit Community Cloud, auto-deploys on push to `main`)
- **Repo:** github.com/jriyasat/nflapp — PUBLIC (required: Streamlit can't see private repos without its GitHub App installed; code contains no secrets)
- **Diagrams:** GitHub Pages from `/docs` → https://jriyasat.github.io/nflapp/ (data-map.html, model-diagram.html + preview PNGs; How It Works page links these)
- **Local app:** `./run.command` → localhost:8501 (same code, same Turso DB)

## Hermes cron jobs (on Jeff's Mac)

| Job | ID | Schedule | What |
|---|---|---|---|
| NFL Morning Brief | 7062a432915e | daily 8:00 ET | Watchdog digest: line movers, injury escalations, model edges ≥2pts, totals leans, wind alerts, Monday recap edition. Silent when nothing changed. Logs picks to Turso + line history |
| NFL Inactives Watch | 98404b02208d | */15 min, 11:00-23:00 Thu/Sat/Sun/Mon | Gameday inactives ~90min pre-kickoff (ESPN summary endpoint), deduped per game |
| NFL Edge keep-alive | 0627253ba560 | 8:05 + 20:05 daily | Pings /healthz; alerts only if cloud app is down |
| Playoff build reminder | f32fe4ea0898 | one-shot 2026-12-01 | Remind Jeff to build POST support (week picker, journal/tracker grading, brief) — DECIDED: preseason skipped, pick'em shelved |

## Architecture

| Piece | Runs where | State |
|---|---|---|
| Streamlit app (cloud) | Streamlit Community Cloud (auto-deploys from `main`) | Stateless; reads/writes Turso |
| Streamlit app (local) | Jeff's Mac (`./run.command` → localhost:8501) | Same code, same Turso DB |
| Morning brief | Jeff's Mac, Hermes cron, daily 8:00 AM ET | Writes predictions + line history to Turso, delivers Telegram + email fan-out |
| Database | Turso (libsql, HTTPS transport) — users, bets (per-user), predictions, line_history | Shared by all |

## Update pipeline

1. Make changes locally
2. Verify: `env -u PYTHONPATH .venv/bin/python` — unit checks + AppTest smoke test (exceptions must be zero)
3. `git add -A && git commit -m "..."`
4. `git push` → Streamlit Cloud auto-redeploys in ~1-2 min; users just refresh

## Rules

- **`main` is always deployable.** No push without the verification pass.
- **Additive-only schema changes.** New columns/tables yes; drops/renames no. Migrations run on connect (`db._ensure_user_cols` pattern).
- **Secrets live in exactly two places:** `.streamlit/secrets.toml` (local, gitignored) and the Streamlit Cloud secrets dashboard. Never in git.
- **PYTHONPATH quirk:** the Hermes agent session exports a polluted PYTHONPATH — always run the app/scripts with `env -u PYTHONPATH` (already baked into run.command and the .sh wrappers).
- **Turso libsql_client hangs process exit** (non-daemon threads) — scripts using it must `os._exit(0)` at the end.
- **Module changes need a server restart, not a browser rerun** — Streamlit reruns `app.py` but Python caches `db.py`/`data.py`/etc. in the long-lived process. Symptom: `AttributeError: module has no attribute <new function>`. Fix: `pkill -f "streamlit run app.py"` and relaunch.

## Rollback

```
git revert HEAD && git push    # cloud redeploys the previous state in ~2 min
```

## Secrets inventory (locations only)

- `.streamlit/secrets.toml`: `NFL_EDGE_TURSO_URL`, `NFL_EDGE_TURSO_TOKEN`, `ODDS_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `[cookie]`
- Streamlit Cloud dashboard: same keys
- `~/.hermes/.env`: `TELEGRAM_BOT_TOKEN` (read at runtime by `scripts/notify.py`; never copied)
- `auth.yaml`: cookie config + bootstrap fallback (gitignored)

## Feature inventory (as of Aug 2026)

- Per-game tabs: Predictor (sides+totals market-blend, EV/¼-Kelly, explainer popup + glossary), Props (injury-aware projections, hit-rate trends, what-if simulator, live lines via house key), SGP (correlation fair-odds), Lines (multi-book + line movement charts + key-number badges), Form, H2H (5y), Injuries
- Pages: Games, Bet Journal (private per user, auto-grade + CLV + bankroll), Track Record (model picks ≥2pts graded at close, edge buckets, calibration), How It Works (explainers + video + diagrams), Settings (password, email/Telegram opt-ins, delete account), Users (admin: add/reset/delete, levels)
- Admin = jeff; users keith/shane. Non-admins don't see API key field or feed-error banners.

## Repo map

```
app.py            Streamlit UI (all pages + tabs)
data.py           Data feeds (nflverse, ESPN w/ circuit breaker, Odds API, Open-Meteo) + caching
predictor.py      Market-blend model (Elo 2015+ + de-vig consensus + adjustments; sides + totals)
props_model.py    Injury-aware player prop projections + hit rates
sgp.py            SGP correlation engine (empirical lifts)
analytics.py      H2H, form, situational spots, key numbers, line shopping
journal.py        Per-user bet journal + CLV (db-backed)
tracker.py        Model pick log + closing-line grading (db-backed)
db.py             SQLite/Turso backend (single seam: _connect)
auth_setup.py     streamlit-authenticator wiring (DB-backed users, safe fallbacks)
weather.py        Kickoff wind forecasts (Open-Meteo)
scripts/morning_brief.py   Daily watchdog digest + Monday recap
scripts/inactives_watch.py Gameday inactives watchdog
scripts/notify.py          Email (Gmail SMTP) + Telegram (Bot API) senders
```

## Monitoring

- Cloud app errors: Streamlit Cloud dashboard → app logs
- Brief failures: Hermes cron alerts Jeff on non-zero exit
- DB: Turso dashboard (usage, rows)
