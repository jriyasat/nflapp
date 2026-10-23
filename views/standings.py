"""
Standings page view.
"""
import streamlit as st
import pandas as pd
import analytics as an
from shared import logo_url, LOGO_CFG

def standings_page(ctx):
    st.header("🏅 Standings")
    played = sorted(ctx.games[ctx.games["result"].notna()]["season"].unique())
    default = int(played[-1]) if len(played) else ctx.season
    yr = st.selectbox("Season", sorted(set(played + [ctx.season])), index=len(set(played + [ctx.season])) - 1)
    stats = an.team_stats(ctx.games, yr)
    t1, t2 = st.tabs(["🏅 Standings", "🎯 ATS Standings"])
    with t1:
        if yr == default and default != ctx.season:
            st.caption("2026 hasn't kicked off yet — showing last season. Flips automatically in Week 1.")
        afc, nfc = st.columns(2)
        for conf, col in (("AFC", afc), ("NFC", nfc)):
            seeds = an.playoff_seeds(stats, conf)
            with col:
                for div in [d for d in an.DIVISIONS if d.startswith(conf)]:
                    rows = []
                    for t in sorted(an.DIVISIONS[div], key=lambda x: an._winpct(stats[x]), reverse=True):
                        s = stats[t]
                        rows.append({"Team": t, "Logo": logo_url(t), "W": s["w"], "L": s["l"],
                                     "T": s["t"], "PF": s["pf"], "PA": s["pa"],
                                     "Seed": str(seeds[t]) if t in seeds else ""})
                    st.markdown(f"**{div}**")
                    st.dataframe(pd.DataFrame(rows), column_config=LOGO_CFG,
                                 hide_index=True, width="stretch")
        st.caption("Seeds 1-4 = division leaders • 5-7 = wildcards")
    with t2:
        rows = []
        for t, s in stats.items():
            n = s["ats_w"] + s["ats_l"]
            rows.append({"Team": t, "Logo": logo_url(t),
                         "ATS": f"{s['ats_w']}-{s['ats_l']}-{s['ats_p']}",
                         "Cover %": round(100 * s["ats_w"] / n, 1) if n else 0.0})
        rows.sort(key=lambda r: -r["Cover %"])
        st.dataframe(pd.DataFrame(rows), column_config=LOGO_CFG, hide_index=True, width="stretch")
        st.caption("Against-the-spread record vs closing lines — the standings that pay.")