# Changelog

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
