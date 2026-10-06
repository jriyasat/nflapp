# Handoff from main (kimi-k3 session, 2026-09-21, updated 2026-09-24) — read before continuing v2 work

Main moved on 2026-09-20/21 with fixes v2 MUST port or consciously supersede.
Main is at `892de00` (2026-09-24) — check `git log main` for anything newer.

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

## 5. SGO prop lines: filter periodID == "game" (fixed on main a6d697e — port to v2 TD props)

SGO returns prop lines for multiple PERIODS (game/1h/1q/2q/3q/4q) under the same
statID+player — 73% of entries are partial-game. Main's `_sgo_event_props` pooled them
into the median, so Stafford showed "over 124.5" (the 1H line) instead of 238.5 (the
game line) — every SGP/Props edge was phantom and nothing matched the book's card.
Fix: keep only `periodID == "game"` entries. Your TD-prop parsing (rushing/receiving/
passing_touchdowns) MUST apply the same filter or it inherits the bug.

## 6. SGP combos: one appearance per leg (main 6a54200)

`best_combos` returned the raw top-6 pairs, so hot legs repeated across rows (Game
OVER appeared in 3 of 6 combos — looked broken to users). Now greedy: sorted by score,
a combo is kept only if neither leg ID was already used. Port if v2 touches sgp.py.

## 7. Manual injury outs (main 50918af) — v2 must respect these

`dl.manual_outs()` (Turso shared_cache key "manual_outs") is Jeff's week-scoped bench
list for news-known outs before the official report publishes (Mon–Wed blind spot).
`dl.apply_manual_outs(nv, season, week)` merges them into the injury dict ONLY while a
team's official report is stale (label week behind); official data always wins once
current. Any v2 code that builds its own injury path (props benching, spread
adjustment, TD props) MUST call apply_manual_outs or the manual benches silently
disappear. Admin UI: Settings → 🚑 Manual injury outs.

## 8. Sleeper fast injuries (main, post-50918af) — layered injury precedence

Injury data now has THREE layers, merged in this exact order (later never overrides
earlier): official nflverse report (wins once current) > `apply_manual_outs` (Jeff's
list) > `apply_sleeper_outs` (Sleeper API, free/keyless, tracks news in hours).
Sleeper merges ONLY Out/Doubtful — NOT IR (long-term, market-priced; the spread
deduction was calibrated on fresh weekly outs) and NOT Questionable (noise). Merge
applies only while a team's official report is stale; rows labeled
'via Sleeper (unofficial)'. Wired into app, morning_brief, value_radar, and
injury_report_watch (fast Out alerts). Any v2 injury path MUST apply all three
layers in this order.

## 9. Post-Sleeper main changes (through 892de00, 2026-09-24)

- `analytics.py` TEAM_TZ: `"LA"` → `"LAR"` (the fourth LA/LAR silent-miss — Rams
  body-clock spot never fired). Check v2's analytics.py for the same.
- Pick'em lock now fails CLOSED everywhere (`app.py _kickoff_passed`,
  `db.save_pickem`, `db.delete_pickem`): when schedule data can't be verified,
  the write is REFUSED (was: allowed — a data hiccup could bypass the lock).
- Track Record page is era-segmented (main baa3cc9): "Post-Fix Era (Week 3+)"
  headline + all-time below + honest W1-2 disclaimer. Don't clobber it in a merge;
  v2 model versions should slot INTO this era framing (a pick stamps its weights
  version — your weight-version attribution work aligns).
- External audit (Sep 2026, third party) cleared the security posture; remaining
  accepted items: no login rate-limiting (deferred), 6-char password min (bump
  before public signups), ~90 deliberate silent excepts (watchdog design;
  `data/health.json` observability planned on main).

## 10. team_ypp_history is the single team-stats source

`team_ypp_history` (Turso shared_cache, 2,718 team-games, 2021–2025 seasons) is the
canonical 5-season YPP database — the YPP coefficient retrain (1,274 games) and any
walk-forward backtest must use it. The parallel `sgo_team_stats` cache is PARTIAL
(228 rows, 2 teams) and your own code already calls it "often malformed" and skips
it — fix it or drop it; two competing stat stores is how phantom data happens.

## 13. SGO key discipline (2026-09-26 — v2 exhausted a full monthly quota)

- **v2 uses ONLY its own key** (`nfl-edge-v2/data/sgo_api_key.txt`, the
  8a9acd37… key — SEPARATE SGO account, own 2,500-entity/month quota).
  Jeff approved this. Never copy main's key (0861e3ab… — that account is
  production's line supply; touching it is what stale-served prod for ~4 days).
- **Fetch-once-cache-forever still applies**: 2,500 entities/month goes fast
  on history pulls (v2 burned a full month in days). All historical work should
  prefer the cached data: `team_ypp_history` in Turso (5 seasons) + the raw
  JSON dumps in `data/`. Live pulls only for genuinely new data, budgeted.
- Do not bake keys into docker images (the 8504 image had one baked in);
  keys live in `data/` (gitignored + dockerignored) only.
- Main's Lines Warm writer (4x/day ≈ 64 entities/day on the prod account) is
  the only sanctioned consumer of the production key.

## 11. Main changes through e13590c (2026-09-26) — SGP/props display layer

- **SGP legs are model-lean-only** (`sgp.build_legs` skips legs where
  `leg_prob < 0.5`): an "over" leg the model projects below the line is a
  contradiction (Allen proj 226 offered as "over 239.5"). If v2 adds UNDER legs,
  the lifts were measured on over-combos only — they need their own study.
- **SGP "Avg book price" column**: needs `over_price_avg`/`under_price_avg` (mean
  across books) from `_sgo_event_props` → carried through `edges_vs_lines` →
  `sgp.build_legs` (`price_avg`) → combined with `sgp.parlay_american`. Green when
  longer than fair. If v2 changes the props parsing, keep these fields.
- **L5 fix**: projection rows now carry `player_id` (the hit-rate lookup silently
  failed without it — column was always blank). L5 = last 10 games (code and
  caption now agree).
- **Manual prop-line buttons removed** (refresh / load-live): lines ride the slate
  fetch; don't reintroduce a per-user live-fetch path.
- **Injuries tab** shows "🕐 updated <ET>" (`dl.injury_report_updated_at`) + a
  midweek note when only practice data is posted.
- **Backtest graveyard (read docs/BACKTESTS.md before proposing angles):** division
  dogs, temperature, TNF, bye fade, body clock, pace differential, dome/indoor,
  QB-out totals (market now OVERCORRECTS, −30% ROI 2024-25), WR1-out, RB1-out —
  ALL DEAD with numbers. Do not re-test these; new candidates need a mechanism
  that isn't market-visible timing.

## 12. Experiment Lab decisions (locked with Jeff 2026-09-24)

- Volume factors are **props-only**: `props_pass_volume_factor` /
  `props_rush_volume_factor`. Do NOT add a sides volume weight — it's an
  unvalidated adjustment; YPP already carries the efficiency signal. Any future
  sides adjustment must earn in via the walk-forward gate like everything else.
- `ypp_weight`/`elo_weight` mix WITHIN the 15% prior; the 85% market anchor is
  unchanged (add that sentence inline in the Lab).
- Apply is DISABLED until `test_name` is non-empty (Save draft stays free-form).
  These three are the audit's first checklist items.
