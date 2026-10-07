# Grading‑Logic Safeguards

These safeguards were added after the **sign‑flip bug** (2026‑10‑06) corrupted all tuning results. They ensure that core grading logic is verified before any commit or merge.

## 1. Git pre‑commit hook

A hook installed at `./git/hooks/pre‑commit` (symlink to `scripts/check_grading_patterns.py`) runs before each commit.

**What it checks:**
- `market_spread = -float(r["spread_line"])` followed by `home_cov = result - market_spread` (sign‑flip bug)
- `market.get('spread')` when predictor only emits `home_spread`
- `clv = sub["edge"].mean()` (mis‑labeled CLV variable)

**Effect:** Commits containing these anti‑patterns are **blocked**.

**To run manually:**
```bash
python scripts/check_grading_patterns.py
```

## 2. Unit‑test suite

`tests/test_grading.py` validates spread‑line conventions and grading arithmetic.

| Test | Purpose |
|------|---------|
| `test_spread_line_convention` | Verifies nflverse `spread_line` interpretation |
| `test_sign_flip_detection` | Ensures the buggy formula produces different home_cov |
| `test_market_margin_consistency` | Checks `market_margin = -market_spread` |
| `test_historical_games` | Grades a small set of manually‑verified historical games |
| `test_verification_sample` | Grades 10 curated historical games from `tests/data/verification_sample_10_games.csv` |

**To run:**
```bash
python -m pytest tests/test_grading.py -v
```

## 3. CI workflow

GitHub Actions runs on every push to `v2` or `main` (`.github/workflows/grading-ci.yml`).

**Steps:**
1. Installs Python, pandas, numpy, pytest
2. Runs the grading unit‑test suite
3. Runs the pattern checker

**Effect:** Any regression is caught **before merging**.

## 4. Spread‑line conventions document

`docs/SPREAD_CONVENTIONS.md` defines the spread‑line perspective, internal variables, and the correct grading formula.

**Key conventions:**
- `spread_line` = away perspective (positive = away underdog)
- Home covers when `result > spread_line`
- `market_spread` = home perspective (`-spread_line`)
- `market_margin` = `-market_spread`
- `home_cov` = `result - market_margin`

## 5. Verification sample

`tests/data/verification_sample_10_games.csv` – 10 historical games with pre‑computed `home_cov`. Any grading bug will cause this sample to fail.

**Usage:** The sample is automatically verified by `test_verification_sample`.

---

## Workflow for grading‑logic changes

Before modifying any grading‑related code (`walk_forward_*.py`, `predictor.py`, `data.py`, etc.):

1. **Read** the conventions document.
2. **Run** the unit‑test suite.
3. **Update** the verification sample if necessary (add new test cases).
4. **Commit** – the pre‑commit hook will block dangerous patterns.
5. **Push** – CI will run the tests again.

## Why this prevents another sign‑flip bug

- The buggy pattern is **detected automatically**.
- The grading formula is **unit‑tested** with real historical games.
- The conventions are **documented**.
- Changes are **validated in CI** before merging.

## Adding new safeguards

If you discover another class of grading bug:

1. Add a corresponding test case to `tests/test_grading.py`.
2. Update the pattern checker (`scripts/check_grading_patterns.py`).
3. Consider adding more historical games to the verification sample.
4. Update this document.

---

*Last updated: 2026‑10‑06 after audit fixes.*