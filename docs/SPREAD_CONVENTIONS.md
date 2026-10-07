# Spread‑Line Conventions

This document defines the spread‑line conventions used throughout the NFL Edge codebase. Misunderstanding these conventions caused the **sign‑flip bug** that invalidated all tuning results before the 2026‑10‑06 audit.

## 1. nflverse `spread_line` (away‑perspective)

- **Source**: `nflverse` game records (`schedule.csv`).
- **Definition**: `spread_line` is the **away team’s point spread**.
- **Sign**: Positive = away team is the underdog, receiving points.
- **Example**: `spread_line = 3.5` means the away team is getting **+3.5** points; the home team is favored by **‑3.5**.

### Cover condition
Home covers when:

```
home_score - away_score > spread_line
```

i.e., the **actual margin** (home – away) must exceed the spread line.

Equivalently, the away team covers when:

```
home_score - away_score < spread_line
```

(Note: a push occurs when `home_score - away_score == spread_line`.)

## 2. Internal spread variables

| Variable | Perspective | Meaning | Formula |
|----------|-------------|---------|---------|
| `spread_line` | away | nflverse raw column | `schedule.spread_line` |
| `home_spread` | home | spread from home’s viewpoint | `home_spread = -spread_line` |
| `market_spread` | home | spread used in model blending (home perspective) | `market_spread = -spread_line` (when derived from nflverse) |
| `market_margin` | home | margin the home team must exceed to cover | `market_margin = -market_spread` |
| `result` | home | actual final margin (home – away) | `result = home_score - away_score` |

### Example
- `spread_line = 3.0` (away +3)
- `home_spread = -3.0` (home –3)
- `market_spread = -3.0`
- `market_margin = 3.0`
- If `result = 10.0`, home covers by `10.0 – 3.0 = 7.0`.

## 3. Grading formula

**Correct grading** (used after the 2026‑10‑06 fix):

```python
market_spread = -float(r["spread_line"])          # home perspective
market_margin = -market_spread                    # positive = home must win by X
home_cov = r["result"] - market_margin            # >0 = home covers
```

**Buggy grading** (sign‑flip):

```python
market_spread = -float(r["spread_line"])          # home perspective
home_cov = r["result"] - market_spread            # WRONG: uses spread, not margin
```

The bug evaluates `home_cov = result - (-spread_line) = result + spread_line`, which grades the opposite side.

## 4. Predictor output

The `predictor.consensus()` function returns a `market` dictionary with:

- `home_spread`: home‑perspective spread (negative when home favored)
- `home_total`: total points (over/under)
- `away_spread`: away‑perspective spread (positive when away underdog)
- `away_total`: same total

**Do not** use `market.get('spread')` – it does not exist. Use `market.get('home_spread')`.

## 5. Walk‑forward backtest convention

All walk‑forward scripts (`walk_forward_sides_no_ypp.py`, `walk_forward_sides.py`, etc.) now follow this pattern:

```python
# Convert nflverse spread_line to home perspective
if pd.notna(r.get("spread_line")):
    market_spread = -float(r["spread_line"])
    market_src = "nflverse"
else:
    market_spread = fallback_spread
    market_src = "none"

market_margin = -market_spread
home_cov = r["result"] - market_margin
```

## 6. Testing & verification

A unit‑test suite (`tests/test_grading.py`) verifies:

1. The spread‑line convention for a set of historical games.
2. That the sign‑flip bug would produce a different home‑cover value.
3. That `market_margin = -market_spread` holds.

Run the tests with:

```bash
cd /path/to/nfl-edge-v2
python -m pytest tests/test_grading.py -v
```

## 7. Pre‑commit hook

The script `scripts/check_grading_patterns.py` scans for anti‑patterns:

- `market_spread = -float(r["spread_line"])` followed by `home_cov = result - market_spread`
- `market.get('spread')`
- `clv = sub["edge"].mean()` (mis‑labeled CLV)

Run manually before committing:

```bash
python scripts/check_grading_patterns.py
```

## 8. Historical note

The sign‑flip bug existed in **every walk‑forward backtest script** (`walk_forward_sides_no_ypp.py`, `walk_forward_sides.py`, `walk_forward_debug.py`, `ypp_enabled_backtest.py`, `quick_test.py`, `debug_edges.py`, `config_backtest.py`) and corrupted all tuning numbers (win %, ROI, “CLV”). The bug was fixed in commit `7544257` (2026‑10‑06).