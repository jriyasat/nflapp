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

## Six candidate adjustments — ALL DEAD (2026-09-24, n=1,359 REG games 2021–2025, closing lines)

| Angle | Best split | Result | Verdict |
|---|---|---|---|
| Division games (dogs cover) | Away div dogs 54.3% (n=282, z=1.43) | Combined 52.1%, −0.6% ROI | ❌ dead |
| Temperature (totals) | 33–45°F: 54.7% under (n=148, z=1.15) | ≤32°F and >75°F: nothing | ❌ dead |
| Short week / TNF | 51.0% under (n=96, z=0.20) | Home covers 49.5% | ❌ dead |
| Bye-week fade | Away bye 54.8% (n=73, z=0.82) | Home bye exactly 50.0% | ❌ dead |
| Body clock (Pacific team, 1pm ET, East) | Fade Pacific visitor: 41.5% (n=65) | Folk angle BACKWARDS (Pacific visitors cover 58.5%) | ❌ dead |
| Pace differential (fast-fast → over) | See autopsy below | Pooled 55.8% UNDER (n=342, z=2.16) — a 2021-22 fossil | ❌ dead |

Control: wind ≥15 → under 60.9% (z=+2.04) replicated inside the same script — the
negatives are real, not a broken pipeline.

### Pace-angle autopsy — what a dying edge looks like

Fast/slow = median split on rolling-4-game plays/gm (prior games only, no lookahead).
Folk theory: two fast teams → more plays → more points → over. Reality: fast and slow
teams average identical efficiency (5.34 ypp each), the NFL pace spread is ~1.4
plays/gm at the median, and the 60-minute clock keeps possessions ~constant.

The pooled "edge" was the market overpricing tempo in 2021-22 — then fixing it:

| Season | FF market line | FF actual | Market error | Under rate | ROI |
|---|---|---|---|---|---|
| 2021 | 46.8 | 45.6 | −1.1 too high | 57.9% | +10.5% |
| 2022 | 44.6 | 43.1 | −1.4 too high | 59.7% | +14.0% |
| 2023 | 43.4 | 44.2 | +0.9 too low | 54.5% | +4.1% |
| 2024 | 44.5 | 45.8 | +1.3 too low | 53.2% | +1.6% |
| 2025 | 45.7 | 46.6 | +0.9 too low | 53.1% | +1.3% |

Same direction all five years, magnitude decaying to zero: the market dropped
fast-fast lines ~3 pts in 2023 and has slightly UNDER-priced them since. Lesson:
edges rooted in market mistakes have a shelf life; edges rooted in physics
(wind) and information timing (injuries) persist. Decision (Jeff, 2026-09-24):
ship nothing; record and close.

## Dome / indoor-stadium angles (2026-09-21, n=1,359 REG games 2021–2025, closing lines)

| Angle | n | Result | z | Verdict |
|---|---|---|---|---|
| Indoor games → over (no wind) | 428 | 50.7% over (+1.48 avg vs line) | +0.29 | ❌ dead — market prices venue |
| Dome team away outdoors ATS ("dome tax") | 263 | 54.8% cover | +1.54 | ❌ dead — direction is BACKWARDS (market overprices the tax if anything) and not significant (p≈0.12, multiple angles tested) |
| Dome team away outdoors, Nov+ | 127 | 55.9% cover | +1.33 | ❌ same |
| Outdoor team away indoors → over | 289 | 52.2% over | +0.76 | ❌ dead |

Side observation: outdoor games go under 52.5% (z=−1.52) with totals perfectly calibrated
(+0.02 avg vs line) — the wind module already captures the actionable subset; a blanket
outdoor-under tweak would double-count it.

**Conclusion:** no indoor-stadium weight. Venue is fully priced; the folk "dome tax"
points the wrong way in the data. Dead, marked with numbers.

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

> ⚠️ **Public-framing note (Sept 2026):** the 61.1% lean figure is validated
> only against a naive proxy line, NOT real market prop lines (historical prop
> closers aren't freely available). Treat it as "beats a naive baseline," not
> "beats the books" — do not quote it externally. A live-line props track
> record (model vs Odds API lines, graded at close) is the planned real gate.

## Sign-bug incident (Aug 24, 2026)

Spread adjustments were applied with flipped sign (boosted injured/rested teams).
Caught via user question about a missing pick; fixed in `10388e5` (subtract
`total_adj` on the spread axis), verified by synthetic sign tests + real DEN@KC
case. No spread pick was ever logged with the bug (all prior picks were totals).
Lesson: cold-cache cloud fetches hit code paths warm local caches don't; cloud
pushes touching imported modules need a Reboot.
