# Changelog

## 2026-11-04 (fix: /app/data not writable by appuser after image rebuild)

### Context
After the rebuild below, 8503 threw `PermissionError: [Errno 13] Permission
denied: '/app/data/games.csv.tmp'` from `data.py`'s atomic-write cache
pattern. `data/` is `.dockerignore`d (local caches, Turso is source of
truth), so `/app/data` doesn't exist when the Dockerfile's `chown -R
appuser:appuser /app` runs at build time. Docker then auto-creates the
directory as `root:root` at container-start to host the individual-file
bind mounts (`sgo_odds.json`, etc.), leaving it unwritable by the non-root
`appuser` for anything the app itself needs to write at runtime (like the
games.csv cache).

### Changed
- `Dockerfile`: added `RUN mkdir -p data/model_fits` before the
  `useradd`/`chown -R` step, so both dirs are appuser-owned before any
  bind mounts land on top. Rebuilt, retagged `nfl-edge:v2-docker` to match,
  recreated all three containers. Verified `/app/data` is now
  `appuser:appuser`, `/healthz` returns 200 on all of 8503/8504/8505, and
  no errors in `nfl-edge-v2`'s logs.

## 2026-11-04 (chore: rebuilt Docker image, consolidated v2/v2-docker tags, restarted 8503-8505)

### Context
`nfl-edge:v2-docker` (used by the admin container on 8505) was a stale image
— built weeks before `nfl-edge:v2` and missing `beautifulsoup4` even though
it's in `requirements.txt`. The `bs4` fix from the previous entry was only
installed at runtime inside the live container, so it would have been lost
on the next recreate. Root-caused: both tags were built from the same single
`Dockerfile`, just at different times, so they'd drifted apart.

### Changed
- `docker build -t nfl-edge:v2 .` — fresh build from current source/
  `requirements.txt`. Confirmed `bs4` now present (`4.15.0`).
- `docker tag nfl-edge:v2 nfl-edge:v2-docker` — both tags now point at the
  identical, current image, eliminating the drift. No separate admin
  Dockerfile exists or is needed; the admin container already overrides
  `CMD` to `streamlit run admin.py` at `docker run` time.
- Recreated `nfl-edge-v2` (8503), `nfl-edge-v2-ypp` (8504), and
  `nfl-edge-v2-admin` (8505) from the rebuilt image, preserving each
  container's exact prior mounts/env/port mapping (captured via `docker
  inspect` beforehand). All three came up healthy; verified `bs4` and
  `sentiment` import cleanly inside the admin container.
- Left the individual file bind mounts (`sentiment.py`, `sentiment_lab.py`,
  `secrets.toml`, etc.) in place even though the image now bakes in current
  source — didn't want to silently change the live-edit deployment model
  this session relied on. Worth revisiting later: now that the image is
  current, those source-file mounts are redundant (data-file mounts like
  `ypp_coefficients.json` still aren't).

## 2026-11-04 (fix: OpenRouter key rotated; real sentiment data collected for current week)

### Context
Follow-up to the 2026-11-03 Sentiment Lab fix. The `OPENROUTER_API_KEY` was
invalid (401), blocking real data collection. User provided a new key.

### Changed
- `sentiment.py`: key lookup now checks `OPENROUTER_API_KEY` env var first,
  falling back to `.streamlit/secrets.toml` (same pattern as `db.py`'s
  Turso credential lookup) — avoids passing the secret as a literal
  `docker run -e` flag (shell history / `docker inspect` exposure).
- Added `OPENROUTER_API_KEY` to `/Users/jeff/nfl-edge/.streamlit/secrets.toml`
  (already mounted read-only into all v2 containers) — one line, with
  explicit user authorization for this specific edit to the v1 worktree.
- `nfl-edge-v2-admin`'s image (`nfl-edge:v2-docker`) was missing `bs4`
  despite it being in `requirements.txt` — installed at runtime to unblock
  testing; the image itself should get rebuilt eventually so this isn't lost
  again on next recreate.
- Ran real sentiment collection for the current week (Week 9 by the time it
  ran — confirms `current_season_week()` tracks correctly across day
  changes mid-session): 23 of 29 teams scored with real LLM output, 6 had no
  snippets available (Reddit 403s plus thin news/Exa results) and were
  correctly left unscored rather than stored with fake data.
- Note: editing `sentiment.py`/`admin.py`/`.streamlit/secrets.toml` on the
  host breaks their single-file Docker bind mounts (Docker Desktop mounts go
  stale when the source file is replaced via rename-on-save). Each edit this
  session required recreating `nfl-edge-v2`, `nfl-edge-v2-ypp`, and
  `nfl-edge-v2-admin` (same mounts/env, just re-attached) to pick up changes.

## 2026-11-03 (fix: Sentiment Lab was dead — local-SQLite isolation, hardcoded Week 4, silent LLM-failure corruption)

### Context
Same shape of bug as the 2026-11-01 YPP issue: `sentiment.py` stored scores
in local SQLite (`/app/data/nfl_edge.db`) instead of the shared Turso cache,
and the only code that collects scores (a button in `admin.py`) ran in a
different container (8505) than the one serving the Sentiment Lab tab
(8503/8504) — so the tab always showed `—`. Separately, both the tab and the
admin refresh button were hardcoded to `season=2026, week=4` rather than the
actual current week. While re-running collection for the real current week
(2026 Week 8), discovered `score_sentiment_llm()` was silently swallowing
`OPENROUTER_API_KEY` auth failures (401) and returning fake neutral
`{confidence:0, morale:0, controversy:0}` scores, which then got *stored* as
if real — corrupting 21 of 28 teams' Week 8 data with zero scores that would
have blocked all future re-collection (code treats "has a score" as "done,"
regardless of validity). The OpenRouter key itself is still invalid/expired;
real sentiment collection is blocked until it's replaced.

### Changed
- `sentiment.py`: migrated score + snippet storage from local SQLite
  (`ensure_sentiment_table`/`ensure_snippets_table`, now deleted) to
  `db.py`'s Turso-backed `cache_get`/`cache_set`, matching the
  `team_ypp_history` pattern. New key scheme:
  `sentiment_score:{team}:{season}:{week}:{source}`,
  `sentiment_snippets:{team}:{season}:{week}:{source}`.
- `views/sentiment_lab.py`: now reads via `sentiment.get_sentiment_score()`
  instead of a direct (and container-local) SQLite query.
- `views/sentiment_lab.py` and `admin.py` (score display, refresh button,
  sentiment-only picks table): replaced hardcoded `season=2026, week=4` with
  `data.current_season_week(games)` — the same helper already used by
  `app.py` and every `scripts/*.py`.
- `sentiment.py:score_sentiment_llm()`: on LLM/API failure now returns
  `None` instead of a fake neutral score, so callers skip storing bad data.
  `ensure_sentiment_for_week()` and `admin.py`'s refresh button both updated
  to check for `None` before storing. Also fixed `admin.py`'s refresh button
  to persist snippets (`stm.store_snippets`) so the Word Cloud feature has
  data to read — it never had before, even on a successful run.
- `db.py`: added `cache_delete(key)` (same pattern as `cache_set`), used to
  purge the 21 corrupted zero-score entries created above.
- The 33 real sentiment scores collected before this migration (under the
  old local-SQLite schema, in `nfl-edge-v2-admin`'s container-local
  `data/nfl_edge.db`) are orphaned — not migrated, since the new key scheme
  is unrelated and re-collection is cheap. They're stranded in a container
  filesystem that's itself disposable.
- `nfl-edge-v2`/`nfl-edge-v2-ypp` recreated (same mounts/env, no changes to
  what's mounted) after editing `sentiment.py` broke their single-file bind
  mount — Docker Desktop's bind mounts can go stale when the host source
  file is replaced via rename-on-save rather than edited in place; recreating
  the container re-attaches the mount to the current file.

## 2026-11-01 (fix: nfl-edge-v2-admin was isolated on a disconnected local SQLite fallback; YPP coefficients missing from v2/v2-ypp images)

### Context
`db.py`'s `_connect()` falls back to a local SQLite file
(`data/nfl_edge.db`) whenever Turso credentials aren't found. Unlike
`nfl-edge-v2`/`nfl-edge-v2-ypp` (which have v1's `secrets.toml` mounted),
`nfl-edge-v2-admin` never had Turso credentials, so every `shared_cache`
write it made (including a YPP data refresh run earlier today) landed in
this disconnected local file instead of the real shared Turso instance used
by the other two containers — invisible to them, and silently diverging.
Separately, `ypp_coefficients.json` (the fitted YPP model — `alpha`/`beta`/etc.)
was completely absent from the `nfl-edge-v2`/`nfl-edge-v2-ypp` images;
`ypp_model.py`'s `YPPModel.__init__` has no guard around `open()`, so it
raised `FileNotFoundError`, which `predictor.py:predict_game()` silently
swallows (`except Exception: ypp_spread = elo_spread`) — meaning
`nfl-edge-v2-ypp` (`USE_YPP=1`) has been running pure Elo this whole time
with no visible error.

### Changed
- `nfl-edge-v2-admin` recreated with v1's `.streamlit/secrets.toml` mounted
  read-only, giving it real Turso credentials for the first time. Verified
  connected to the same shared instance as `nfl-edge-v2` (matching
  `team_ypp_history` timestamp/row-count before refresh).
- Re-ran `scripts/compute_ypp_from_stats_team.py --years 2020..2026` and
  `scripts/fit_ypp_model_from_cache.py` inside the now-connected admin
  container, pushing a fresh `team_ypp_history` (3602 rows, seasons
  2020-2026) to the real shared Turso — previously stuck at 2718 rows /
  2021-2025 / ~41 days stale. Refit coefficients (n_samples 1408 → 1801).
- `nfl-edge-v2` and `nfl-edge-v2-ypp` recreated with a new read-only mount
  of v2's own `data/model_fits/ypp_coefficients.json` (no v1 involvement —
  pure v2-internal file). Verified `YPPModel()` now instantiates without
  raising in `nfl-edge-v2-ypp`, so `USE_YPP=1` is live for the first time.

## 2026-11-01 (dev: relay v1's live SGO/injury/roster data into v2 containers)

### Context
v2's own SGO odds pipeline is dead (monitor daemon down, feed 403ing since
Sep 27) and its YPP/snap/team-stat caches are stale, while v1
(`/Users/jeff/nfl-edge`) is confirmed to be fetching and refreshing this data
live. Rather than stand up a duplicate SGO fetcher (and burn a second
API-tier's worth of quota) while v2 is still in dev, the three v2 containers
now read v1's live files directly via read-only bind mounts — no network
calls of their own for this data. This is a dev-only bridge; v2 will run its
own equivalent pipeline in prod.

### Changed
- `nfl-edge-v2`, `nfl-edge-v2-ypp`, `nfl-edge-v2-admin` containers recreated
  with 5 new read-only mounts from v1's `data/`: `sgo_odds.json`,
  `sleeper_players.json`, `nflverse_injuries_2026.csv`, `player_stats_2025.csv`,
  `player_stats_2026.csv`. All other config (env, ports, restart policy,
  existing mounts/secrets) preserved exactly.
- `data.py`: `SGO_CACHE_MIN` (the 120-min disk-freshness gate in
  `_sgo_board_raw()`) is now overridable via `SGO_RELAY_CACHE_MIN` env var.
  Root cause: the gate exists to throttle *v2's own* SGO fetches against its
  paid-tier quota, but a relay container never fetches — it only reads a
  file whose own refresh cadence (v1's, every few hours) doesn't reliably
  land inside a 120-min window. Without the override, `cached_sgo_lines()`
  silently returned `None` even with a same-day mounted file.
  `nfl-edge-v2-admin` (the container lacking v1's `secrets.toml`, so it has
  no working Turso shared-cache fallback either) now runs with
  `SGO_RELAY_CACHE_MIN=720`. `nfl-edge-v2`/`nfl-edge-v2-ypp` already have
  v1's `secrets.toml` mounted and get a cache hit via Turso directly, so
  they didn't need the override, but all three were verified end-to-end
  (`cached_sgo_lines()` returns 27 books on each).

## 2026-10-29 (fix: admin.py — Overseer sides metrics, config-save wipe, history parsing, debug leaks)

### Fixed
- `admin.py`: Tab1 "💾 Save Configuration" rebuilt `new_config` from only the
  slider fields, silently dropping `superadmin_secret`/`market_weight`/any
  other untouched key on every save. Now spreads `**config` first so only
  the edited fields actually change.
- `admin.py`: `append_history()` assumed `backtest_results` was always
  `{market: {metric: value}}}`; `run_backtest()`'s actual shape is
  `{"output": ..., "metrics": {market: {...}}}`, so every props-backtest
  save was flattening the wrong (empty) dict into the CSV. Fixed with
  `backtest_results.get("metrics", backtest_results)`.
- `admin.py`: Tab4 Overseer reads `sides_win_pct`/`sides_roi`/`sides_clv`/
  `sides_n_picks` columns from `tuning_history.csv`, but nothing ever wrote
  them — the "✅ Apply Candidate Configuration" button called
  `append_history(candidate_config, test_name=test_name)` with no backtest
  results at all, so those columns were always empty and the Overseer's
  "best observed configuration"/Top-5 tables had nothing to rank. Root
  cause: a `run_sides_backtest()` function was referenced by two orphaned
  root-level scripts (`tune_iteration.py`, `test_save.py`) but never
  actually implemented in `admin.py`. Added `run_sides_backtest(config)`,
  which runs `scripts/walk_forward_sides_no_ypp.py`'s `evaluate_config()`
  against already-locally-cached data (`data/games.csv` +
  `dl.cached_sgo_lines()` — the same source the existing "Compute Edge
  Distribution" button already uses) — no live API calls — and returns
  `{"sides": {"n_picks", "win_pct", "roi", "clv"}}`, which
  `append_history()`'s existing flattening turns into exactly the
  `sides_*` columns the Overseer expects. Wired into the "Apply Candidate
  Configuration" button. Verified live against the real cached dataset
  (`docker exec nfl-edge-v2-admin`): returns real, non-error metrics, and
  flattens into the four expected `sides_*` CSV columns.
- `admin.py`: removed `print(f"[DEBUG] Password check: ...")` /
  `print(f"[DEBUG] Superadmin password check: ...")` (logged entered
  password hashes to container stdout on every login attempt), a stray
  `st.write(f"DEBUG: total_records={total_records}")` left in the Overseer
  tab's UI, and the now-unused `import hashlib`.
- Verified via `py_compile` and a live `nfl-edge-v2-admin` container check
  (HTTP 200, `run_sides_backtest()` invoked directly against real cached
  data with no errors) after each change — this container bind-mounts
  source directly, so no rebuild was needed.

### Not done this pass (deliberately deferred)
- The "✅ Apply Candidate Configuration" button still never calls
  `save_config()` — it only logs the candidate to tuning history, so
  "applying" a config doesn't actually change what's live. Needs its own
  pass.
- The "🚀 Run Walk‑Forward Backtest (2021‑2025)" button is still an
  unimplemented stub (`# TODO: implement`).

## 2026-10-25 (fix: Power Rankings legend toggle didn't stack)

### Fixed
- `views/rankings.py`: clicking a second team in the progression chart's
  legend reset the first team's toggle instead of stacking with it.
  Root cause: Altair's `selection_point(toggle=True)` serializes to the
  JSON boolean `true`, which Vega-Lite treats as its *default* value —
  "only toggle while shift is held" — not "always toggle." Passing the
  Vega expression **string** `"true"` instead of the Python bool is
  what actually forces always-toggle-on-plain-click. Verified empirically
  with a real headless-Chromium (Playwright) click sequence against the
  live SVG-rendered chart (`AppTest` can't exercise this — it never runs
  client-side JS/Vega-Lite interactivity): clicking team A fades only A;
  clicking team B fades B while A stays faded (stacked); re-clicking A
  restores it while B stays faded — independent per-team toggling as
  intended.

## 2026-10-25 (feature: Power Rankings season-progression chart)

### Added
- `predictor.py`: `Elo.__init__` now records `self.history`, a list of
  `(season, week, {team: rating})` snapshots taken at each week boundary
  during its single existing pass over games — no extra Elo refits, just
  bookkeeping added to the loop that was already running.
- `views/rankings.py`: new "📈 Season Progression" chart below the
  rankings table, rendered with `st.altair_chart` (ships with Streamlit,
  no new dependency). Click a team in the legend to isolate its line
  (shift-click to add more) via Altair's `selection_point(bind="legend")`
  bound to an opacity encoding. Switched the page to reuse one cached
  `shared.get_elo(ctx.games)` instance for both the current-standings
  table and the new history chart instead of constructing a second
  `pr.Elo` object.

## 2026-10-25 (hotfix: Bet Journal AttributeError)

### Fixed
- `views/journal.py`: crashed with `AttributeError: module 'db' has no
  attribute 'get_user_settings'` — `get_user_settings` lives in `shared.py`,
  not `db.py`. Fixed both call sites (`get_user_settings(ctx.USER)` and the
  `.clear()` cache-bust call) to use the correct import.
- `shared.py`: its own `get_user_settings()` called `db.get_user(username)`
  but the module never imported `db` — a latent `NameError` masked until the
  journal-page fix above actually exercised it. Added `import db`.
- `db.py`: `get_alert_prefs()` / `set_alert_pref()` (and `views/settings.py`'s
  alert-subscriptions UI) referenced `ALERT_TYPES` / `ALERT_CHANNELS`, which
  had been dropped entirely during an earlier refactor — a pre-existing
  `AttributeError` on the Settings page for every user. Restored both from
  git history (`ALERT_TYPES` labels, `ALERT_CHANNELS` tuple).
- `app.py`: removed a dead duplicate `get_user_settings()` (identical to
  `shared.py`'s, never called) found while fixing the above.
- All three are the same bug class as the earlier module-split breakage:
  a name moved/renamed during the `app.py` → `views/` split but a caller
  (or the function itself) wasn't updated. Verified via an `AppTest` sweep
  of all 13 nav pages for both an admin-tier and a synthetic unregistered
  user — zero exceptions (the Settings-page `me["email"]` crash seen with
  the synthetic user is expected: real users are always provisioned with a
  DB row at signup, so that path can't occur in production).

## 2026-10-25 (follow-up: suggestion fixes)

### Changed
- `app.py`: factored the 13 duplicated `AppContext(...)` construction sites
  into one `_build_ctx(page, injuries=injuries)` helper. Removed a dead,
  never-called module-level `form_df(team)` (the real one lives in
  `views/game_detail.py`). The Games page still overrides `injuries` with
  the richer nflverse report via `_build_ctx(page, injuries=nv_injuries)`.
- `predictor.py`: removed two debug `print()` statements (`market n_books=...`,
  `DEBUG kelly ...`) that fired on every request.
- `props_model.py`: removed two debug `print()` statements (`snaps_df
  columns: ...`, `required cols: ...`) that fired on every props-tab render.
- `sentiment.py`: added `@st.cache_data(ttl=600)` to `collect_reddit_snippets()`,
  `collect_exa_snippets()`, and `score_sentiment_llm()` so opening the
  Sentiment Lab tab repeatedly no longer re-fires Reddit/Exa network calls
  or LLM scoring on every rerun. Extracted the word-frequency tokenization
  logic out of `word_cloud_html()` into a pure `tokenize_for_wordcloud()`
  helper (no DB/network) so it can be unit tested directly; removed an
  unused `import re` found in the same pass.

### Added
- `tests/test_predictor_math.py`: unit tests for `american_to_prob()`, `devig()`,
  and `predict_game()`'s cover-probability + quarter-Kelly formulas.
- `tests/test_form_df.py`: unit tests for `views/game_detail.py`'s `form_df()`
  column mapping and sign/dash formatting (mocks `analytics.last_n`).
- `tests/test_sentiment_wordcloud.py`: unit tests for `sentiment.tokenize_for_wordcloud()`
  (stopword/short/numeric filtering, frequency counts).
  All three run both standalone (`python3 tests/test_*.py`, plain asserts)
  and under `pytest`; wired into `.github/workflows/grading-ci.yml` so they
  run on every PR. Verified green against the live `nfl-edge-v2-admin`
  container.

## 2026-10-25

### Fixed
- Repaired breakage left by the `app.py` → `views/` module-split refactor. A broad
  find/replace meant to rewrite bare variable references as `ctx.*` attribute
  accesses had also corrupted string literals, dict keys, and prose:
  - `views/game_detail.py`: fixed a nested-quote f-string `SyntaxError` (Python
    3.9 doesn't support PEP 701) in `form_df()`.
  - `views/game_detail.py`: fixed corrupted dict-key/string-literal lookups —
    `pred["mode"] == "ctx.elo-only"` → `"elo-only"`, `pred['p_ctx.elo']` →
    `pred['p_elo']`, `g['ctx.season']`/`g['ctx.week']` → `g['season']`/`g['week']`,
    and the `slip_tab()` journal dict keys `"ctx.season"`/`"ctx.week"` →
    `"season"`/`"week"` (these were silently writing bad keys into logged picks).
  - `views/game_detail.py`: fixed cosmetic `ctx.`-corrupted UI captions/docstrings
    (e.g. "his last 5 ctx.games" → "his last 5 games").
  - `views/game_detail.py`: removed two leftover `print(f"DEBUG UI kelly_...")`
    debug statements, and a duplicated/dead `BOOK_NAMES`/`_book_name`/`PROJ_COLS`
    block (the removed copy's `_book_name` was missing a `return`).
  - `shared.py`: fixed a truncated/orphaned trailing `@st.cache_data` decorator
    left over from the split.
  - `views/context.py` / `app.py`: added the missing `injuries_err` field to
    `AppContext` and threaded it through all 13 construction sites — this was a
    latent `AttributeError` waiting to fire on any injuries-fetch failure.
- Verified via `py_compile` across the repo and Streamlit's `AppTest` harness
  (per `DEPLOY.md`'s documented smoke-test step) running the real Games page —
  predictor, props, SGP, slip/journal, Sentiment Lab, and Handle tabs — with
  zero exceptions, as both a free-tier and admin-tier user.

### Changed
- `sentiment.py`: replaced the `subprocess`/`mcporter`/`opencli` shell-outs with
  direct HTTP calls — `collect_reddit_snippets()` now hits Reddit's public JSON
  API (`reddit.com/r/<sub>/hot.json`) and `collect_exa_snippets()` now calls
  Exa's REST search API (`api.exa.ai/search`) directly via `requests`. Reddit is
  re-enabled in `collect_all_snippets()` (previously commented out).
- `sentiment.py`: replaced `get_wordcloud_url()` (built a QuickChart.io image
  URL — an external, user-tracking-capable third party) with `word_cloud_html()`,
  which renders an inline HTML tag cloud from the same word-frequency data,
  sized/colored by rank, with no external request. Updated the call site in
  `views/game_detail.py`'s `sentiment_tab()` to render it via `st.markdown(...,
  unsafe_allow_html=True)` instead of linking out to an image.
- `views/game_detail.py`: renamed the "💰 HANDLE" tab label to "💰 Handle" (both
  the `st.tabs()` entry and the page subheader).

### Suggestions for further improvement (not done this pass)
- `app.py` constructs `AppContext(...)` from scratch at 13 separate call sites —
  worth factoring into one helper to stop this class of bug (a field added to
  the dataclass but missed at a call site) from recurring.
- `predictor.py` still has `print(f"DEBUG kelly ...")` / `print(f"[DEBUG] market
  n_books=...")` debug statements firing on every run — should be removed or
  gated behind a debug flag.
- `props_model.py` (or wherever the snap-count loader lives) prints `[DEBUG]
  snaps_df columns: ...` / `[DEBUG] required cols: ...` on every props-tab
  render — same cleanup.
- `sentiment.py`'s LLM scoring (`score_sentiment_llm`) and the new Reddit/Exa
  collectors have no retry/backoff and no caching — every Sentiment Lab tab
  open can trigger fresh network calls. Worth a short-TTL cache like the rest
  of `shared.py`'s data helpers.
- No automated test suite exercises the `views/` modules directly (only
  `AppTest`-level smoke testing was done this session) — unit tests around
  `form_df()`, `predictor_tab()`'s odds math, and the sentiment word-frequency
  logic would catch this class of corruption automatically next time.
