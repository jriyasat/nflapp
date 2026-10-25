"""
Game detail view: render_game and tab functions.
"""
import streamlit as st
import pandas as pd
import analytics as an
import data as dl
ABBR_TO_NAME = {v: k for k, v in dl.TEAM_NAME_TO_ABBR.items()}

@st.cache_data(ttl=3600)
def get_projections(_ctx, team, opp, inj_items, team_line=None):
    """Memoized per-matchup projections (the heaviest per-rerun compute).
    inj_items: tuple(sorted(injuries.items())) for hashability."""
    return pm.project_game(_ctx.player_stats, _ctx.def_mults, team, opp,
                           injuries=dict(inj_items), team_line=team_line)

def team_inj_map(_ctx, team):
    m = {r["name"]: r["status"]
         for r in (_ctx.injuries.get(team) or {}).get("rows", []) if r.get("status")}
    return tuple(sorted(m.items()))

import predictor as pr
import weather as wx
import props_model as pm
import sgp
import tracker
import db
from shared import gate, paywall, logo_url, team_md, logo_img, TEAM_SET, LOGO_CFG, VALUE_EDGE_MIN
from views.live import _live_score_map

MODEL_EXPLAINER_MD = ""

PROJ_COLS = [("proj_pass", "Pass Yds"), ("proj_rush", "Rush Yds"),
             ("proj_rec_yds", "Rec Yds"), ("proj_rec", "Receptions"),
             ("proj_pass_td", "Pass TD"), ("proj_rush_td", "Rush TD"), ("proj_rec_td", "Rec TD")]


def form_df(ctx, team):
    rows = an.last_n(ctx.games, team, 3)
    if not rows:
        return None
    out = pd.DataFrame([{
        "Date": r["date"], "Game": f'{r["loc"]} {r["opp"]}', "Score": r["score"],
        "W/L": r["result"], "Line": f'{r["line"]:+.1f}' if pd.notna(r["line"]) else "-",
        "ATS": r["ats"], "Total": f'{r["total_line"]:.1f}' if pd.notna(r["total_line"]) else "-",
        "O/U": r["ou"],
    } for r in rows])
    return out

def fmt_ml(v):
    return f"{v:+d}" if isinstance(v, (int, float)) else "-"

@st.cache_data(ttl=600, show_spinner=False)


def _line_history(game_label):
    """Line-movement history per game (Turso roundtrip — cache 10 min so open
    tabs don't each pay a network call on every rerun)."""
    return db.line_history(game_label)



def fmt_spread(sp, home, away):
    """home-perspective spread (neg=home fav) -> 'SEA -3.1'"""
    return f"{home} {sp:.1f}" if sp < 0 else f"{away} {-sp:.1f}"




BOOK_NAMES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
              "caesars": "Caesars", "bovada": "Bovada", "mybookieag": "MyBookie",
              "betonlineag": "BetOnline", "williamhill_us": "Caesars", "espnbet": "ESPN BET",
              "betrivers": "BetRivers", "fanatics": "Fanatics", "hardrockbet": "Hard Rock"}


def _book_name(key):
    if not key:
        return "—"
    return BOOK_NAMES.get(key, key.replace("_", " ").title())


def _pre_game_tag(ctx, away, home):
    """Small lock note on Predictor/Lines tabs while the game is live."""
    ev = _live_score_map(ctx.season, ctx.week).get((away, home))
    if ev and ev["state"] == "in":
        st.caption("🔒 Pre-game numbers — locked at kickoff. Live score in the banner above.")


@st.fragment


def predictor_tab(ctx, g, away, home):
    _pre_game_tag(ctx, away, home)
    key = (away, home)
    wind_mph = None
    if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
        wind_mph, _ = wx.wind_for_game(g)
    pred = pr.predict_game(g, ctx.elo, ctx.books_by_abbr.get(key), ctx.espn_odds.get(key), ctx.injuries,
                           wind_mph=wind_mph)
    if pred["mode"] == "elo-only":
        st.info("No market lines posted yet — showing Elo-only estimate (edges compute once books post).")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        mcol, icol = st.columns([5, 1])
        mcol.metric("🤖 Model line", fmt_spread(pred["model_spread"], home, away))
        with icol:
            with st.popover("❓", help="Explain the Model"):
                st.markdown(MODEL_EXPLAINER_MD)
    if pred.get("market_spread") is not None:
        src = f"{pred['n_books']} book(s)" if pred["n_books"] else "nflverse current line"
        c2.metric("📚 Market", fmt_spread(pred["market_spread"], home, away), src)
        edge = pred["edge_pts"]
        side = home if edge > 0 else away
        c3.metric("⚡ Edge", f"{abs(edge):.1f} {side}",
                  "value" if abs(edge) >= ctx.VALUE_EDGE_MIN else "within noise",
                  delta_color="normal" if abs(edge) >= ctx.VALUE_EDGE_MIN else "off")
        if pred.get("model_total") is not None:
            gap = pred["model_total"] - pred["market_total"]
            lean = "UNDER" if gap < 0 else "OVER"
            c4.metric("🎚️ Model total", f"{pred['model_total']:.1f}",
                      f"mkt {pred['market_total']:.1f} → {lean} {abs(gap):.1f}")
        elif pred.get("market_total"):
            c4.metric("Total (market)", f"{pred['market_total']:.1f}")
        p = pred["p_home_cover"]
        st.markdown(f"**Cover probability:** {team_md(home, 20)} {p*100:.0f}% / {team_md(away, 20)} {(1-p)*100:.0f}%",
                    unsafe_allow_html=True)
        st.progress(min(max(p, 0.0), 1.0))
        rows = []
        br = (db.get_user(ctx.USER) or {}).get("bankroll")
        for side, team in (("home", home), ("away", away)):
            ev = pred.get(f"ev_{side}")
            if ev is not None:
                k = pred[f"kelly_{side}"]
                ktxt = (f"{k*100:.1f}% of bankroll" + (f" (${k*br:.0f})" if br else "")) if k > 0 else "no bet"
                rows.append({"Logo": logo_url(team), "Side": team, "EV @-110": f"{ev*100:+.1f}%",
                             "¼ Kelly stake": ktxt})
        for side in ("over", "under"):
            ev = pred.get(f"ev_{side}")
            if ev is not None:
                k = pred[f"kelly_{side}"]
                ktxt = (f"{k*100:.1f}% of bankroll" + (f" (${k*br:.0f})" if br else "")) if k > 0 else "no bet"
                rows.append({"Logo": None, "Side": side.upper(), "EV @-110": f"{ev*100:+.1f}%",
                             "¼ Kelly stake": ktxt})
        st.dataframe(pd.DataFrame(rows), column_config=LOGO_CFG, hide_index=True, width="stretch")
        if pred.get("total_adjustments"):
            st.markdown("**Total adjustments:** " + " • ".join(
                f"{n} {v:+.1f}" for n, v in pred["total_adjustments"]))
    else:
        c2.metric("Elo win prob", f"{home} {pred['p_elo']*100:.0f}%")
    if pred["adjustments"]:
        st.markdown("**Adjustments applied:** " + " • ".join(
            f"{a['module']} {logo_img(a['team'], 16)}{a['team']} {a['pts']:+.1f}"
            for a in pred["adjustments"]), unsafe_allow_html=True)
    for name, info in pred["angles"]:
        st.success(f"📐 **Angle:** {info['note']} — backtest: {info['record']} (2021-25)")
    st.caption("Base = de-vigged market consensus (85%) + Elo prior (15%) + backtested adjustments. "
               "EV assumes -110; Kelly shown at ¼ fraction. Historical ≠ future — size accordingly.")

# ---------------- props UI ----------------

def props_tab(ctx, g, away, home):
    if ctx.player_stats is None:
        st.warning("Player stats feed unavailable right now.")
        return
    # team lines (negative = favored) for the v2 rushing game-script factor
    mkt = pr.consensus(ctx.books_by_abbr.get((away, home)))
    hs = mkt.get("home_spread")
    if hs is None and pd.notna(g.get("spread_line")):
        hs = -float(g["spread_line"])  # nflverse is away-perspective -> flip to home
    lines = st.session_state.get(f"props_{away}_{home}", {})
    if not lines and ctx.api_key:  # shared daily cache: show today's lines free, no button press
        cached, ts = dl.cached_event_props(ABBR_TO_NAME[away], ABBR_TO_NAME[home])
        if cached:
            lines = cached
            st.session_state[f"props_{away}_{home}"] = cached
            st.session_state[f"props_ts_{away}_{home}"] = ts
    for team, opp in ((away, home), (home, away)):
        st.markdown(f"{team_md(team)} (vs {team_md(opp, 20)})", unsafe_allow_html=True)
        tl = (-hs if team == away else hs) if hs is not None else None
        res = get_projections(ctx, team, opp, team_inj_map(ctx, team), tl)
        # 🧪 injury what-if simulator: pretend any player is OUT, watch volume reshuffle
        sim = st.multiselect(f"🧪 Simulate OUT ({team})",
                             [p["player"] for p in res["players"]],
                             key=f"sim_{away}_{home}_{team}",
                             placeholder="What-if: bench a player…")
        if sim:
            inj = dict(team_inj_map(ctx, team))
            for nm in sim:
                inj[nm] = "Out"
            res = get_projections(ctx, team, opp, tuple(sorted(inj.items())), tl)
        for w in res["warnings"]:
            st.error(w)
        if res["benched"]:
            st.warning("🚑 Benched: " + ", ".join(f"{b['player']} ({b['status']})" for b in res["benched"])
                       + " — volume redistributed")
        projs = pm.edges_vs_lines(res["players"], lines)
        rows = []  # one table per team, under its header (edge-sorted)
        for p in projs:
            name = p["player"] + (" ⚠️" if p.get("flag") else "")
            if p.get("boost"):
                name += f" ↑{p['boost']:.2f}x"
            if p.get("rush_v2"):
                name += " ⚡"
            for col, label in PROJ_COLS:
                v = p.get(col)
                if v is None:
                    continue
                e = p.get("edges", {}).get(col)
                if e:
                    over = e["lean"] == "OVER"
                    book = e.get("over_book") if over else e.get("under_book")
                    price = e.get("over_price") if over else e.get("under_price")
                    bb = _book_name(book)
                    if book and price is not None:
                        bb += f" {price:+.0f}"
                    mark = "🟢" if abs(e["edge_pct"]) >= 8 else "⚪"
                    hr = (pm.hit_rate(ctx.player_stats, p["player_id"], col, e["line"])
                          if p.get("player_id") else None)
                    l5 = (f"{'O' if hr['overs'] >= hr['unders'] else 'U'} "
                          f"{max(hr['overs'], hr['unders'])}-{min(hr['overs'], hr['unders'])}") if hr else ""
                    rows.append({"Player": name, "Prop": label,
                                 "Proj": round(float(v)), "Line": e["line"], "Best Book": bb,
                                 "Edge": f"{mark} {e['lean']} {e['edge_pct']:+.0f}%",
                                 "L5": l5, "_sort": abs(e["edge_pct"])})
                else:
                    rows.append({"Player": name, "Prop": label,
                                 "Proj": round(float(v)), "Line": None, "Best Book": "—",
                                 "Edge": "—", "L5": "", "_sort": -1})
        # group by player: each player's markets stacked (best edge first within
        # the player), players ordered by their best edge. Name prints only on
        # the first row of each block — reads like merged cells, not duplicates.
        _by_p = {}
        for r in rows:
            _by_p.setdefault(r["Player"], []).append(r)
        rows = []
        for p in sorted(_by_p, key=lambda p: -max(x["_sort"] for x in _by_p[p])):
            for i, r in enumerate(sorted(_by_p[p], key=lambda x: -x["_sort"])):
                rows.append(r if i == 0 else dict(r, Player=""))
        for r in rows:
            r.pop("_sort")
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("**Proj** = NFL Edge model projection — *our* number, built from player stats. "
               "Not a book line.")
    if lines:
        ts = st.session_state.get(f"props_ts_{away}_{home}")
        if ts:
            st.caption(f"🕐 Lines as of {pd.Timestamp.fromtimestamp(ts).strftime('%a %-I:%M %p')} "
                       "— prop lines auto-load Mon & Sat, cached between runs "
                       "(spreads/totals stay live).")
        st.caption("🟢 = edge ≥8% (line = median across books) · **Best Book** = best price for the lean · "
                   "**L5** = his over/under record vs that line in his last 5 games · "
                   "⚡ = v2 rushing model (backtest-validated: 61% lean hit 2023-25, see docs/BACKTESTS.md).")
        if ctx.api_key and st.button("↻ Refresh prop lines", key=f"refreshprops_{away}_{home}",
                                 help="Fetch fresh lines for THIS game now (~4 API credits — "
                                      "admin unlimited, otherwise counts as your daily load)"):
            used = db.usage_today(ctx.USER, "prop_load")
            if not ctx.IS_ADMIN and used >= 1:
                st.error("Daily prop-line load used (1/day per user — protects the shared free "
                         "API quota). Resets at midnight. Admin loads are unlimited.")
            else:
                with st.spinner("Fetching fresh prop lines..."):
                    try:
                        dl.bust_event_props_cache(ABBR_TO_NAME[away], ABBR_TO_NAME[home])
                        fetched = dl.odds_api_event_props(props_ctx.api_key, ABBR_TO_NAME[away], ABBR_TO_NAME[home])
                        if not ctx.IS_ADMIN:
                            db.bump_usage(ctx.USER, "prop_load")
                        if fetched:
                            st.session_state[f"props_{away}_{home}"] = fetched
                            st.session_state[f"props_ts_{away}_{home}"] = pd.Timestamp.now().timestamp()
                            st.session_state.pop(f"props_none_{away}_{home}", None)
                            st.rerun()
                        else:
                            st.warning("No player props posted for this game yet — books usually hang "
                                       "them a few days before kickoff.")
                    except Exception as e:
                        st.error(f"Props fetch failed: {e}" if ctx.IS_ADMIN
                                 else "Props fetch failed right now — try again later.")
    elif ctx.api_key:
        if st.button("📡 Load live prop lines", key=f"loadprops_{away}_{home}",
                     help="Lines auto-load Mon & Sat; this fetches fresh now (~4 API credits — "
                          "admin unlimited, otherwise counts as your daily load)."):
            warm, _ = dl.cached_event_props(ABBR_TO_NAME[away], ABBR_TO_NAME[home])
            real_fetch = warm is None
            used = db.usage_today(ctx.USER, "prop_load")
            if real_fetch and not ctx.IS_ADMIN and used >= 1:
                st.error("Daily prop-line load used (1/day per user — protects the shared free "
                         "API quota). Resets at midnight. Admin loads are unlimited.")
            else:
                with st.spinner("Fetching props from The Odds API..." if real_fetch
                                else "Reading today's shared cache..."):
                    try:
                        fetched = dl.odds_api_event_props(props_ctx.api_key, ABBR_TO_NAME[away], ABBR_TO_NAME[home])
                        if real_fetch:
                            db.bump_usage(ctx.USER, "prop_load")
                        if fetched:
                            st.session_state[f"props_{away}_{home}"] = fetched
                            st.session_state[f"props_ts_{away}_{home}"] = pd.Timestamp.now().timestamp()
                            st.rerun()
                        else:
                            st.session_state[f"props_none_{away}_{home}"] = True
                            st.warning("No player props posted for this game yet — books usually hang "
                                       "them a few days before kickoff. Check back then.")
                    except Exception as e:
                        st.error(f"Props fetch failed: {e}" if ctx.IS_ADMIN
                                 else "Props fetch failed right now — try again later.")
        if st.session_state.get(f"props_none_{away}_{home}"):
            st.caption("Last check: props not on the board yet.")
    else:
        st.caption("Add your Odds API key in the sidebar to compare projections against live prop lines.")

# ---------------- SGP UI ----------------


def sgp_tab(ctx, g, away, home):
    lines = st.session_state.get(f"props_{away}_{home}", {})
    if not lines and ctx.api_key:  # shared daily cache (same as Props tab)
        cached, ts = dl.cached_event_props(ABBR_TO_NAME[away], ABBR_TO_NAME[home])
        if cached:
            lines = cached
            st.session_state[f"props_{away}_{home}"] = cached
            st.session_state[f"props_ts_{away}_{home}"] = ts
    if not lines:
        st.info("No prop lines cached for this game — lines auto-load Mon (TNF) & Sat (full slate), "
                "or grab them now in the 🎰 Props tab (~4 API credits). "
                "SGP combos are built from those lines.")
        return
    key = (away, home)
    pred = pr.predict_game(g, ctx.elo, ctx.books_by_abbr.get(key), ctx.espn_odds.get(key), ctx.injuries)
    projs = []
    for team, opp in ((away, home), (home, away)):
        res = get_projections(ctx, team, opp, team_inj_map(ctx, team))
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
            "Combo boost": f"×{c['lift']:.2f} (n={c['n']})",
            "Both hit": f"{c['p_joint']*100:.0f}%",
            "Fair price": f"{c['fair_american']:+d}",
            "No-boost price": f"{c['naive_american']:+d}",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("**How to use:** Fair price includes the measured combo boost (2024-25, n=544 real games). "
               "Only bet the SGP if your book's price is *longer* than Fair — books adjust for "
               "correlation too, so compare before betting. Boost ≠ guaranteed edge.")



def lines_block(ctx, g, away, home, espn_o, books):
    _pre_game_tag(ctx, away, home)
    # model context — shared by the chart overlay and the pinned table row
    wind_mph = None
    if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
        wind_mph, _ = wx.wind_for_game(g)
    pred = pr.predict_game(g, ctx.elo, books=books, espn=espn_o,
                           injuries=ctx.injuries, wind_mph=wind_mph)
    hist = _line_history(f"{away} @ {home}")
    if len(hist) >= 2:
        st.caption("📉 Line movement (daily snapshots, away-team spread) — flat line = current model")
        m1, m2 = st.columns(2)
        move = hist.set_index("ts")[["spread_away"]].copy()
        move["🤖 model (now)"] = round(-pred["model_spread"], 2)  # home-persp -> away-persp
        m1.line_chart(move, y_label="spread (away)")
        tot = hist.set_index("ts")[["total"]].copy()
        if pred.get("model_total") is not None:
            tot["🤖 model (now)"] = round(pred["model_total"], 1)
        m2.line_chart(tot, y_label="total")
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
    # pinned 🤖 MODEL row: model spread + total next to the market, ⚡ when |edge| >= ctx.VALUE_EDGE_MIN
    edge = pred.get("edge_pts")
    badge = " ⚡ VALUE" if edge is not None and abs(edge) >= ctx.VALUE_EDGE_MIN else ""
    side = home if (edge or 0) > 0 else away
    rows.insert(0, {
        "Book": f"🤖 MODEL{badge}",
        "Spread": fmt_spread(pred["model_spread"], home, away)
                  + (f" (edge {abs(edge):.1f} on {side})" if badge else ""),
        "Total": f"{pred['model_total']:.1f}" if pred.get("model_total") is not None else "-",
        "ML": "—",
    })
    st.table(pd.DataFrame(rows))
    if not books and not espn_o:
        st.caption("No live lines posted yet — model row is an Elo-only estimate.")
    if books:
        best = an.line_shopping(books)
        if best.get("books_disagree"):
            st.success("⚡ Books disagree on the number -- line shopping value available")
        tags = []
        if best.get("home_spread"):
            b = best["home_spread"]; tags.append(f"Best {team_md(home, 18)} spread: {b['point']:+.1f} @ {b['book']}")
        if best.get("away_spread"):
            b = best["away_spread"]; tags.append(f"Best {team_md(away, 18)} spread: {b['point']:+.1f} @ {b['book']}")
        if best.get("over"):
            tags.append(f"Best Over: {best['over']['point']:.1f} @ {best['over']['book']}")
        if best.get("under"):
            tags.append(f"Best Under: {best['under']['point']:.1f} @ {best['under']['book']}")
        if tags:
            st.markdown(" • ".join(tags), unsafe_allow_html=True)



def injuries_block(ctx, away, home):
    any_data = False
    for team in (away, home):
        nv = ctx.injuries.get(team)
        if nv and nv["rows"]:
            any_data = True
            st.markdown(f"{team_md(team)} — official NFL report ({nv['label']})",
                        unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{
                "Player": r["name"], "Pos": r["position"], "Status": r["status"],
                "Injury": r["detail"], "Practice": r["practice"],
            } for r in nv["rows"]]), hide_index=True, width="stretch")
        else:
            rows = ctx.injuries.get(team, [])
            if rows:
                any_data = True
                st.markdown(f"{team_md(team)} — via ESPN", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame([{
                    "Player": r["name"], "Pos": r["position"],
                    "Status": r["status"], "Injury": r["detail"],
                } for r in rows]), hide_index=True, width="stretch")
    if not any_data:
        if ctx.injuries_err and nv_status != "ok":
            st.warning("Injury feeds temporarily unavailable — hit 🔄 Refresh in a few minutes.")
        else:
            st.info("No injuries listed (official report publishes Wednesday of game week).")



def slip_tab(ctx, g, away, home):
    """Add this game as a parlay leg. The slip is reviewed & saved on the Journal page."""
    slip = st.session_state.setdefault("slip", [])
    label = f"{away} @ {home}"
    flash = st.session_state.get("slip_flash")
    if flash is not None and flash != len(slip):
        st.session_state.pop("slip_flash", None)  # slip changed since (saved/edited) -> clear
        flash = None
    if flash is not None:
        st.markdown(f"✅ Leg added to your bet slip ({flash} legs) — review & save in the "
                    f"<a href='?page=journal' target='_self'>Bet Journal</a>",
                    unsafe_allow_html=True)
    bt = st.selectbox("Bet type", ["spread", "ml", "total"], key=f"slip_bt_{label}")
    if bt == "total":
        sel = st.selectbox("Side", ["over", "under"], key=f"slip_sel_{label}")
        default_line = float(g["total_line"]) if pd.notna(g["total_line"]) else 45.5
    else:
        sel = st.selectbox("Team", [away, home], key=f"slip_sel_{label}")
        if bt == "spread" and pd.notna(g["spread_line"]):
            base = float(g["spread_line"])
            default_line = base if sel == away else -base
        else:
            default_line = 0.0
    line = st.number_input("Line (team spread / total)", value=float(default_line), step=0.5,
                           key=f"slip_line_{bt}_{label}", disabled=(bt == "ml"))
    odds = st.number_input("Leg odds (American)", value=-110, step=5, key=f"slip_odds_{label}")
    dupe = any(l["game"] == label and l["bet_type"] == bt and l["selection"] == sel for l in slip)
    if st.button("➕ Add to bet slip", key=f"slip_add_{label}", type="primary", disabled=dupe,
                 help=("Already on your slip — that exact leg is there. Add a different leg or game."
                       if dupe else "Add this leg to your bet slip")):
        slip.append({"game": label, "bet_type": bt, "selection": sel,
                     "season": int(g["season"]), "week": int(g["week"]),
                     "line": None if bt == "ml" else float(line), "odds": int(odds)})
        st.session_state["slip_flash"] = len(slip)
        st.rerun()
    if slip:
        st.caption("Slip: " + " · ".join(f"{l['selection']} {l['bet_type']}" for l in slip))



def sentiment_tab(ctx, g, away, home):
    """Sentiment Lab: show sentiment scores, composite diff, pick, and inline word clouds."""
    st.subheader("🧠 Sentiment Lab")
    st.caption(f"Sentiment analysis for {away} @ {home}")
    
    # Try to import sentiment module
    try:
        import sentiment as stm
        season = int(g['season'])
        week = int(g['week'])
        
        # Get sentiment scores
        away_score = stm.get_sentiment_score(away, season, week, 'combined')
        home_score = stm.get_sentiment_score(home, season, week, 'combined')
        
        if away_score and home_score:
            away_comp = away_score.get('composite', 0)
            home_comp = home_score.get('composite', 0)
            diff = home_comp - away_comp
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(f"{away} Composite", f"{away_comp:.2f}")
                if away_score.get('confidence') is not None:
                    st.caption(f"Confidence: {away_score['confidence']:.2f}")
                    st.caption(f"Morale: {away_score['morale']:.2f}")
                    st.caption(f"Controversy: {away_score['controversy']:.2f}")
            
            with col2:
                st.metric(f"{home} Composite", f"{home_comp:.2f}")
                if home_score.get('confidence') is not None:
                    st.caption(f"Confidence: {home_score['confidence']:.2f}")
                    st.caption(f"Morale: {home_score['morale']:.2f}")
                    st.caption(f"Controversy: {home_score['controversy']:.2f}")
            
            with col3:
                pick = home if diff > 0 else away
                st.metric("Composite Diff", f"{diff:+.2f}", f"Pick: {pick}")
                # Sentiment pick based on threshold (default 0.5)
                threshold = 0.5
                if abs(diff) >= threshold:
                    st.success(f"Sentiment Pick: {pick} (diff ≥ {threshold})")
                else:
                    st.info("No clear sentiment pick (diff < threshold)")
            
            # Word Clouds
            st.divider()
            st.subheader("Word Clouds")
            
            # Build inline word clouds (no external image service)
            away_html = stm.word_cloud_html(away, season, week, 'combined')
            home_html = stm.word_cloud_html(home, season, week, 'combined')

            col_a, col_h = st.columns(2)
            with col_a:
                st.write(f"**{away} Sentiment Words**")
                if away_html:
                    st.markdown(away_html, unsafe_allow_html=True)
                else:
                    st.info(f"No news snippets available for {away}")
                    if st.button(f"Collect {away} News", key=f"collect_{away}"):
                        snippets = stm.collect_news_snippets(away)
                        if snippets:
                            st.success(f"Collected {len(snippets)} snippets")
                        else:
                            st.warning("No snippets found")

            with col_h:
                st.write(f"**{home} Sentiment Words**")
                if home_html:
                    st.markdown(home_html, unsafe_allow_html=True)
                else:
                    st.info(f"No news snippets available for {home}")
                    if st.button(f"Collect {home} News", key=f"collect_{home}"):
                        snippets = stm.collect_news_snippets(home)
                        if snippets:
                            st.success(f"Collected {len(snippets)} snippets")
                        else:
                            st.warning("No snippets found")
            
        else:
            st.warning(f"Sentiment scores not available for {away} and/or {home}. Ensure sentiment collection has run.")
            if st.button("Collect Sentiment for This Week", key="collect_sent"):
                st.info("Sentiment collection would run here (requires OpenRouter API key).")
    except ImportError:
        st.error("Sentiment module not available.")
    except Exception as e:
        st.error(f"Error loading sentiment: {e}")




def handle_tab(ctx, g, away, home):
    """Handle tab: public betting percentages (Action Network) and derived money flow."""
    st.subheader("💰 Handle")
    st.caption(f"Public betting splits for {away} @ {home}")
    
    import data as dl
    try:
        an_data = dl.actionnetwork_public_betting()
    except Exception as e:
        st.error(f"Failed to fetch handle data: {e}")
        an_data = {}
    
    key = (away, home)
    if key not in an_data:
        st.warning("Handle data not available for this matchup.")
        st.info("Action Network provides public bet percentages for all games, but money percentages are limited to two games per week (free tier).")
        # Optional: compute derived money flow from line movement / vig skew
        return
    
    vals = an_data[key]
    bet_away = vals.get('bet_pct_away')
    bet_home = vals.get('bet_pct_home')
    money_away = vals.get('money_pct_away')
    money_home = vals.get('money_pct_home')
    diff = vals.get('diff')
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Public Bets (Away)", f"{bet_away}%" if bet_away is not None else "N/A")
        st.metric("Public Bets (Home)", f"{bet_home}%" if bet_home is not None else "N/A")
    with col2:
        st.metric("Money % (Away)", f"{money_away}%" if money_away is not None else "Locked")
        st.metric("Money % (Home)", f"{money_home}%" if money_home is not None else "Locked")
    with col3:
        if diff is not None:
            st.metric("Money-Bet Diff (Home)", f"{diff:+.1f}%")
            if diff > 0:
                st.success("Sharp side: HOME (money heavier than bets)")
            elif diff < 0:
                st.success("Sharp side: AWAY (money lighter than bets)")
            else:
                st.info("Money matches bets")
        else:
            st.metric("Diff", "N/A")
    
    if money_away is None or money_home is None:
        st.info("💰 Money percentages are locked for this game. Action Network's free tier only unlocks the first two games each week.")
    
    # Add derived money flow from line movement (future enhancement)
    st.caption("Sharp side detection: money‑bet diff >0 indicates sharp money on that side.")




def _live_strip(ctx, away, home):
    """Auto-updating live-game strip above an open game. Loud by design."""
    ev = _live_score_map(ctx.season, ctx.week).get((away, home))
    if not ev or ev["state"] == "pre":
        return
    if ev["state"] == "post":
        st.success(f"🏁 **Final: {ev['away']} {ev['a_score']} @ {ev['home']} {ev['h_score']}** "
                   f"— this game moves to 🏁 Completed on the next data refresh.")
        return
    st.error(f"🔒 **LOCKED AT KICKOFF** — the lines, edges & model numbers below are the "
             f"**pre-game** numbers, frozen at kickoff. They do NOT move during the game.\n\n"
             f"🔴 **LIVE: {ev['away']} {ev['a_score']} @ {ev['home']} {ev['h_score']}**"
             f"  —  {ev['detail']}")
def _completed_rows(ctx, season, week):
    """Completed games: final score + model receipts, graded at the nflverse
    CLOSING line (same standard as Track Record). Badges only where the model
    had a bettable lean (>=2.0 pts), matching the board's star/green rules."""
    wk = ctx.games[(ctx.games["season"] == season) & (ctx.games["game_type"] == "REG") &
                   (ctx.games["week"] == week) & (ctx.games["result"].notna())].sort_values(["gameday", "gametime"])
    # honest receipts: each game's model line comes from an Elo that has NOT
    # absorbed that game's own result (one rebuild per distinct gameday)
    gd = pd.to_datetime(ctx.games["gameday"], errors="coerce")
    elo_by_day = {d: pr.Elo(ctx.games[gd < d]) for d in sorted(pd.to_datetime(wk["gameday"]).unique())}
    rows = []
    for _, g in wk.iterrows():
        away, home = g["away_team"], g["home_team"]
        pred = pr.predict_game(g, elo_by_day.get(pd.Timestamp(g["gameday"]), ctx.elo), None, None, ctx.injuries)
        ms = pred.get("model_spread")          # home-perspective (neg = home)
        mt = pred.get("model_total")
        mk_home = -float(g["spread_line"]) if pd.notna(g["spread_line"]) else None
        kt = float(g["total_line"]) if pd.notna(g["total_line"]) else None
        margin = float(g["result"])            # home margin
        actual_total = float(g["total"]) if pd.notna(g["total"]) else None
        # spread receipt
        sp_pick_logo, sp_badge = "", "—"
        if ms is not None and mk_home is not None:
            edge_h = mk_home - ms              # >0: model likes home vs market
            if abs(edge_h) >= VALUE_EDGE_MIN:
                pick_home = edge_h > 0
                cover = margin + mk_home       # >0 home covers, <0 away covers
                hit = (cover > 0) if pick_home else (cover < 0)
                sp_badge = "➖" if cover == 0 else ("✅" if hit else "❌")
                sp_pick_logo = logo_url(home if pick_home else away)
        # total receipt
        tot_lean = "—"
        if mt is not None and kt is not None and actual_total is not None:
            diff = float(mt) - kt
            if abs(diff) >= VALUE_EDGE_MIN:
                over = diff > 0
                hit = (actual_total > kt) if over else (actual_total < kt)
                badge = "➖ push" if actual_total == kt else ("✅" if hit else "❌")
                tot_lean = f"{'OVER' if over else 'UNDER'} {kt:.1f} {badge}"
        winner = home if margin > 0 else (away if margin < 0 else "")
        rows.append({
            "Final": f"{away} {int(g['away_score'])} @ {home} {int(g['home_score'])}",
            "Winner": logo_url(winner) if winner else "",
            "Model Line": fmt_spread(ms, home, away) if ms is not None else "—",
            "Closing Line": fmt_spread(mk_home, home, away) if mk_home is not None else "—",
            "Spread pick": sp_pick_logo,
            "ATS": sp_badge,
            "Total lean": tot_lean,
        })
    return rows
def render_game(ctx, gi, g):
    away, home = g["away_team"], g["home_team"]
    spots = an.situational_spots(ctx.games, g)
    if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
        mph, wflag = wx.wind_for_game(g)
        if wflag == "under":
            spots.append(("🌬️ WIND", f"{mph:.0f} mph forecast at kickoff — under angle (60.9% unders 2021-25, n=87)", "UNDER"))
        elif wflag == "breezy":
            spots.append(("🌬️ BREEZY", f"{mph:.0f} mph forecast at kickoff — monitor", None))
    if spots:
        cols = st.columns(min(len(spots), 4))
        for i, (tag, detail, lean) in enumerate(spots):
            cols[i % len(cols)].warning(f"**{tag}**{' → ' + lean if lean else ''}\\n\\n{detail}")

    tabs = st.tabs(["🎯 Predictor", "🎰 Props", "🧩 SGP", "📊 Lines", "📈 Form (last 3)", "⚔️ H2H (5y)", "🏥 Injuries", "🎟️ Slip", "🧠 Sentiment Lab", "💰 Handle"])
    with tabs[0]:
        predictor_tab(ctx, g, away, home)
    with tabs[1]:
        if gate(ctx,"props"):
            props_tab(ctx, g, away, home)
        else:
            paywall(ctx,"Player Props")
    with tabs[2]:
        if gate(ctx,"sgp"):
            sgp_tab(ctx, g, away, home)
        else:
            paywall(ctx,"The SGP correlation finder")
    with tabs[3]:
        lines_block(ctx, g, away, home, ctx.espn_odds.get((away, home)), ctx.books_by_abbr.get((away, home)))
    with tabs[4]:
        c1, c2 = st.columns(2)
        for col, team in ((c1, away), (c2, home)):
            col.markdown(team_md(team), unsafe_allow_html=True)
            df_team = form_df(ctx, team)
            if df_team is not None:
                col.dataframe(df_team, hide_index=True, width="stretch")
            else:
                col.info("No recent games found.")
    with tabs[5]:
        rows, summ = an.h2h(ctx.games, away, home, seasons=5)
        if rows:
            st.markdown(
                f"**Last {summ['n']} meetings:** {team_md(away, 20)} {summ[away]['w']}W / "
                f"{team_md(home, 20)} {summ[home]['w']}W "
                f"• ATS: {away} {summ[away]['ats']}-{summ[home]['ats']} {home} "
                f"• Totals: {summ['over']}O-{summ['under']}U" +
                (f"-{summ['push']}P" if summ["push"] else ""), unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.info("No meetings in the last 5 seasons.")
    with tabs[6]:
        injuries_block(ctx, away, home)
    with tabs[7]:
        if gate(ctx,"journal"):
            slip_tab(ctx, g, away, home)
        else:
            paywall(ctx,"The bet slip (parlays + journal)")
    with tabs[8]:
        sentiment_tab(ctx, g, away, home)
    with tabs[9]:
        handle_tab(ctx, g, away, home)



