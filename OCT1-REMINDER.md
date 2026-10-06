# Oct 1 2026 – SGO Quota Reset & V2 Development Start

## 🚀 **Immediate Actions (Oct 1 morning)**
1. **SGO quota resets** – fetch team‑week stats (~1,300 objects) and prop lines (~500 objects)
2. **Retrain YPP model** with fresh data (coefficients currently from 2026‑09‑27)
3. **Implement current‑season backtest** in Experiment Lab (tab 3):
   - Filter games to `season == 2026`
   - Use nflverse fallback lines (no SGO quota needed)
   - Show win%, ROI, picks with small‑sample caveat
4. **Begin V2 Phase 0** (per `docs/V2‑PLAN.md`):
   - Build `nfl‑edge:v2` Docker image on port 8503
   - Add pyarrow dependency
   - Implement `_get_df()` loader primitive in `nflverse_extra.py`

## 📋 **Pre‑Oct‑1 Prep Checklist**
✅ **Admin panel** – Overseer enhanced with AI analysis  
✅ **System status** – SGO quota countdown sidebar  
✅ **Edge histogram** – protected with quota warning  
🔲 **Data Health section** (Settings tab) – Phase 0 S4 deliverable  
🔲 **Review V2‑PLAN.md** – confirm tasks for Oct 1  
🔲 **Test Docker build** – ensure `nfl‑edge:v2` builds cleanly  
🔲 **Backup tuning history** – `config/tuning_history.csv`  
🔲 **Document Overseer workflow** – for YouTube explainer  
🔲 **Set up monitoring** – admin panel alerts for quota usage  

## 🧠 **Overseer‑Guided Tuning (Post‑Oct 1)**
1. **Diversify constant weights** – test `ryoe_multiplier`, `separation_multiplier`, etc. across full ranges
2. **Run 5–10 targeted tests** using Overseer recommendations
3. **Collect 50+ varied configurations** to fuel advanced ML insights

## ⚠️ **Known Issues**
- YPP coefficient freshness warning may be false positive (check `get_system_status()` logic)
- Player‑prop historical lines missing from cache (SGO fetch needed)
- Admin panel LSP warnings about `use_container_width` (Streamlit deprecation)

---
*This reminder created 2026‑09‑28. Last admin‑panel enhancement: Overseer AI analysis.*