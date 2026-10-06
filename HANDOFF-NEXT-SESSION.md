# NFL‑Edge V2 Development Handoff - Next Session

## Quick Summary of Last Session's Work

**Admin Panel Enhanced** - Four tabs now operational:
1. 🎛️ Model Tuning - Added "Recent Past Tests" table showing last 5 runs
2. 📈 Tuning History - Historical config comparison
3. 🔬 Experiment Lab - Edge distribution histogram + YPP freshness check
4. 👁️ Overseer - Recommends best win% config

**Key Features Added:**
- Edge distribution histogram (visualizes why pick counts vary)
- YPP coefficient freshness check with retrain button
- Docker-CLI in admin container for restarts
- Props factors decoupled (props_pass_volume_factor, props_rush_volume_factor)

## Current Status
- **V2 containers running**: 8503 (baseline), 8504 (YPP-enabled), 8505 (admin)
- **Production untouched**: main branch isolated (ports 8501/8502)
- **Edge threshold fixed**: 2.0 everywhere for backtest consistency
- **Market weight**: 0.85 dominates blend

## Open Issues
1. **SGO API quota exhausted** - Resets Oct 1 (~3 days)
2. **Player-prop historical lines missing** - Cache has sides/totals/moneyline only
3. **YPP coefficient warning persists** - Freshness check shows <1 day age

## Recent Fixes (This Session)
1. **Fixed KeyError: 'pass_volume_factor'** - Updated all sliders to use props_ prefixed keys with fallback:
   - `config.get("props_pass_volume_factor", config.get("pass_volume_factor", 1.0))`
   - `config.get("props_rush_volume_factor", config.get("rush_volume_factor", 1.0))`
2. **Fixed TypeError: datetime timezone mismatch** - Added proper timezone handling for YPP coefficient freshness check
3. **Admin container restarted** - Fixes applied and container running on port 8505

## Immediate Next Steps
1. **Check containers**: `docker ps | grep nfl-edge-v2`
2. **Open admin panel**: http://localhost:8505
3. **Test edge histogram**: Tab 3 → "Compute Edge Distribution"
4. **Monitor SGO quota**: Check admin logs for 403/429

## When SGO Quota Resets (Oct 1)
1. Fetch team-week stats (~1,300 objects)
2. Fetch prop lines (~500 objects)  
3. Retrain YPP model with enriched data
4. Implement walk-forward backtest in Experiment Lab

## Critical Context
- Edge threshold MUST stay 2.0 (Jeff's decision)
- Market anchor = 85% weight dominates blend
- V2 completely isolated from production
- Jeff's away-mode: pre-approves autonomous builds if verification gates pass

## Key Files
- `/Users/jeff/nfl-edge-v2/admin.py` - Enhanced admin panel
- `/Users/jeff/nfl-edge-v2/scripts/walk_forward_sides.py` - Backtest engine
- `/Users/jeff/nfl-edge-v2/config/tuning_history.csv` - 21 records
- `/Users/jeff/nfl-edge-v2/data/model_fits/ypp_coefficients.json` - Fresh coefficients