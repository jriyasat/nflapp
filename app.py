"""NFL Edge Finder -- Streamlit app.

Run:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

import analytics as an
import data as dl
import journal
import predictor as pr
import props_model as pm
import sgp
import weather as wx

st.set_page_config(page_title="NFL Edge Finder", page_icon="🏈", layout="wide")
st.title("🏈 NFL Edge Finder")
st.caption("Predictor • Lines • H2H history (5y) • Recent form (ATS/O-U) • Situational spots • Injuries")

games = dl.load_games()

@st.cache_resource
def get_elo():
    return pr.Elo(games)

elo = get_elo()

@st.cache_data(ttl=12 * 3600)
def get_player_stats():
    ps = dl.load_player_stats()
    return ps, pm.defense_multipliers(ps)

try:
    player_stats, def_mults = get_player_stats()
except Exception:
    player_stats, def_mults = None, None

ABBR_TO_NAME = {v: k for k, v in dl.TEAM_NAME_TO_ABBR.items()}

@st.cache_data(ttl=3600)
def get_projections(team, opp, inj_items):
    """Memoized per-matchup projections (the heaviest per-rerun compute).
    inj_items: tuple(sorted(injuries.items())) for hashability."""
    return pm.project_game(player_stats, def_mults, team, opp, injuries=dict(inj_items))

def team_inj_map(team):
    m = {r["name"]: r["status"]
         for r in (nv_injuries.get(team) or {}).get("rows", []) if r.get("status")}
    return tuple(sorted(m.items()))

# ---------------- sidebar ----------------
st.sidebar.header("Controls")
season, week = dl.current_season_week(games)
season = st.sidebar.number_input("Season", 2020, 2030, season)
weeks = sorted(games[(games["season"] == season) & (games["game_type"] == "REG")]["week"].unique())
week = st.sidebar.selectbox("Week", weeks, index=weeks.index(week) if week in weeks else 0)
api_key = st.sidebar.text_input("The Odds API key (optional)", type="password",
                                help="Free key at the-odds-api.com -> multi-book lines + line shopping")
if st.sidebar.button("🔄 Refresh live data"):
    import glob
    import os
    for f in glob.glob(os.path.join(dl.CACHE, "espn_*.json")) + glob.glob(os.path.join(dl.CACHE, "odds_api.json")):
        os.remove(f)
    st.rerun()

week_games = games[(games["season"] == season) & (games["game_type"] == "REG") &
                   (games["week"] == week)].sort_values(["gameday", "gametime"])
if week_games.empty:
    st.warning("No games found for that week.")
    st.stop()

# ---------------- live data ----------------
espn_odds = {}
try:
    espn_odds = dl.espn_week_odds(season, week)
except Exception as e:
    st.sidebar.warning(f"ESPN odds unavailable: {e}")

books_by_abbr = {}
odds_err = None
if api_key:
    try:
        raw = dl.odds_api_lines(api_key)
        for (away_name, home_name), books in raw.items():
            key = (dl.TEAM_NAME_TO_ABBR.get(away_name), dl.TEAM_NAME_TO_ABBR.get(home_name))
            if all(key):
                books_by_abbr[key] = books
    except Exception as e:
        odds_err = str(e)
if api_key and odds_err:
    st.sidebar.error(f"Odds API: {odds_err}")
elif api_key and not books_by_abbr:
    st.sidebar.info("Odds API: no NFL markets on the board right now.")

injuries = {}
injuries_err = None
try:
    injuries = dl.espn_injuries()
except Exception as e:
    injuries_err = str(e)

try:
    nv_injuries, nv_status = dl.nflverse_injuries()
except Exception:
    nv_injuries, nv_status = {}, "unavailable"

st.sidebar.markdown(f"**{len(week_games)} games** loaded • injuries for {len(injuries)} teams")
page = st.sidebar.radio("View", ["Games", "📒 Bet Journal"])

# ---------------- bet journal page ----------------
def journal_page():
    st.header("📒 Bet Journal + CLV Tracker")
    bets = journal.settle(journal.load_bets(), games)
    s = journal.summary(bets)
    c = st.columns(5)
    c[0].metric("Record", s.get("record", "0-0-0"))
    c[1].metric("Profit", f"{s.get('profit', 0):+.2f}u" if s.get("staked") else "-")
    c[2].metric("ROI", f"{s.get('roi', 0):+.1f}%" if s.get("staked") else "-")
    c[3].metric("Avg CLV", f"{s.get('avg_clv', 0):+.2f}" if s.get("n_clv") else "-")
    c[4].metric("Beat the close", f"{s.get('beat_close_pct', 0):.0f}% ({s.get('n_clv', 0)})"
                if s.get("n_clv") else "-")
    st.caption("CLV: positive = you got a better number than the close. Beating the close "
               ">53% of the time over 100+ bets is the strongest known signal of a real edge.")

    with st.expander("➕ Log a bet", expanded=not len(bets)):
        gs = games[(games["season"] == season) & (games["game_type"] == "REG")].sort_values(["week", "gameday"])
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
                "date": pd.Timestamp.now().strftime("%Y-%m-%d"), "season": season,
                "week": int(pick.split("(W")[1].rstrip(")")), "game": glabel,
                "bet_type": btype, "selection": sel, "line": line, "odds": odds,
                "stake": stake, "book": book})
            st.success("Saved. CLV fills in at kickoff; grade lands after the final.")
            st.rerun()

    if len(bets):
        show = bets.copy()
        show["clv"] = show["clv"].apply(lambda v: f"{float(v):+.2f}" if str(v) not in ("", "nan") else "…")
        st.dataframe(show[["date", "game", "bet_type", "selection", "line", "odds",
                           "stake", "book", "status", "profit", "clv"]].iloc[::-1],
                     hide_index=True, width="stretch")
        del_id = st.selectbox("Delete a bet (by id)", [""] + bets["id"].tolist())
        if del_id and st.button("🗑️ Delete"):
            journal.delete_bet(del_id)
            st.rerun()

if page == "📒 Bet Journal":
    journal_page()
    st.stop()

# ---------------- render helpers ----------------
def fmt_ml(v):
    return f"{v:+d}" if isinstance(v, (int, float)) else "-"

def lines_block(away, home, espn_o, books):
    rows = []
    if books:
        for bk, e in books.items():
            rows.append({
                "Book": e.get("title", bk),
                "Spread": f"{home} {e['home_spread']:+.1f} ({fmt_ml(e.get('home_spread_price'))})"
                          if e.get("home_spread") is not None else "-",
                "Total": f"{e['total']:.1f} (O {fmt_ml(e.get('over_price'))})"
                         if e.get("total") is not None else "-",
                "ML": f"{away} {fmt_ml(e.get('away_ml'))} / {home} {fmt_ml(e.get('home_ml'))}",
            })
    elif espn_o:
        rows.append({
            "Book": espn_o.get("provider", "ESPN") + " (single book)",
            "Spread": f"{espn_o.get('details', '-')}",
            "Total": f"{espn_o['over_under']:.1f}" if espn_o.get("over_under") else "-",
            "ML": f"{away} {fmt_ml(espn_o.get('away_ml'))} / {home} {fmt_ml(espn_o.get('home_ml'))}",
        })
    if rows:
        st.table(pd.DataFrame(rows))
    else:
        st.info("No live lines posted yet for this game.")
    if books:
        best = an.line_shopping(books)
        if best.get("books_disagree"):
            st.success("⚡ Books disagree on the number -- line shopping value available")
        tags = []
        if best.get("home_spread"):
            b = best["home_spread"]; tags.append(f"Best {home} spread: {b['point']:+.1f} @ {b['book']}")
        if best.get("away_spread"):
            b = best["away_spread"]; tags.append(f"Best {away} spread: {b['point']:+.1f} @ {b['book']}")
        if best.get("over"):
            tags.append(f"Best Over: {best['over']['point']:.1f} @ {best['over']['book']}")
        if best.get("under"):
            tags.append(f"Best Under: {best['under']['point']:.1f} @ {best['under']['book']}")
        if tags:
            st.markdown(" • ".join(f"**{t}**" for t in tags))

def form_df(team):
    rows = an.last_n(games, team, 3)
    if not rows:
        return None
    out = pd.DataFrame([{
        "Date": r["date"], "Game": f"{r['loc']} {r['opp']}", "Score": r["score"],
        "W/L": r["result"], "Line": f"{r['line']:+.1f}" if pd.notna(r["line"]) else "-",
        "ATS": r["ats"], "Total": f"{r['total_line']:.1f}" if pd.notna(r["total_line"]) else "-",
        "O/U": r["ou"],
    } for r in rows])
    return out

def injuries_block(away, home):
    any_data = False
    for team in (away, home):
        nv = nv_injuries.get(team)
        if nv and nv["rows"]:
            any_data = True
            st.markdown(f"**{team}** — official NFL report ({nv['label']})")
            st.dataframe(pd.DataFrame([{
                "Player": r["name"], "Pos": r["position"], "Status": r["status"],
                "Injury": r["detail"], "Practice": r["practice"],
            } for r in nv["rows"]]), hide_index=True, width="stretch")
        else:
            rows = injuries.get(team, [])
            if rows:
                any_data = True
                st.markdown(f"**{team}** — via ESPN")
                st.dataframe(pd.DataFrame([{
                    "Player": r["name"], "Pos": r["position"],
                    "Status": r["status"], "Injury": r["detail"],
                } for r in rows]), hide_index=True, width="stretch")
    if not any_data:
        if injuries_err and nv_status != "ok":
            st.warning("Injury feeds temporarily unavailable — hit 🔄 Refresh in a few minutes.")
        else:
            st.info("No injuries listed (official report publishes Wednesday of game week).")

# ---------------- predictor UI ----------------
def fmt_spread(sp, home, away):
    """home-perspective spread (neg=home fav) -> 'SEA -3.1'"""
    return f"{home} {sp:.1f}" if sp < 0 else f"{away} {-sp:.1f}"

def predictor_tab(g, away, home):
    key = (away, home)
    wind_mph = None
    if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
        wind_mph, _ = wx.wind_for_game(g)
    pred = pr.predict_game(g, elo, books_by_abbr.get(key), espn_odds.get(key), nv_injuries,
                           wind_mph=wind_mph)
    if pred["mode"] == "elo-only":
        st.info("No market lines posted yet — showing Elo-only estimate (edges compute once books post).")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🤖 Model line", fmt_spread(pred["model_spread"], home, away))
    if pred.get("market_spread") is not None:
        src = f"{pred['n_books']} book(s)" if pred["n_books"] else "nflverse current line"
        c2.metric("📚 Market", fmt_spread(pred["market_spread"], home, away), src)
        edge = pred["edge_pts"]
        side = home if edge > 0 else away
        c3.metric("⚡ Edge", f"{abs(edge):.1f} pts on {side}",
                  "value" if abs(edge) >= 1.5 else "within noise",
                  delta_color="normal" if abs(edge) >= 1.5 else "off")
        if pred.get("model_total") is not None:
            gap = pred["model_total"] - pred["market_total"]
            lean = "UNDER" if gap < 0 else "OVER"
            c4.metric("🎚️ Model total", f"{pred['model_total']:.1f}",
                      f"mkt {pred['market_total']:.1f} → {lean} {abs(gap):.1f}")
        elif pred.get("market_total"):
            c4.metric("Total (market)", f"{pred['market_total']:.1f}")
        p = pred["p_home_cover"]
        st.markdown(f"**Cover probability:** {home} {p*100:.0f}% / {away} {(1-p)*100:.0f}%")
        st.progress(min(max(p, 0.0), 1.0))
        rows = []
        for side, team in (("home", home), ("away", away)):
            ev = pred.get(f"ev_{side}")
            if ev is not None:
                rows.append({"Side": team, "EV @-110": f"{ev*100:+.1f}%",
                             "¼ Kelly stake": f"{pred[f'kelly_{side}']*100:.1f}% of bankroll"
                             if pred[f"kelly_{side}"] > 0 else "no bet"})
        for side in ("over", "under"):
            ev = pred.get(f"ev_{side}")
            if ev is not None:
                rows.append({"Side": side.upper(), "EV @-110": f"{ev*100:+.1f}%",
                             "¼ Kelly stake": f"{pred[f'kelly_{side}']*100:.1f}% of bankroll"
                             if pred[f"kelly_{side}"] > 0 else "no bet"})
        st.table(pd.DataFrame(rows))
        if pred.get("total_adjustments"):
            st.markdown("**Total adjustments:** " + " • ".join(
                f"{n} {v:+.1f}" for n, v in pred["total_adjustments"]))
    else:
        c2.metric("Elo win prob", f"{home} {pred['p_elo']*100:.0f}%")
    if pred["adjustments"]:
        st.markdown("**Adjustments applied:** " + " • ".join(
            f"{a['module']} {a['team']} {a['pts']:+.1f}" for a in pred["adjustments"]))
    for name, info in pred["angles"]:
        st.success(f"📐 **Angle:** {info['note']} — backtest: {info['record']} (2021-25)")
    st.caption("Base = de-vigged market consensus (85%) + Elo prior (15%) + backtested adjustments. "
               "EV assumes -110; Kelly shown at ¼ fraction. Historical ≠ future — size accordingly.")

# ---------------- props UI ----------------
PROJ_COLS = [("proj_pass", "Pass Yds"), ("proj_rush", "Rush Yds"),
             ("proj_rec_yds", "Rec Yds"), ("proj_rec", "Receptions")]

def props_tab(g, away, home):
    if player_stats is None:
        st.warning("Player stats feed unavailable right now.")
        return
    lines = st.session_state.get(f"props_{away}_{home}", {})
    for team, opp in ((away, home), (home, away)):
        st.markdown(f"**{team}** (vs {opp})")
        res = get_projections(team, opp, team_inj_map(team))
        for w in res["warnings"]:
            st.error(w)
        if res["benched"]:
            st.warning("🚑 Benched: " + ", ".join(f"{b['player']} ({b['status']})" for b in res["benched"])
                       + " — volume redistributed")
        projs = pm.edges_vs_lines(res["players"], lines)
        rows = []
        for p in projs:
            name = p["player"] + (" ⚠️" if p.get("flag") else "")
            if p.get("boost"):
                name += f" ↑{p['boost']:.2f}x"
            row = {"Player": name, "Pos": p["pos"], "G": p["games"]}
            for col, label in PROJ_COLS:
                v = p.get(col)
                if v is None:
                    continue
                e = p.get("edges", {}).get(col)
                if e:
                    mark = "🟢" if abs(e["edge_pct"]) >= 8 else "⚪"
                    row[label] = (f"{v:.0f} | {e['line']} {mark} "
                                  f"{e['lean']} {abs(e['edge']):.0f} ({e['edge_pct']:+.0f}%)")
                else:
                    row[label] = f"{v:.0f}"
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if lines:
        st.caption("Format: **projection | line lean ±edge (%)** — 🟢 = edge ≥8%. Lines = median across books.")
    elif api_key:
        if st.button("📡 Load live prop lines (~4 API credits)", key=f"loadprops_{away}_{home}"):
            with st.spinner("Fetching props from The Odds API..."):
                try:
                    fetched = dl.odds_api_event_props(api_key, ABBR_TO_NAME[away], ABBR_TO_NAME[home])
                    st.session_state[f"props_{away}_{home}"] = fetched
                    st.rerun()
                except Exception as e:
                    st.error(f"Props fetch failed: {e}")
    else:
        st.caption("Add your Odds API key in the sidebar to compare projections against live prop lines.")

# ---------------- SGP UI ----------------
def sgp_tab(g, away, home):
    lines = st.session_state.get(f"props_{away}_{home}", {})
    if not lines:
        st.info("Load live prop lines in the 🎰 Props tab first — SGP combos are built from them.")
        return
    key = (away, home)
    pred = pr.predict_game(g, elo, books_by_abbr.get(key), espn_odds.get(key), nv_injuries)
    projs = []
    for team, opp in ((away, home), (home, away)):
        res = get_projections(team, opp, team_inj_map(team))
        projs += pm.edges_vs_lines(res["players"], lines)
    legs = sgp.build_legs(projs, pred, home, away)
    if not legs:
        st.info("No usable legs found for this game.")
        return
    combos = sgp.best_combos(legs)
    if not combos:
        st.info("No correlated combos found.")
        return
    rows = []
    for c in combos:
        a, b = c["legs"]
        rows.append({
            "Leg 1": f"{a['label']} ({a['p']*100:.0f}%)",
            "Leg 2": f"{b['label']} ({b['p']*100:.0f}%)",
            "Correlation lift": f"×{c['lift']:.2f} (n={c['n']})",
            "Joint prob": f"{c['p_joint']*100:.0f}%",
            "Fair odds": f"{c['fair_american']:+d}",
            "If independent": f"{c['naive_american']:+d}",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("**How to use:** Fair odds include the empirical correlation lift (2024-25, n=544). "
               "Only bet the SGP if your book's price is *longer* than Fair — books adjust for "
               "correlation too, so compare before betting. Lift ≠ guaranteed edge.")

# ---------------- main loop ----------------
for _, g in week_games.iterrows():
    away, home = g["away_team"], g["home_team"]
    day = g["gameday"].strftime("%a %b %d") if pd.notna(g["gameday"]) else ""
    label = f"{away} @ {home}  •  {day} {g.get('gametime', '')} ET"
    with st.expander(label, expanded=False):
        spots = an.situational_spots(games, g)
        if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
            mph, wflag = wx.wind_for_game(g)
            if wflag == "under":
                spots.append(("🌬️ WIND", f"{mph:.0f} mph forecast at kickoff — under angle (60.9% unders 2021-25, n=87)", "UNDER"))
            elif wflag == "breezy":
                spots.append(("🌬️ BREEZY", f"{mph:.0f} mph forecast at kickoff — monitor", None))
        if spots:
            cols = st.columns(min(len(spots), 4))
            for i, (tag, detail, lean) in enumerate(spots):
                cols[i % len(cols)].warning(f"**{tag}**{' → ' + lean if lean else ''}\n\n{detail}")

        tabs = st.tabs(["🎯 Predictor", "🎰 Props", "🧩 SGP", "📊 Lines", "📈 Form (last 3)", "⚔️ H2H (5y)", "🏥 Injuries"])
        with tabs[0]:
            predictor_tab(g, away, home)
        with tabs[1]:
            props_tab(g, away, home)
        with tabs[2]:
            sgp_tab(g, away, home)
        with tabs[3]:
            lines_block(away, home, espn_odds.get((away, home)), books_by_abbr.get((away, home)))
        with tabs[4]:
            c1, c2 = st.columns(2)
            for col, team in ((c1, away), (c2, home)):
                col.markdown(f"**{team}**")
                df_team = form_df(team)
                if df_team is not None:
                    col.dataframe(df_team, hide_index=True, width="stretch")
                else:
                    col.info("No recent games found.")
        with tabs[5]:
            rows, summ = an.h2h(games, away, home, seasons=5)
            if rows:
                st.markdown(
                    f"**Last {summ['n']} meetings:** {away} {summ[away]['w']}W / {home} {summ[home]['w']}W "
                    f"• ATS: {away} {summ[away]['ats']}-{summ[home]['ats']} {home} "
                    f"• Totals: {summ['over']}O-{summ['under']}U" +
                    (f"-{summ['push']}P" if summ["push"] else ""))
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            else:
                st.info("No meetings in the last 5 seasons.")
        with tabs[6]:
            injuries_block(away, home)

st.caption("Historical lines: nflverse closing lines. Live: ESPN + The Odds API. For entertainment/research — bet responsibly.")
