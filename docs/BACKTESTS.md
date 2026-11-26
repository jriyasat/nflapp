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

## Injury-to-totals candidates — ALL DEAD (2026-09-24, 2,718 team-games 2021–2025)

Method: starter = top-usage player per team-season (QB by attempts, RB by carries,
WR by targets); out = Out/Doubtful on that week's official report; totals graded vs
closing line.

| Candidate | n | Under rate | Avg vs total | ROI | Verdict |
|---|---|---|---|---|---|
| QB1 Out | 91 | 47.3% | +2.12 | −9.8% | ❌ dead — **market now OVERCORRECTS** |
| QB1 Doubtful | 26 | 57.7% | +0.33 | +10.1% | ❌ noise (n=26) |
| WR1 Out | 60 | 41.7% | +4.27 | −20.5% | ❌ dead — backwards (overs hit) |
| RB1 Out | 81 | 59.3% | −0.71 | +13.1% | ❌ fossil (see below) |

**QB-out totals warning (do not resurrect):** season-by-season ROI on QB-out unders:
+6.1% (2021) → +13.5% (2022) → 0% (2023) → **−28.4% (2024) → −31.3% (2025)**.
The market learned to slash totals on QB news and now slashes too far — backup QBs
outperform the panic. Betting QB-out unders is a ~−30% ROI loser in the current era.

**RB1 Out fossil:** 73.9% under in 2021 (z=+2.29, +41% ROI) → 63.6% (2022) →
50.0/50.0/52.6% (2023–25). Same decay signature as the pace angle: real once,
eaten by 2023.

**Meta-lesson (3x confirmed this week):** market-visible timing angles die in ~2
seasons. Durable edges share different DNA — physics (wind), information speed
(Sleeper-layer injury news before books move), and discipline (≥2.0 vs real lines
only). Injury value on the SPREAD side likewise lives in timing, not close (see
injury-module section below).

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

## Travel distance / fatigue (Oct 5, 2026) — DEAD

Tested whether travel affects ATS/totals, 2021–2025 REG (n=1,333, real closing
lines, neutral-site excluded). Away-trip distance (haversine home→venue):
buckets 0–500/500–1k/1k–1.5k/1.5k–2k/2k+ mi → away cover 51.1/47.8/49.6/49.3/49.2%
(all |z|<0.9, no gradient). Isolated to non-division games (kills the division
confound): 47.6/49.7/49.3% — flat. Long-trip (>1.5k mi, non-division) by season:
+6.3/−6.3/+6.6/+0.1/−4.0 pts vs baseline — noise oscillation, the dead-angle
signature. Back-to-back road games: 49.2% vs 49.5% — nothing. Long-trip totals:
over% flips sign year to year. **The market prices travel completely; do not
resurrect.** The ✈️ Travel tab remains a display/teaching feature only — no
model adjustment.

> ⚠️ **Convention correction (same session):** nflverse `spread_line` is the
> AWAY team's line (positive = away underdog), verified by corr(result,
> spread_line)=+0.46 and big-spread samples (HOU +20.5 @ ARI etc.). Earlier
> ATS-side backtests in this file used the mirrored convention — e.g., the dome
> "dome team away outdoors 54.8% cover" is actually 45.2% the other side
> (|z|=1.54 either way: dead stands; fading it is not significant either).
> Totals-based tests (over/under) are unaffected. Grading in tracker.py uses
> its own pick-side convention and was independently verified — unaffected.

## Weather deep-dive: gusts + precipitation (Oct 5, 2026) — ALIVE (paper-trading)

897 outdoor games 2021–25, actual kickoff-hour weather (Open-Meteo archive) vs
closing totals. Sustained wind: 10–14 mph unders 61.1% (z=+3.77 — production
−1.2 rule VALIDATED); 15–40 mph unders 55.4% (z=+1.34 — production −2.7 rule
was calibrated on a 60.9%/n=87 claim; the 5-season rate is softer).
**Gusts are the sharper instrument:** 20–25 mph unders 60.0% (z=+2.99, n=145);
25–30 mph unders 70.6% (z=+4.24, n=85); 30+ mph unders 58.3% (z=+1.66 — market
prices headline weather). Season persistence (gust 25+): 68/69/80% under
2021–23, **flip 2024 (33%, n=21)**, 68% 2025 — 4 of 5 seasons. Rain ≥1mm:
unders 64.5% (z=+1.89, n=31 — promising, small).

**Decision (Jeff, Oct 5): PAPER TRADE.** `tracker.log_gust_papers` logs a
totals UNDER (experimental=1) for every outdoor game with forecast gusts ≥20
mph and a real books total — graded at close, excluded from the headline
record, shown on Track Record under 🧪 Paper trades. Adopt as a model
adjustment only if the live trial confirms. Caveats: backtest used ACTUAL
gusts, production bets FORECAST gusts (error shrinks edge); 2024 flip warns
of losing years; 30+ weakening says books partially catch up.

## Precipitation deep-dive (Oct 7, 2026) — rain joins the trial, snow flips sign

Same 897-game dataset (2021–25 outdoor, actual kickoff-hour weather, closing
totals; archive now stored fetch-once in data/weather_archive/). **Rain (no
snow): any measurable rain → unders ~65% (n=80, z=-2.4; light rain z=-2.45,
n=51).** Season persistence: 4/5 strongly under (2024 flat — same anomaly as
gusts). **Snow at kickoff: went OVER 73.3% (n=15, z=+1.62 — NOT significant,
but positive all 5 seasons)** — opposite of folk theory (heated fields; snow
hurts defensive footing more). Rain+gust≥20 combo: under 61.1% (n=18).

**Decision (Jeff, Oct 7): paper-trade BOTH.** Rules (priority snow > rain >
gust, one paper per game, tagged in predictions.paper_rule): `snow` → OVER,
`rain` → UNDER, `gust20` → UNDER. Track Record 🧪 section shows per-rule
records with historical samples disclosed. Forecast-vs-actual caveat applies
to all three; snow's n=15 is the weakest basis and is labeled as such.

## Division / primetime / team-health angles (Nov 4, 2026) — all DEAD

Jeff's three candidates tested on 1,359 REG games 2021–25 (correct
away-perspective spread convention; closing lines; persistence by season).
Health measured position-weighted (QB 4.0, WR/OT/DE/CB 2.0, else 1.0, K/P/LS
0.25; Out 1.0 / D 0.5 / Q 0.25) from nflverse weekly reports, all five seasons.

**Division games — DEAD.** Divisional away dogs cover 53.3% (n=287) vs 47.6%
non-divisional, but z≈+0.3 overall (pushes handled) — sub-breakeven. The 3–7
point band hits 56.9% (n=144) yet z≈+1.1; four of five seasons mildly positive
but never decisively. Folk theory ("divisional dogs") is priced.

**Primetime — DEAD.** TNF: nothing anywhere (over 49%, home 46.9%, n=96 —
the short-rest under angle is gone; season persistence 33/37/68/53/52% over =
random). SNF+MNF unders 58.0% (n=188, z=-2.85) looks alive until persistence:
50/34/28/49/49% over — a 2022–23 flavor, dead for two straight seasons.
Two-season flavors are the graveyard's most common epitaph.

**Position-weighted team health — DEAD.** Home team much MORE hurt (burden
diff ≥ +2.5): home covers 45.1% (n=315), consistent direction 2022–25
(44/42/43/44%) but z≈+0.9 for the away side — closing lines already price the
final report. Both-teams-healthy unders (59.7%, n=67): persistence
47/40/29/30/55% over = noise. The market prices WHO is out, not just that
someone is.

None met the paper-trade bar (z-screen + persistence). Graveyard now at 13.
The pattern holds: fully market-visible information (division, schedule slot,
published injury reports) does not beat closing lines.

## Divisional dogs deep-dive (Nov 4, 2026) — ONE slice survives → paper trade

Full grid over 480 division games 2021–25 (closing lines, pushes handled,
persistence by season). Headline: divisional favorites cover only 46.0%
(n=480, z=-2.79) — the market's favorite in close division games is nearly
meaningless (div dogs ≤3, normal rest win OUTRIGHT 52.6%).

**Jeff's short-rest combination is BACKWARDS — dead:** div dogs ≤3 with the
favorite on short rest cover 25.0% (n=8); both-short (TNF-ish) 33.3% (n=21).
The edge lives entirely in normal-rest games (60.7%, n=135, 5/5 seasons).

**Survivor (passes z-screen AND persistence): div dog ≤3, normal rest,
week ≥12 → dog covers 68.9% (n=61, z=+2.58, positive all 5 seasons:
90/60/61/67/73%).** Runner-up: dog-healthier slice 65.2% (n=66, z=+2.09, 5/5).
Multiple-testing caveat: ~13 slices cut, so treat z with humility; the 5/5
persistence is the real evidence.

**Decision (Jeff, Nov 4): paper trade 'divdog'** — divisional dogs ≤3 with
both teams on ≥7 days rest, weeks 12+ only, vs books consensus line,
experimental=1, graded at close, excluded from headline. ~15-20 trials/yr.
First possible trials: W12 2026. Short-rest widening is explicitly forbidden
in the rule docstring.

## Snap/role-trend momentum for rec props (Nov 25, 2026) — DEAD

Hypothesis: books build prop lines off season-long usage, so a player whose
role is *growing* (recent-3-game snap share >> season ewm) is underpriced.
Tested as (a) snap-momentum ratio multiplier on target share and (b) direct
target-share momentum blends, walk-forward, point-in-time, 7,248 role-qualified
WR/TE player-weeks 2023–25 (`~/nfl-edge-v2/scripts/backtest_snap_momentum.py`).

| Variant | rec_yds MAE | rec MAE |
|---|---|---|
| v1 / naive | 22.99 / 23.26 | 1.59 / 1.61 |
| best momentum (snap ratio, sqrt) | 23.53 | 1.61 |
| **flat 5% shrink control (no information)** | **23.13** | **1.59** |

Every momentum variant loses the MAE gate, and the zero-information shrink
control matches or beats every momentum lean hit-rate (55–59% vs 52–57%) —
the apparent "edge" was bias correction of an over-projecting base, not role
information. Snap counts are public Monday morning; books re-line props
within 1–2 weeks of a role change, so a 3-game trend is already priced.
**Decision (Jeff, Nov 25): gravestone. Do not resurrect.**

**Pipeline bugs found & fixed in the research script (not yet in
backtest_props_v2.py):** agg_snap `offense_pct` is a FRACTION (0–1) but the
original script divided by 100 (snap shares 100× too small), its snap gate
compared fractions to 0.40 (passed everyone), and the Rams snap merge failed
silently (`LA` vs `LAR`). Rush-yds v2 in production is UNAFFECTED
(carries-based); snap-share tuning rows in tuning_history.csv for rec/pass
were computed under these bugs — treat them as void.
