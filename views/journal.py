"""
Journal page view.
"""
import streamlit as st
import pandas as pd
import journal
import db
from shared import logo_url, LOGO_CFG

def journal_page(ctx):
    st.header("📒 Bet Journal + CLV Tracker")
    st.caption(f"Private journal of **{ctx.NAME}** — only you can see this.")
    bets = journal.settle(journal.load_bets(ctx.USER), ctx.games, ctx.USER)
    s = journal.summary(bets)
    parlays = db.settle_parlays(ctx.games, ctx.USER)
    settled_parlays = [p for p in parlays if p["status"] in ("won", "lost", "push")]
    par_profit = sum(float(p["profit"] or 0) for p in settled_parlays)
    par_staked = sum(float(p["stake"] or 0) for p in settled_parlays)
    if par_staked:
        s["profit"] = s.get("profit", 0) + par_profit
        s["staked"] = s.get("staked", 0) + par_staked
        s["roi"] = 100 * s["profit"] / s["staked"] if s["staked"] else 0
    c = st.columns(5)
    c[0].metric("Record", s.get("record", "0-0-0"))
    c[1].metric("Profit", f"{s.get('profit', 0):+.2f}u" if s.get("staked") else "-")
    c[2].metric("ROI", f"{s.get('roi', 0):+.1f}%" if s.get("staked") else "-")
    c[3].metric("Avg CLV", f"{s.get('avg_clv', 0):+.2f}" if s.get("n_clv") else "-")
    c[4].metric("Beat the close", f"{s.get('beat_close_pct', 0):.0f}% ({s.get('n_clv', 0)})"
                if s.get("n_clv") else "-")
    me_u = db.get_user_settings(ctx.USER) or {}
    if me_u.get("bankroll"):
        br, un = me_u["bankroll"], me_u.get("unit") or 1.0
        pnl = s.get("profit", 0) * un
        st.metric("💰 Bankroll balance", f"${br + pnl:,.0f}",
                  f"started ${br:,.0f} · P/L ${pnl:+,.0f}")
    with st.expander("💰 Bankroll settings"):
        b1, b2 = st.columns(2)
        br_in = b1.number_input("Bankroll ($)", min_value=0.0,
                                value=float(me_u.get("bankroll") or 0), step=50.0)
        un_in = b2.number_input("Unit size ($)", min_value=0.0,
                                value=float(me_u.get("unit") or 0), step=5.0,
                                help="Journal stakes are in units — this converts them to $.")
        if st.button("Save bankroll"):
            db.update_bankroll(ctx.USER, br_in, un_in)
            db.get_user_settings.clear()
            st.success("Bankroll saved ✅")
            st.rerun()
    st.caption("CLV: positive = you got a better number than the close. Beating the close "
               ">53% of the time over 100+ bets is the strongest known signal of a real edge.")

    # 🎟️ bet slip review (legs added from the 🎟️ Slip tab on any game)
    slip = st.session_state.setdefault("slip", [])
    if slip:
        with st.expander(f"🎟️ Bet slip — {len(slip)} leg(s)", expanded=True):
            for i, leg in enumerate(slip):
                lc1, lc2 = st.columns([11, 1])
                txt = (f"**{leg['game']}** · {leg['bet_type']} **{leg['selection']}**"
                       + (f" {leg['line']:+.1f}" if leg.get("line") is not None else "")
                       + f" ({leg['odds']:+d})")
                lc1.markdown(txt)
                if lc2.button("✕", key=f"slip_rm_{i}"):
                    slip.pop(i)
                    st.rerun()
            dec = 1.0
            for leg in slip:
                dec *= db._american_to_dec(leg["odds"])
            auto_am = (round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))) \
                if len(slip) > 1 else slip[0]["odds"]
            comb = st.number_input("Combined odds (auto — edit for boosts/SGP pricing)",
                                   value=auto_am, step=5, key=f"slip_comb_{len(slip)}")
            sc1, sc2 = st.columns(2)
            stake = sc1.number_input("Stake (units)", value=1.0, step=0.5, min_value=0.1,
                                     key="slip_stake")
            book = sc2.text_input("Book", key="slip_book")
            b1, b2 = st.columns(2)
            if b1.button("💾 Save parlay", disabled=len(slip) < 2, type="primary"):
                db.save_parlay(ctx.USER, slip, float(comb), float(stake), book, "parlay")
                st.session_state["slip"] = []
                st.success("Parlay saved — legs grade automatically as games finish.")
                st.rerun()
            if b2.button("💾 Save as round robin (manual result)", disabled=len(slip) < 3,
                         help="One ticket, total stake, you enter the result when it settles"):
                db.save_parlay(ctx.USER, slip, None, float(stake), book, "round_robin")
                st.session_state["slip"] = []
                st.success("Round robin saved — enter the result below when it settles.")
                st.rerun()

    with st.expander("➕ Log a bet", expanded=not len(bets)):
        gs = ctx.games[(ctx.games["season"] == ctx.season) & (ctx.games["game_type"] == "REG")].sort_values(["week", "gameday"])
        labels = [f"{r['away_team']} @ {r['home_team']} (W{int(r['week'])})" for _, r in gs.iterrows()]
        pick = st.selectbox("Game", labels)
        glabel = pick.split(" (W")[0]
        away_t, home_t = glabel.split(" @ ")
        btype = st.selectbox("Bet type", ["spread", "ml", "total"])
        if btype == "total":
            sel = st.selectbox("Side", ["over", "under"])
            default_line = 45.5
        elif btype == "spread":
            sel = st.selectbox("Team", [away_t, home_t])
            default_line = -3.0
        else:
            sel = st.selectbox("Team", [away_t, home_t])
            default_line = 0.0
        c1, c2, c3 = st.columns(3)
        line = c1.number_input("Line (team's spread / total)", value=default_line, step=0.5,
                               disabled=(btype == "ml"))
        odds = c2.number_input("Odds (American)", value=-110, step=5)
        stake = c3.number_input("Stake (units)", value=1.0, step=0.5, min_value=0.1)
        book = st.text_input("Book", "")
        if st.button("💾 Save bet"):
            journal.save_bet({
                "date": pd.Timestamp.now().strftime("%Y-%m-%d"), "season": ctx.season,
                "week": int(pick.split("(W")[1].rstrip(")")), "game": glabel,
                "bet_type": btype, "selection": sel, "line": line, "odds": odds,
                "stake": stake, "book": book}, ctx.USER)
            st.success("Saved. CLV fills in at kickoff; grade lands after the final.")
            st.rerun()

    # ---------------- Logged (pending) vs Settled ----------------
    GR = {"won": "✅", "lost": "❌", "push": "➖", "pending": "⏳"}
    pend_s = bets[bets["status"] == "pending"] if len(bets) else bets.iloc[0:0]
    done_s = bets[bets["status"] != "pending"] if len(bets) else bets.iloc[0:0]
    pend_p = [p for p in parlays if p["status"] == "pending"]
    done_p = [p for p in parlays if p["status"] != "pending"]

    def _to_win(odds, stake):
        return f"{float(stake) * (db._american_to_dec(float(odds)) - 1):+.2f}u"

    def _singles_table(df, show_profit):
        show = df.copy()
        show["clv"] = show["clv"].apply(lambda v: f"{float(v):+.2f}" if str(v) not in ("", "nan") else "…")
        show.insert(0, "Logo", show["selection"].map(logo_url))
        show["To Win"] = show.apply(lambda r: _to_win(r["odds"], r["stake"]), axis=1)
        cols = ["id", "Logo", "selection", "date", "game", "bet_type", "line", "odds",
                "stake", "To Win", "book", "status"]
        if show_profit:
            cols += ["profit", "clv"]
        st.dataframe(show[cols], column_config=LOGO_CFG, hide_index=True, width="stretch")

    def _parlay_expander(pl):
        odds_txt = f"{int(pl['combined_odds']):+d}" if pl["combined_odds"] is not None else "manual"
        to_win = (f"To Win {_to_win(pl['combined_odds'], pl['stake'])}"
                  if pl["combined_odds"] is not None else "To Win: manual")
        profit_txt = (f" · {pl['profit']:+.2f}u"
                      if pl["status"] != "pending" and pl["profit"] is not None else "")
        with st.expander(f"{GR.get(pl['status'], '⏳')} {pl['kind'].replace('_', ' ').title()} · "
                         f"{len(pl['legs'])} legs · {odds_txt} · {pl['stake']:g}u · "
                         f"{to_win}{profit_txt} — {pl['created_at']}"):
            lrows = [{
                "Pick": logo_url(leg["selection"]),
                "Game": leg["game"], "Type": leg["bet_type"], "Sel": leg["selection"],
                "Line": f"{leg['line']:+.1f}" if leg.get("line") is not None else "-",
                "Closing": f"{leg['closing_line']:+.1f}" if leg.get("closing_line") is not None else "-",
                "Result": GR.get(leg["grade"], "⏳"),
            } for leg in pl["legs"]]
            st.dataframe(pd.DataFrame(lrows),
                         column_config={"Pick": st.column_config.ImageColumn("Pick", width="small")},
                         hide_index=True, width="stretch")
            if pl["kind"] == "round_robin" and pl["status"] == "pending":
                r1, r2 = st.columns(2)
                res = r1.selectbox("Settle round robin", ["won", "lost"], key=f"rr_res_{pl['id']}")
                payout = r2.number_input("Profit (units, excl. stake)", value=0.0, step=0.5,
                                         key=f"rr_pay_{pl['id']}", disabled=(res != "won"))
                if st.button("💾 Settle", key=f"rr_go_{pl['id']}"):
                    db.settle_rr(pl["id"], res, payout)
                    st.rerun()
            if pl["status"] == "pending":
                if st.button("🗑️ Delete ticket", key=f"par_del_{pl['id']}"):
                    db.delete_parlay(pl["id"])
                    st.rerun()

    if len(pend_s) or pend_p:
        st.subheader("📋 Logged")
    if len(pend_s):
        st.markdown("**Singles**")
        _singles_table(pend_s.sort_values(["week", "date"], ascending=False), show_profit=False)
        del_id = st.selectbox("Delete a pending bet (by id)", [""] + pend_s["id"].tolist())
        if del_id and st.button("🗑️ Delete"):
            journal.delete_bet(del_id, ctx.USER)
            st.rerun()
    if pend_p:
        st.markdown("**🎟️ Parlays & Round Robins**")
        for pl in pend_p:
            _parlay_expander(pl)

    if len(done_s) or done_p:
        st.subheader("✅ Settled")
    if len(done_s):
        st.markdown("**Singles**")
        _singles_table(done_s.sort_values(["week", "date"], ascending=False), show_profit=True)
    if done_p:
        st.markdown("**🎟️ Parlays & Round Robins**")
        for pl in done_p:
            _parlay_expander(pl)