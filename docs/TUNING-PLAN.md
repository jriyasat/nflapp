# Hyperparameter Tuning Plan (Sides/Totals Model)

## Goal
Improve the sides/totals prediction accuracy by re‑estimating Elo parameters and spread mapping using recent data (2024‑2025) with detailed team statistics.

## Data Sources
- `nflverse/games.csv` (schedule, results, closing lines)
- `nflverse/stats_team_week_{year}.qs` (weekly team‑level stats: yards, points, turnovers, drives, plays, third‑down, red‑zone, etc.)
- Data range: 2024‑2025 (two full seasons). Stats available per team per week.

## Feature Extraction
For each team‑week:
- Compute **efficiency metrics**:
  - Yards per play (offensive, defensive)
  - Points per drive (offensive, defensive)
  - Turnover margin per game
  - Red‑zone TD rate (TDs per red‑zone trip)
  - Third‑down conversion rate
  - Sack rate (defensive sacks per opponent dropback)
- Compute **rolling averages** over last N games (N=8) for each metric.
- For each game, compute **differential** (home rolling avg – away rolling avg) for each metric.
- These differentials will be used to:
  1. **Conditionally adjust MARGIN_SD, TOTAL_SD** (higher variance for high‑volatility teams).
  2. **Optional**: small linear adjustment to margin prediction (capped at ±2 pts) based on efficiency differentials (requires coefficient tuning).

## Parameters to Tune
| Parameter | Current Value | Tuning Range |
|-----------|---------------|--------------|
| K (Elo K‑factor) | 20.0 | [15, 25, 30, 35] |
| HFA (home‑field advantage points) | 48.0 | [40, 48, 55, 60] |
| REGRESS (off‑season regression) | 1/3 | [0.25, 0.33, 0.4] |
| MARGIN_SD (std dev of margin vs expectation) | 13.3 | [12, 13.3, 14, 15] |
| TOTAL_SD (std dev of total vs expectation) | 13.5 | [12.5, 13.5, 14.5] |
| MAX_ADJ (cap on total margin adjustment) | 2.5 | [2.0, 2.5, 3.0] |
| MAX_TOTAL_ADJ | 3.5 | [3.0, 3.5, 4.0] |
| Elo spread mapping coefficients (_a, _b) | derived from 2021‑25 | re‑fit on 2024‑25 |

## Tuning Methodology
1. **Time‑series cross‑validation**: split data by season‑week; train on weeks 1‑W, test on week W+1; slide forward.
2. **Objective**: maximize log‑likelihood of covering outcomes (binary: home cover or not) given model predicted probability.
3. **Procedure**:
   - For each parameter combination:
     - Run Elo rating updates over training weeks (same algorithm as current).
     - Compute predicted spread (via spread mapping) for each test game.
     - Compute log‑likelihood (and optionally Brier score) on test set.
   - Select combination with highest average log‑likelihood across folds.
4. **Validation**: hold out one full season (2025) as final test.

## Integration of Team Stats
- **SD adjustment**: compute team‑specific volatility (variance of margin residuals). Adjust MARGIN_SD per team (shrink toward league average). Use weighted average for game‑level SD.
- **Option**: add a linear adjustment `beta * eff_diff` where `eff_diff` is a composite efficiency differential (PCA of multiple metrics). Fit `beta` via regularized regression (LASSO) on training data. Cap at ±2 pts.

## Risk Mitigation
- **No overfitting**: use out‑of‑sample validation; keep parameter grid coarse.
- **Backward compatibility**: test new constants on 2021‑2023 data (pre‑stats era) to ensure they don't degrade performance.
- **Model stability**: ensure changes don't cause wild swings in predictions (caps on adjustments remain).
- **Market‑blend principle preserved**: stats only refine the prior, never override market consensus.

## Deliverables
1. **Script** `scripts/tune_model.py` that downloads data, runs tuning, outputs new constants.
2. **Report** with:
   - New parameter values.
   - Validation metrics (log‑likelihood, ATS %, RMSE) vs current constants.
   - Backtest results on 2021‑2023.
3. **Updated `predictor.py`** (if improvement is statistically significant).
4. **Optionally** a new module `team_stats.py` for efficiency metric computation (reusable for future features).

## Timeline
- Day 1: Data pipeline (load stats_team, merge with games).
- Day 2: Feature engineering, cross‑validation harness.
- Day 3: Parameter search, analysis.
- Day 4: Report and finalize.

## Approval
Please confirm you approve this plan; I'll start implementing.