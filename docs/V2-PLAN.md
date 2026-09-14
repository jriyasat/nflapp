# V2 Session Plan — NFL Edge Finder

> **Status:** locked 2026-09-13 · build starts **Oct 1, 2026** (Telegram reminder `a4cdd03bcb90`)
> **Sources:** `docs/NFLVERSE-DATA-UPGRADE.md` (spec) · `docs/AUDIT-2026-09-10.md` (seam map) · `docs/V2-IDEAS.md` (idea log)
> **Branch rule:** all V2 work on `v2` — **never push to main** (main auto-deploys to Cloud). Merge per-phase only on Jeff's approval.

## Goal

Ship the nflverse data upgrade in five independently-shippable, independently-revertible phases (0–4), each model-facing change passing a backtest gate before merge. Plan locked before Oct 1; no code until then.

## Working agreements (from Jeff, 2026-09-13)

- **Timing:** plan now, build on Oct 1 as scheduled. No code before then.
- **Cadence (mixed):**
  - **Autonomous** sessions: data loaders, backtests, infra — completion report to Telegram alerts channel.
  - **Interactive** sessions: model decisions and every phase gate — Jeff makes the ship/no-ship call.
- **Proving ground:** second LOCAL Docker `nfl-edge:v2` on **:8503** (alongside `nfl-edge:local` :8502). V2 never deploys to Streamlit Cloud while in V2.
- **Spec rule:** every model-facing change ships through a backtest gate (props v2 precedent, `docs/BACKTESTS.md`).
- **Receipts principle (V2-IDEAS #2):** every V2 dataset bakes in "as-of" snapshots — loaders must be season/week-parametrized so backtests see only what was knowable at pick time.

## Golden rules carried from V1 (violations caused real outages)

1. `env -u PYTHONPATH` for every python/pip/script run in this project.
2. Module changes need a server **restart**, not a browser rerun.
3. Verify before merge: AppTest smoke over every page (auth preset) — **run inside Docker** (AppTest hangs in the desktop env, audit §5.8) — plus unit tests.
4. Secrets never in git. Additive-only DB schema (Phase 0 needs no DB changes — caches are disk).
5. Requirements pinned. Cron scripts: `_common.run` + `os._exit` on every path + 600s deadline.

---

## Session roadmap (S0–S15)

| Session | Phase | Content | Mode | Gate / output |
|---|---|---|---|---|
| S0 | — | **This plan** — lock roadmap + Phase 0 tasks on `v2` branch | done 9/13 | `docs/V2-PLAN.md` committed |
| S1 | 0 | V2 infra: Docker `:8503`, pyarrow, `_get_df()` primitive + tests | autonomous | primitive unit tests pass in Docker |
| S2 | 0 | CSV loaders: snaps, NGS ×3, QBR, FTN, depth charts | autonomous | 5 loaders cached + schema tests pass |
| S3 | 0 | Team EPA loader (pbp parquet, aggregate-then-delete) | autonomous | weekly EPA table cached, raw deleted, disk footprint small |
| S4 | 0 | Data Health admin section (Settings) + `data/health.json` silent-failure logging (audit §5.7) | autonomous → **interactive checkpoint** | Jeff eyeballs Data Health in :8503 → Phase 0 sign-off |
| S5 | 1 | Snap-share volume slot 1: recency-weighted snap share replaces season-average (`props_model.py:~120`; fold in audit §4 unweighted-mean fix) | autonomous | walk-forward 2023–25 backtest run |
| S6 | 1 | Injury absorption (depth-chart redistribution, slot 2 `:131-135`) + NGS RYOE → rush v2; separation/cushion → candidate rec v3 | autonomous | backtest vs current props v2 |
| S7 | 1 | **GATE:** props walk-forward must beat **61% lean hit-rate** | **interactive** | Jeff ship/no-ship → merge or revert |
| S8 | 2 | Role-keyed `injury_adjustment()` (starter/backup via depth charts); QB-out = f(starter QBR − backup QBR) | autonomous | QB-out proxy cohort flagged for CLV tracking |
| S9 | 2 | **GATE:** CLV judgment at the already-scheduled **Nov 1 review** | **interactive** | Jeff ship/no-ship |
| S10 | 3 | EPA differential → 15% non-market component (candidate Elo replacement); weekly early-season EPA signal | autonomous | walk-forward vs 85/15 baseline, 1,359-game set |
| S11 | 3 | **GATE:** spread model walk-forward — ship only if it wins | **interactive** | Jeff ship/no-ship |
| S12 | 4 | Pace (sec/play), PROE, def EPA → totals; keep validated adjustments (wind, early-season, ref) | autonomous | totals ATS backtest vs current |
| S13 | 4 | **GATE:** totals backtest review | **interactive** | Jeff ship/no-ship |
| S14 | — | V2 wrap: merge summary, DEPLOY.md update, V2-IDEAS.md review (new sparks captured during build) | interactive | V2 closed out |

**Calendar pressure:** the Phase 2 gate is a *live* CLV review on Nov 1 — S5–S8 must land by **~mid-October** so the QB-out cohort accumulates closing-line receipts. Phases 0–1 are the priority path; Phases 3–4 can slip without blocking anything.

**Deferred decisions (need Jeff's go, not scheduled):** audit §5 proposals — app.py split into `views/`+`core/` (recommended *alongside Phase 0*, would slot in as S4b), lazy tab rendering, Turso retention prune, bulk DB writes, password policy, gitleaks CI.

---

## Phase 0 — detailed tasks (S1–S4)

New module `nflverse_extra.py`, one cached loader per dataset. **Aggregate on load** — compact summaries only; raw pbp deleted after aggregation (a pbp season is 50MB+). All six are free full-history downloads from nflverse-data GitHub releases, same pattern as existing `games.csv` / `player_stats` / `injuries` loaders (disk-cached, 12h TTL).

### Task 1 (S1): V2 Docker proving ground

**Objective:** isolated V2 runtime so `main` and the V1 app are never touched.

**Files:** `Dockerfile` (existing, reused), `DEPLOY.md` (V2 container row, on v2 branch only)

**Steps:**
1. Build image: `docker build -t nfl-edge:v2 .`
2. Run: port **8503**, same secrets mounts as `nfl-edge:local` (:8502), non-root.
3. Verify: container serves the unchanged app at localhost:8503.
4. Add V2 container row to DEPLOY.md cron/ops tables.

**Verify:** `docker ps` shows `nfl-edge:v2` on :8503; page loads; `main` branch working tree untouched.

### Task 2 (S1): pyarrow dependency

**Files:** `requirements.txt`

**Steps:** add pinned `pyarrow==<current stable>`; rebuild `nfl-edge:v2`; `python -c "import pyarrow.parquet"` inside container.

**Verify:** import succeeds in container; Cloud requirements unchanged on main (this edit lives on v2 only until merge).

### Task 3 (S1): `_get_df()` loader primitive

**Objective:** audit §4 — thin generalization of `_get_json` (data.py:124) for DataFrames, **not a rewrite**.

**Files:**
- Create: `nflverse_extra.py`
- Test: `tests/test_nflverse_extra.py`

**Steps:**
1. `_get_df(url, cache_name, max_age_hr, fmt)` mirroring `_get_json` semantics: TTL check via `_fresh()`, atomic write (tmp+rename), stale-cache fallback on fetch failure, memoize-by-mtime like `espn_injuries`.
2. `fmt in {"csv","parquet"}`; parquet via pyarrow.
3. Optional `aggregate_fn` hook: if provided, raw download goes to a temp file, `aggregate_fn(raw_path) -> df`, raw deleted, only aggregate cached (pbp pattern).
4. Unit tests: fresh-hit (no fetch), expired→refetch, fetch-failure→stale served, aggregate path deletes raw.

**Verify:** `env -u PYTHONPATH python -m pytest tests/test_nflverse_extra.py -v` passes **inside the v2 container**.

### Task 4 (S2): CSV loaders (5 of 6)

**Files:** `nflverse_extra.py`, `tests/test_nflverse_extra.py`

| Loader | Source (nflverse-data release) | Cached output |
|---|---|---|
| `load_snaps(season)` | `snap_counts/snap_counts_<yr>.csv` | player-week snap counts + snap share — **one row per player-week** (audit landmine: dedupe before any merge) |
| `load_ngs(season, stat_type)` | `nextgen_stats/ngs_<yr>_<passing\|rushing\|receiving>.csv` | RYOE, separation, cushion, time-to-throw |
| `load_qbr()` | `espn_qbr/qbr_week_level.csv` | QB week/season QBR |
| `load_ftn(season)` | `ftn_charting/ftn_charting_<yr>.csv` | pressures, drops, adjusted INTs |
| `load_depth_charts(season)` | `depth_charts/depth_charts_<yr>.csv` | starter lists by team/position |

**Landmines (audit §4):** join on `player_id`, never name; season/week-parametrized from day one (as-of snapshots, V2-IDEAS #2); team normalize `LA→LAR` on load (same fix as `load_games`/`load_player_stats` — apply to every V2 loader).

**Tests:** schema asserts (expected columns), row-count sanity per season, one-row-per-player-week for snaps, no `"LA"` team values anywhere.

### Task 5 (S3): team EPA loader (the heavy one)

**Files:** `nflverse_extra.py`, `tests/test_nflverse_extra.py`

**Steps:**
1. `load_team_epa(season)`: stream `pbp/play_by_play_<yr>.parquet` via the aggregate path from Task 3.
2. Aggregate to weekly team off/def EPA/play, success rate, PROE, pace (sec/play).
3. Raw parquet deleted post-aggregation; cache is the compact weekly table (~KBs).

**Tests:** aggregate shape (32 teams × weeks), no raw `.parquet` left in cache dir, EPA values in sane range (|EPA/play| < 1).

### Task 6 (S4): Data Health admin section + silent-failure logging

**Objective:** spec's "Data Health" Settings section + audit §5.7 (`except: pass` swallows loader failures invisibly).

**Files:** `nflverse_extra.py` (health hooks), `app.py` (Settings page, admin-gated), `data/health.json` (gitignored)

**Steps:**
1. Every V2 loader records `{dataset, last_fetch, last_success, rows, source}` to `data/health.json` on success/failure.
2. Settings → Data Health (admin tier only): per-dataset freshness, row counts, last error.
3. Wire existing V1 loaders into the same health file where they currently `except: pass`.

**Verify in :8503:** fresh container → cold load of all six → Data Health shows green with row counts; kill network → reload → stale served + health shows stale flag.

### Task 7 (S4): Phase 0 gate

1. AppTest smoke over every page in Docker (auth preset `authentication_status=True`).
2. Full unit suite in container.
3. `git ls-files` clean of secrets/data.
4. **Interactive checkpoint:** Jeff opens :8503, eyeballs Data Health → signs off Phase 0.
5. Telegram completion report (away-mode format): what shipped, what you'll see, next session.

---

## Phases 1–4 — build briefs (detail expanded at each phase kickoff)

**Phase 1 — Props (S5–S7).** Snap-share volume replaces season-average volume at `props_model.py:~120` (recency-weighted; fold in the audit's unweighted-2-season-mean fix — don't patch v1). Injury absorption redistributes an OUT starter's snap share to next-man-up via depth charts (`:131-135`). NGS: RYOE → rush v2; separation/cushion → candidate rec v3. **Gate:** walk-forward 2023–25 vs current props v2 — must beat **61% lean hit-rate**.

**Phase 2 — Injury pricing (S8–S9).** `injury_adjustment()` keyed off depth-chart role instead of flat values; QB-out deduction = f(starter QBR − backup QBR/EPA), not flat −7/−3. **Gate:** CLV judgment at the Nov 1 review (QB-out proxy cohort) — calendar-bound, builds must land by mid-Oct.

**Phase 3 — Team strength (S10–S11).** Off/def EPA differential blended into the 15% non-market component (candidate Elo replacement); weekly current-year EPA signal replaces arbitrary early-season Elo regression. **Gate:** walk-forward vs the 85/15 baseline on the same 1,359-game set — ship only if it wins.

**Phase 4 — Totals (S12–S13).** Pace, PROE, def EPA replace blunt bucket adjustments (close-spread/blowout); keep validated adjustments (wind, early-season, ref). **Gate:** totals ATS backtest vs current model.

---

## Risks & open questions

| Risk / question | Mitigation |
|---|---|
| pbp parquet is 50MB+/season — memory pressure in container | aggregate streaming per-season; raw deleted immediately; test on oldest season first |
| FTN charting coverage is partial (not all games charted) | loader records coverage in health.json; Phase 1/2 features degrade gracefully when FTN missing |
| Phase 2 gate is calendar-bound (Nov 1) | S5–S8 prioritized; if S8 slips past ~Oct 15, gate slides to a later review — Jeff decides |
| app.py split (audit §5.2) would conflict with every V2 app.py touch | Jeff's call: slot as S4b *before* Phase 1, or defer to post-V2 |
| AppTest hangs in desktop env | all smoke runs inside Docker; investigate root cause only if it starts failing in Docker too |
| Backtests need historical as-of data (lines, injuries) | Turso `line_history`/`predictions` are insert-only since V1 — verify coverage for 2023–25 walk-forward at S5 kickoff; gap-fill from nflverse loaders where needed |

## Merge protocol (every phase)

1. Gate passes + Jeff approves → PR-style diff review of `v2` phase commits.
2. Merge to `main` → Cloud auto-deploys (~2 min) → verify prod.
3. Phase marked shipped in this file + DEPLOY.md; revert path noted (each phase is independently revertible).
