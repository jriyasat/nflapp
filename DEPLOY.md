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
| NFL Props Warm (Daily) | c34350045782 | daily 10:00 ET | Warms shared prop-line cache for all games within 4 days; fetches only missing/stale games + refreshes games within 36h of kickoff (quota-safe on dedicated ODDS_API_KEY_PROPS). Replaced the old Mon+Sat pair on 2026-09-10 |
| NFL Value Radar | 2e42c684b0b9 | */30 min, 8:00-24:00 | Spread + total edges ≥2.0 with re-alerts on ≥1-pt line moves (shows the move). Reads shared SGO cache (never spends objects) + ESPN fallback |
| NFL Lines Warm (SGO → Turso) | 4b79a2913d68 | 6:00/12:00/18:00/23:00 ET | Pushes the SGO board (lines + player props) into the Turso `shared_cache` table with kickoff-freeze (started games keep pre-start lines). One fetch cycle for ALL environments (~64 objects/day, free-tier safe) |
| NFL Edge keep-alive | 0627253ba560 | 8:05 + 20:05 daily | Pings /healthz; alerts only if cloud app is down |
| Playoff build reminder | f32fe4ea0898 | one-shot 2026-12-01 | Remind Jeff to build POST support (week picker, journal/tracker grading, brief) — DECIDED: preseason skipped, pick'em shelved |

## Shared cache (single-fetcher, since 2026-09-13)

Turso table `shared_cache(key, payload, updated_at-epoch)`. Writer = lines-warm cron (+ prop_warm's daily push + write-on-fetch from the app). Readers (`dl._sgo_board_raw`, `dl.cached_sgo_lines`, `dl.cached_event_props`) chain: **Turso (<8h) → local disk → live fetch**, memoized in-process (the board payload is ~19MB — parsed once per change, never per call). This is why props/SGP work on Streamlit Cloud despite its ephemeral filesystem. Player props now come from the SGO slate fetch (free, `dl._sgo_event_props`); The Odds API props path remains as fallback (`props:{away}@{home}` keys in shared_cache).

## Architecture

| Piece | Runs where | State |
|---|---|---|
| Streamlit app (cloud) | Streamlit Community Cloud (auto-deploys from `main`) | Stateless; reads/writes Turso |
| Streamlit app (local) | Jeff's Mac (`./run.command` → localhost:8501) | Same code, same Turso DB |
| Morning brief | Jeff's Mac, Hermes cron, daily 8:00 AM ET | Writes predictions + line history to Turso, delivers Telegram + email fan-out |
| Lines (spreads/totals/ML) | **SportsGameOdds API** (`dl.sgo_lines`, 2h disk cache `data/sgo_odds.json`) — primary since 2026-09-10; The Odds API (`dl.odds_api_lines`) is fallback only (main key exhausted its 500/mo quota) | Key: `data/sgo_api_key.txt` (0600, gitignored) or env `SGO_API_KEY`; amateur free tier = 2,500 objects/mo (~156 slate fetches), 10 req/min; free-tier books: draftkings/fanduel/betmgm/caesars/espnbet (others 400); usage: `GET /v2/account/usage` with `x-api-key` header. Auth via header, errors 401/429 trip the 6h circuit breaker with stale-serve |
| Player props lines | The Odds API, dedicated key `ODDS_API_KEY_PROPS` (separate quota) — migrate to SGO later | 6-day shared disk cache, warmed daily 10:00 ET |
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

## Review backlog status (Sep 2026 audit)

- DONE: S1 (cookie fail-closed), S2 (pick'em server-side lock), S4 (delete-account password), O2 (user_level memo), O3 (quota: 1 prop-load/day free users, Thursday-only scan ≈100 credits/mo), O4 (single `emailer` path), O1 (lazy game rendering — only open games render tabs), G3 (central `FEATURE_GATES` in app.py)
- DEFERRED: S3 (login throttling — low value), O5 (script common-core — mostly subsumed by email consolidation), G1 (full page-dispatch registry — do when the next page lands), G2 (data-source registry — do when adding a paid feed), G4 (model constants to config)
- DEFERRED (user decisions): preseason support (skipped), pick'em was built, playoff support → build Dec 2026 (reminder job f32fe4ea0898)

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
