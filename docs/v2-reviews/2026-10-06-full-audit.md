# V2 Full-Branch Audit — 2026-10-06 (kimi-k3, merge gate)

Scope: `main..origin/v2` @ `f7f6c4a` — 24 commits, 75 files, +7,495/−1,067 (merge-base `a95fe3e`, 2026-09-13).
Method: three parallel auditors (gate compliance / Experiment Lab+weights / sentiment+scripts), headline claims independently spot-verified by the gate before publishing.

## VERDICT

**v2 is NOT merge-ready, and its own tuning results are currently untrustworthy.** The walk-forward backtest family grades ATS with a flipped sign (corrupting every win%/ROI/CLV number v2 was tuned on), the admin backtest never reads real book lines (wrong dict key), 3 of 4 mandated props/SGP data-chain fields were not ported, and merging today would delete live main features (gust paper-trades, pipeline health, experimental picks, BACKTESTS.md ledger). The locked Experiment Lab *engine* decisions hold; the *UI* layer of those decisions is missing or regressed.

---

## 1. Gate audit (spot-verified ✓)

| # | Item | Result |
|---|---|---|
| 1 | SGO key discipline (own account, no hardcoded keys, cache-first) | **PASS** — note: `fetch_sgo_history.py:39` caches immutable history only 24h → quota re-burn on reruns |
| 2 | Secrets hygiene | **CONCERN** — no real tokens committed, but `config/model_weights.json` + `_tune.json` contain `"admin_secret": "admin123"` / `"superadmin_secret": "superadmin123"` in a public repo |
| 3 | Additive-only schema | **PASS** — sole change: `predictions ADD COLUMN config_hash` |
| 4 | Three-layer injury precedence at every consumer | **PASS** — exact match to main |
| 5 | spread_line convention (AWAY-perspective) | **FAIL** — see 2A |
| 6 | Props/SGP data-chain port | **FAIL** — see 2B |
| 7 | Divergence from main | **CONCERN (severe)** — 20 files modified on both sides; merge traps below |

## 2. Critical defects (all spot-verified at the gate)

**2A. v2's entire walk-forward family grades ATS sign-flipped.**
`walk_forward_sides_no_ypp.py:~106-148`: `market_spread = -float(r["spread_line"])` then `home_cov = result − market_spread` ⇒ evaluates `result + spread_line` — the opposite of correct (home covers iff `result > spread_line`). Same pattern in `walk_forward_sides.py:139`, `walk_forward_debug.py:88`, `ypp_enabled_backtest.py:58`, `quick_test.py:62`, `debug_edges.py:33`, `config_backtest.py:44+`. **Every v2 tuning win%/ROI/CLV figure is unreliable.** Compounding: `admin.py:944` reads `market.get('spread')` but `predictor.consensus()` only emits `home_spread` → always None → admin backtests silently use fallback lines labeled `market_src='books'`.

**2B. 3 of 4 mandated data-chain fields not ported.**
`over_price_avg`/`under_price_avg`: zero hits in v2 (Avg-book-price chain broken) · `player_id` missing from projection rows (L5 hit-rate permanently blank — the exact bug main fixed) · no `p_over < 0.5` lean filter in `sgp.py` (contradiction legs possible). Ported correctly: `periodID=='game'` filter, greedy leg-dedupe in `best_combos`.

**2C. "CLV" in v2 tuning is not CLV.** `walk_forward_sides_no_ypp.py:177`: `clv = sub["edge"].mean()` — mean model edge at the same closing line that generated the pick; no take-at/close pair exists. Every negative "CLV" in `tuning_history.csv` is this mislabeled statistic.

**2D. The "no_ypp" backtest silently includes YPP**, and the YPP coefficients are **in-sample** (fit on full 2021–25, then used "point-in-time" in the same span). Live coefficients file (untracked) says n=1,408, R²=0.133 — not the committed claim of 1,274/R²=0.170.

## 3. Experiment Lab locked decisions

- **Props-only volume factors: engine PASS / plumbing+UI CONCERN.** No `sides_volume_weight` anywhere ✓; readers accept new keys ✓. But admin **Save writes the OLD keys** (`admin.py:750-751`), `model_weights_tune.json` is an orphan (nothing reads it), and UI text still claims volume factors move sides/totals (the killed coupling).
- **ypp/elo within the 15% prior: engine PASS / docs FAIL.** 85% anchor untouched and normalized correctly (`predictor.py:33-43`). The required inline UI sentence about the anchor does not exist anywhere in `admin.py`.
- **Apply blocked until test_name: FAIL (feature absent).** No Apply button and no test_name input exist in v2's admin at all; Lab backtest button is a stub ("not yet implemented", `admin.py:1026-1031`); unlabeled rows already pollute `tuning_history.csv` (6/28 NaN, one row with `ypp_weight=33.97` unit corruption, exact duplicates).
- **PASS:** `predict_spread` sign (verified empirically), USE_YPP default off, config_hash attribution on logged picks end-to-end.

## 4. Sentiment layer

**Safe today by accident, not by gate.** `predictor.sentiment_adjustment()` is dead code (never called), so no logged pick is sentiment-influenced. But `config/model_weights.json` ships `sentiment_weight: 0.09`, admin has an "Enable sentiment layer" checkbox, and there is no `USE_SENTIMENT` flag or pick-flagging — one line away from leaking an unvalidated adjustment into every logged pick. The forward test is vacuous (enhanced arm sets a weight `predict_game` ignores → "picks changed" is guaranteed 0/N); the lab page is frozen at week 4; storage is container-local sqlite at hardcoded `/app/...` contradicting its own Turso doc; `sentiment_forward_test.sh` calls `.venv/bin/python` which doesn't exist in the worktree.

## 5. Regressions a v2→main merge would bring

- **Deletes `tracker.log_gust_papers`** (the live gust paper-trade experiment, main `9472d53`) ✓ verified
- **Deletes `scripts/_common._health_record`** (pipeline health, main `d8dede8`)
- **Drops `experimental` from `_PICKS_COLS`** + **fail-open pick'em lock** (main made it fail-closed)
- `scripts/inactives_watch.py` **re-adds dead `import db`** (main's hour-long-hang class); `injury_report_watch.py` drops `run(main)` (loses alarm deadline + health)
- `morning_brief.py:61-63` **KeyError 'n'** (uses old summary schema) + recap counts flagged phantom rows again
- `docs/BACKTESTS.md` loses 123 lines (graveyard ledger gutted); main-only files (`docs/props-system-diagram.*`, `docs/v2-reviews/`) would be delete-traps in a naive merge
- v2 still carries the prop-line live-fetch buttons main removed; orphans: `sgo_monitor_daemon.py`, `fetch_sgo_history_to_db.py` (writes to the malformed `sgo_team_stats` store), `sides_detailed_report.py`, `scan_td.py`, ~10 one-off ypp/debug scripts

## 6. Required before merge (in order)

1. Fix `home_cov` sign + `market.get('home_spread')` key; **re-run all tuning backtests** — every current number is suspect.
2. Remove in-sample YPP leak (cutoff fit); reconcile coefficients file with claims.
3. Port `player_id`, `over_price_avg`, lean-only SGP legs.
4. Gate sentiment like YPP (default-0 weight + `USE_SENTIMENT` env flag + flag any sentiment-influenced logged pick).
5. Land the Experiment Lab UI decisions (Apply/test_name, 85% inline doc, Save writes new keys, fix coupling text); clean the corrupt CSV row.
6. Replace fake CLV with real take-at/close pairs or rename the metric.
7. Reconcile the 20 shared files deliberately (main's gust papers, health, experimental picks, BACKTESTS ledger, fail-closed lock must survive).
8. Rotate `admin123`/`superadmin123` out of the committed config.

*Gate: kimi-k3 · Evidence: file:line throughout · Full auditor transcripts: session deleg_a87d1916*
