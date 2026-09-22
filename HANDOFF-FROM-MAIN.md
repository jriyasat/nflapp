# Handoff from main (kimi-k3 session, 2026-09-21) — read before continuing v2 work

Main moved on 2026-09-20/21 with fixes v2 MUST port or consciously supersede.
Main is at `15b8692` + docs `d974ed4` (+ the phantom-line commit below, pending push
at time of writing — check `git log main`).

## 1. Phantom-line picks bug (the big one — broke the model's receipts)

**Symptom:** spread record 3-14 while CLV showed an impossible +9.5 avg / 88% beat-close.

**Root cause chain:**
- `scripts/morning_brief.py` fetched odds LIVE (`dl.sgo_lines(key)`) instead of reading
  the Turso shared cache. When that fetch failed or returned partial slates, games fell
  through to `predict_game`'s fallback market paths (espn_ml / nflverse schedule line).
- Edges computed vs fallback lines are phantom: logged "market" lines were 6–28 pts off
  the true market, several with the favorite sign-flipped. 10 picks (W1: SF@LAR,
  CHI@CAR, ARI@LAC; W2: 7 of 8) logged garbage, all graded as losses vs real closings.
- Grading itself was verified correct (all 17 picks recompute); closing lines are
  consistent (nflverse ≈ SGO frozen pre-kickoff, within ~1 pt). Totals were unaffected
  (their fallback market is the real total_line).

**Fix on main (port this):**
- `predictor.py`: `predict_game` now returns `market_src` ∈ {"books","espn_ml","nflverse",None}.
- `tracker.log_predictions`: spread picks log ONLY when `market_src == "books"`.
- `app.py` `_board_rows`: Edge column shows "—" unless `market_src == "books"`
  (no ★ phantom value on display).
- `scripts/morning_brief.py`: books now come from `dl.cached_sgo_lines()` (shared cache,
  same lines the app shows, zero quota). NEVER a live odds fetch in any cron script.
- `db.py`: additive `predictions.flag TEXT` column (migration in `_ensure_user_cols`);
  `_PICKS_COLS` includes it. Corrupted picks flagged, excluded from
  `tracker.summary/edge_buckets/calibration` (see `tracker._clean`), still shown in the
  All picks table with ⚠️. `recap_sections` also filters flagged.
- Result: record now reads spread 3-4-0 / total 9-9-0 clean.

## 2. Other main fixes to port

- `data.py load_games`: overdue-results refetch restructured BEFORE the memo early-return
  (was dead code → finals lagged up to 12h on cloud). Throttled via
  `_MEMO["games_refetch_ts"]` (1/hour).
- `data.py nflverse_injuries`: in-season guard — never fall back to prior-season file
  once the season has started (fetch failure → "unavailable", not ancient data).
- `data.py _PS_COLS`: includes `rushing_tds` (you already have this via aa7f750).
- `app.py`: ET "last updated" stamps (`_et()` helper, `_lines_updated_at()` reads the
  Turso payload timestamp first — disk-only checks show "—" on Cloud); Track Record
  All-picks row highlighting by grade + 1-decimal formatting.
- Cron (no code): Injury Report Watch now runs */30 8–21 Wed–Mon (was Wed–Fri only —
  MNF teams' Saturday reports never alerted).

## 3. Process rules (DEPLOY.md "Rules" section, read it)

- `~/nfl-edge` stays on `main` ALWAYS — crons + 8501 run from it. Your checkout of v2
  there on 2026-09-21 crash-looped Value Radar and killed the Morning Brief
  (`KeyError: 'n'`) because v2's data.py dropped `cached_sgo_lines`.
- v2 work happens HERE (`~/nfl-edge-v2`) or the :8503 container.
- **Keep data.py's public API backward-compatible** (`cached_sgo_lines`,
  `_sgo_board_raw`, `nflverse_injuries`, `load_games`, `load_player_stats`,
  `TEAM_NAME_TO_ABBR`, `current_season_week`...) — cron scripts import them directly.
- Your 3 WIP stashes are repo-global (`git stash list`); pop them in THIS worktree.
  Note `bf5ec62` already re-did the predictor YPP hook, so stash@{2} may be redundant.

## 4. Verification pattern expected before any v2→main merge proposal

- `env -u PYTHONPATH .venv/bin/python3` unit checks + AppTest smoke (zero exceptions
  across pages); the phantom-line guard test: with `books_by_abbr={}`,
  `log_predictions` must insert ZERO spread picks (monkeypatch `db.insert_pick` to
  capture, never write prod DB from a test).
