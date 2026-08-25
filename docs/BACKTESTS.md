# Model Backtest Ledger

*Honest record of what's validated and what isn't. Updated Aug 24, 2026.*

## Spread model — end-to-end (`scripts/backtest_model.py`)

Walk-forward, point-in-time Elo, spread map fit 2015–2020, graded vs closing lines,
1,359 games (2021–2025 REG):

| Edge threshold | n | ATS% | ROI (−110) |
|---|---|---|---|
| ≥ 0.5 | 485 | 49.3% | −5.9% |
| ≥ 1.0 | 108 | 51.9% | −1.0% |
| ≥ 1.5 | 21 | 66.7% (noise) | +27.3% |
| ≥ 2.0 (production) | **1** | — | — |

**Conclusion:** the market+Elo+rest core almost never fires (once in 5 years at the
production threshold) and shows no reliable edge when it does. Model margin MAE ≈
market MAE (9.77 vs 9.75). The blend is a no-bet machine by design — spread picks
in practice come from the injury module.

## Injury module (`scripts/backtest_injury.py`)

Absences proxied from weekly player stats (primary QB = cumulative attempts leader,
top-3 skill by usage; week 18 excluded), 702 QB-out team-games 2021–2025:

- One-sided QB out: affected team ATS 52.6% (home) / 49.7% (away), shortfall vs
  closing +0.01 / −0.59 pts → **the closing line fully prices QB absences.**
- Simulated injury-driven picks: **48.8% ATS, −6.7% ROI at ≥2.0** — losing at every
  threshold, every season 2022–2025 individually.

**Conclusion:** dead vs closing lines. Any real value must come from *timing* —
firing on fresh injury news before books move (impossible to measure with
closing-line data). **Decision (Jeff, Aug 24): keep the module as-is, judge the
live picks on CLV, decide at midseason.** If picks show positive CLV but keep
losing ATS → timing edge real but too small; if CLV negative → kill or
freshness-gate the module.

## Component backtests (validated earlier, `scripts/backtest_spots.py`, `backtest_elo.py`, `backtest_totals.py`)

| Component | Result | Verdict |
|---|---|---|
| Pure Elo vs closing | 51.1% ATS (n=1,359) | ❌ below breakeven — hence 85% market weight |
| Elo calibration | predicted≈actual across buckets | ✅ honest probabilities |
| Home fav 7+ angle | 62.5% ATS (n=112) | ✅ badge only (small n) |
| Wind 15+ unders | 60.9% (n=87) | ✅ totals adj −2.7 |
| Rest 3+ days | 47.0% ATS (n=285) | ✅ fade −0.5 |
| Totals adjustments | see backtest_totals.py | ✅ in production |

## Props v2 backtest (`scripts/backtest_props_v2.py`, Aug 24 2026)

Opportunity × efficiency + game script, walk-forward 2023–25 (burn-in 2021–22),
snap-% role gate, graded on MAE vs v1 and vs naive trailing-10 line + lean hit-rate:

| Market | MAE gate | Lean hit vs naive (≥7.5%) | Per-season | Verdict |
|---|---|---|---|---|
| **Rush yds** | **PASS** (26.4 vs v1 26.6, naive 27.5) | **61.1%** (n=1,199) | 61/59/63% | ✅ **in production (rush-only)** |
| Receptions | FAIL (1.62 vs 1.59/1.61) | 52.9% | 53/52/54% | ❌ stays v1 |
| Rec yds | FAIL | 51.5% | 51/51/52% | ❌ stays v1 |
| Pass yds | FAIL badly (79.6 vs 69.7) | 54.0% | 53/56/53% | ❌ stays v1 |

**Decision (Aug 24): v2 rushed into production for RB rush yards only** (carry
share × team rush volume × script factor × YPC × opp; script fit 2021–25:
−0.2284 rush att/pt of team_line). Rec/pass remain v1. Caveat: lean test used
naive trailing-10 as line proxy; real books are smarter — final exam is live
CLV/hit-rate in the app. Rushing's edge mechanism: carry share + game script
is far more stable than receiving/QB variance.

## Sign-bug incident (Aug 24, 2026)

Spread adjustments were applied with flipped sign (boosted injured/rested teams).
Caught via user question about a missing pick; fixed in `10388e5` (subtract
`total_adj` on the spread axis), verified by synthetic sign tests + real DEN@KC
case. No spread pick was ever logged with the bug (all prior picks were totals).
Lesson: cold-cache cloud fetches hit code paths warm local caches don't; cloud
pushes touching imported modules need a Reboot.
