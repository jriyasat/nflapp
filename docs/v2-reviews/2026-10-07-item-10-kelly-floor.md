# V2 Audit — Addendum: Item 10 (Kelly stake floor typo)

**Found:** 2026-10-07, via external reviewer (Claude); verified by merge gate same day.
**Status at logging:** OPEN — present at `origin/v2` HEAD (`ef9a245`), untouched by the 8 fix commits.

## Bug

`predictor.py:278` (spread block):

```python
kelly = max((b * p - (1 - p)) / b,133) / 4  # quarter kelly
```

Correct version, same file, totals block (`predictor.py:314`), and both sites on main (`predictor.py:205,241`):

```python
max((b * p - (1 - p)) / b, 0) / 4
```

## Why it's real

Full-Kelly fraction for -110 odds is `(b·p − (1−p))/b` with `b = 100/110 ≈ 0.909`,
bounded above by 1 (at p = 1). `max(..., 133)` therefore **always** returns 133,
so every spread-side stake is the constant `133/4 = 33.25`.

## Blast radius

- Only consumer: `app.py:1809` game-detail "¼ Kelly stake" row → every spread game
  shows **"3325.0% of bankroll"** (and 33.25× bankroll in dollars when a bankroll is
  set) for BOTH home and away; the `k > 0` "no bet" branch is unreachable for spreads.
- Totals Kelly (line 314) is correct.
- No effect on backtests, tuning metrics, or track record — nothing else reads `kelly_*`.
- v2 dev containers only (8503/8504); main is clean.

## Origin

Introduced by `9bd97d8` ("V2: port phantom-line bug fixes from main") — a transcription
typo during the port (`, 0)` → `,133)`). Predates audit seed `f7f6c4a`, so the daily
diff-review cron will never surface it; checklist-only.

## Fix

One character class change: `,133)` → `, 0)` at `predictor.py:278`.
Gate spot-check after fix: any spread game detail view must show a real per-side
Kelly % (or "no bet"), not 3325.0%.

## Process note

Missed by the 2026-10-06 full audit; caught by external cross-review. Added to the
standing re-audit checklist as item 10.
