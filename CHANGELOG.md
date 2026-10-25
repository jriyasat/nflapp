# Changelog

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
