# V2 Idea Log

Running capture of Jeff's V2 ideas — raw sparks, not commitments. When V2 dev
starts (Oct 1 reminder `a4cdd03bcb90`), **start by reviewing this file** alongside
`NFLVERSE-DATA-UPGRADE.md` (the spec) and `AUDIT-2026-09-10.md` (the seam map).
Say "save this V2 idea" in any session and it lands here.

| # | Date | Idea | Why / notes | Status |
|---|------|------|-------------|--------|
| 1 | 2026-09-13 | (seed) SGO as permanent lines+props backbone; single-fetcher already built (Turso `shared_cache`) | V2 inherits it free; props already ride the slate fetch | shipped in V1 ✅ |
| 2 | 2026-09-13 | (seed) Live-line freeze at the writer proved essential — V2 datasets should bake "as-of" snapshots into every pick (pre-game Elo, pre-game lines, pre-game injuries) for honest backtests | receipts integrity theme of Week 1 | principle adopted ✅ |
| 3 | 2026-09-13 | SGO is more than odds: `results` carries full player box scores (76 statIDs/player incl. targets, YAC, yards-after-contact) back to **2024 Wk1** (cutoff verified live), and `includeOpenCloseOdds` gives historical closing lines → **independent CLV receipts** + same-day prop grading, all riding the events endpoint at 1 object/event. Slate payload already carries **28 prop stat markets** (we model 4). | verified live on amateur key 2026-09-13; nflverse stays the training source (SGO gap: 2023), SGO = market + grading layer; MUST cross-check 1 week vs nflverse before trusting results (saw a partial QB line on a `finalized` game) | accepted → Phase 1 scope |

_(Jeff's ideas start at #4.)_
