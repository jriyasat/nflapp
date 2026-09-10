# nflverse Data Upgrade — Full Integration Spec

**Status:** roadmap approved · reminder set for Oct 1, 2026 (Telegram) to kick off
**Prereq:** current stack (journal/parlays/props-cache/weekly-board) pushed live
**Proving ground:** V2 — a second LOCAL Docker container (`nfl-edge:v2`, port 8503).
V2 is local-only: **no Streamlit Cloud deploy**; V2 work lives on a GitHub **v2 branch**
(main auto-deploys to Cloud — never push V2 code to main). Merge to main only after
Jeff approves a phase.
**Rule:** every model-facing change ships through a backtest gate (props v2 precedent, see docs/BACKTESTS.md)

All six datasets are free, full-history downloads from nflverse-data GitHub releases — same
pattern as our existing `games.csv` / `player_stats` / `injuries` loaders (disk-cached, 12h TTL).

---

## Phase 0 — Foundation (data loaders, no model changes)

New module `nflverse_extra.py` with one cached loader per dataset. **Aggregate on load** —
we keep compact summaries, not raw play-by-play (a pbp season is 50MB+).

| Loader | Source (nflverse-data release) | Output we cache |
|---|---|---|
| `load_team_epa()` | `pbp/play_by_play_<yr>.parquet` | weekly team off/def EPA/play, success rate, PROE, pace |
| `load_snaps()` | `snap_counts/snap_counts_<yr>.csv` | player-week snap counts + snap share |
| `load_ngs()` | `nextgen_stats/ngs_<yr>_<passing|rushing|receiving>.csv` | RYOE, separation, cushion, time-to-throw |
| `load_qbr()` | `espn_qbr/qbr_week_level.csv` | QB week/season QBR grades |
| `load_ftn()` | `ftn_charting/ftn_charting_<yr>.csv` | pressures, drops, adjusted INTs |
| `load_depth_charts()` | `depth_charts/depth_charts_<yr>.csv` | official starter lists by team/position |

Plus: admin "Data Health" section (Settings page) — each dataset's freshness + row counts.

## Phase 1 — Props (our proven edge; first build)

- **Snap-share volume** replaces season-average volume in props_model (rush v2 + rec/pass v1)
- **NGS features**: RYOE into rush v2; separation/cushion into a candidate rec v3
- **Injury absorption**: starter OUT → redistribute that player's snap share to the next
  man up (uses depth charts)
- **Gate:** walk-forward backtest 2023–25 vs current v2 — must beat 61% lean hit-rate to ship

## Phase 2 — Injury pricing

- `injury_adjustment()` values keyed off **depth-chart role** (starter/backup) instead of flat
- QB-out: grade the **backup's QBR/EPA** — deduction = f(starter QBR − backup QBR), not flat −7/−3
- **Gate:** CLV judgment at the already-scheduled Nov 1 review (QB-out proxy cohort)

## Phase 3 — Team strength (spread model)

- Blend off/def EPA differential into the 15% non-market component (candidate replacement for Elo)
- Early-season: EPA updates weekly with current-year signal — no arbitrary Elo regression
- **Gate:** walk-forward vs the current 85/15 baseline on the same 1,359-game set; ship only if it wins

## Phase 4 — Totals model

- Pace (seconds/play), PROE, def EPA → replace blunt bucket adjustments (close-spread/blowout)
- Keep validated adjustments (wind, early-season, ref)
- **Gate:** backtest totals ATS vs current model

---

## Notes

- Disk footprint stays small: aggregated caches only (~few MB), raw files deleted after aggregation
- Everything is offline-reproducible: loaders re-pull + re-aggregate on cache expiry
- Each phase is independently shippable and independently revertible
