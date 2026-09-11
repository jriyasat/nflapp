"""NFL Edge Finder -- Streamlit app.

Run:  streamlit run app.py
"""

import os
import secrets

import bcrypt
import pandas as pd
import streamlit as st

import analytics as an
import auth_setup
import data as dl
import db
import emailer
import journal
import predictor as pr
import props_model as pm
import sgp
import tracker
import weather as wx

st.set_page_config(page_title="NFL Edge Finder", page_icon="🏈", layout="wide")

st.markdown("""
<style>
@keyframes glowPulse {
  0%, 100% { opacity: .65; text-shadow: 0 0 4px #7cffb2, 0 0 10px #7cffb2; }
  50%      { opacity: 1;   text-shadow: 0 0 14px #7cffb2, 0 0 30px #39ff88; }
}
/* replace spinner icons with glowing LOADING text */
[data-testid="stSpinner"] svg,
[data-testid="stSpinner"] .st-emotion-cache-spinner,
[data-testid="stStatusWidget"] svg { display: none !important; }
[data-testid="stSpinner"] > div,
[data-testid="stStatusWidget"] {
  font-weight: 700 !important;
  letter-spacing: .22em !important;
  color: #7cffb2 !important;
  animation: glowPulse 1.2s ease-in-out infinite !important;
}
[data-testid="stSpinner"] > div::before { content: "⏳ LOADING — "; letter-spacing: .1em; }
/* compact help popover button beside metric labels */
[data-testid="stPopover"] > button {
  border: none !important; background: transparent !important;
  padding: 0 .15rem !important; margin-top: .55rem; font-size: .9rem;
}
</style>
""", unsafe_allow_html=True)

MODEL_EXPLAINER_MD = """
**In one sentence:** the model starts from the sportsbooks' own odds — the market is the
single best predictor of NFL games — then nudges that number with our Elo ratings and a few
backtest-proven adjustments, and only flags value when the gap between model and market is
big enough to beat the vig.

---

**How it works, in detail:**

**1. Market base (85% of the prediction).** Every book's moneyline implies a win probability
with the vig (their cut) baked in. We strip the vig from every book, take the median across
books, and use that as the "true" consensus. We tested the alternative: a pure stats model
(Elo) against the closing line went **51.1% ATS over 1,359 games — below the 52.4% needed
to break even at -110**. So the market leads; we don't fight it.

**2. Elo prior (15%).** FiveThirtyEight-style ratings updated game-by-game since 1999, with
margin-of-victory multipliers and offseason regression. Backtest: 62.9% straight-up win
accuracy. Its job: sanity-check the market and carry predictions before lines post.

**3. Backtest-validated adjustments (capped ±2.5 pts).** Only adjustments that proved
themselves against 5 years of closing lines are allowed in:
- *Injuries* — a starting QB Out moves the number ~5.5 pts; other starters ~0.4 each
- *Rest fade* — teams with 3+ extra rest days covered only 47% (the market overprices rest),
  so we shave half a point off the rested side

**4. Totals model.** Market total plus validated adjustments (capped ±3.5): wind 15+ mph
(−2.7), wind 10-14 (−1.2), close spread ≤3 (−1.3), blowout setup 7+ (+0.8), early season
(−1.0), extreme-under referees (−0.5 to −1.0).

**5. Edge → probability → money.** Model vs market gap becomes a cover probability
(NFL scoring margins are roughly normal, SD ≈ 13.3), then **EV%** at standard -110 odds,
then a **¼-Kelly** stake suggestion. If the edge is smaller than the vig, the app literally
says "no bet" — most games are.

**Honesty clause:** every angle badge shows its real 2021-25 record next to it, and the
📒 Bet Journal grades the model's picks against closing lines all season. If it stops
working, the numbers will say so.

---

**📖 Terms used above (plain English):**

- **Spread** — the handicap on a game. SEA -3.5 means Seattle must win by 4+ for a spread bet on them to win.
- **Cover** — beating the spread. SEA -3.5 "covers" if they win by 4 or more.
- **ATS (against the spread)** — a record measured against the spread, not wins/losses. A team can go 10-7 but 6-11 ATS.
- **Total / Over-Under** — combined points of both teams. Over 44.5 wins at 45+ combined points.
- **Moneyline (ML)** — a bet on who wins outright, no spread. Odds like -150 / +130.
- **-110** — standard odds: bet $110 to win $100. The $10 difference is the book's cut.
- **Vig (juice)** — the bookmaker's built-in cut. It's why both sides are -110 instead of +100, and why you must win 52.4% to break even.
- **De-vig** — removing that cut from the odds to reveal the book's *true* implied probability. That's how we find the real market price.
- **Closing line** — the final spread/total right before kickoff. The smartest number in betting — beating it consistently = real edge.
- **Elo** — a power rating per team (borrowed from chess). The gap between two ratings predicts the winner: +100 points ≈ 64% win chance, +200 ≈ 76%. Win and you take points from your opponent; upsets move ratings, expected wins barely do. Ours: home field = 48 pts (≈2 pts of spread), ratings pull ⅓ back to average each offseason. Full mini-lesson: the **❓ How It Works** page.
- **Cover probability** — the model's estimated chance a side covers. 55% means it expects to win that bet ~55 times out of 100.
- **EV (expected value)** — average profit per dollar bet, long run. +3% EV ≈ +$3 per $100 over many bets. Negative EV = the vig eats you.
- **Kelly / ¼-Kelly** — a formula for bet sizing from edge size. Full Kelly is aggressive; we show a quarter of it (¼-Kelly) to keep swings survivable.
- **Unit (u)** — your standard bet size, whatever it is. +2.5u profit = two and a half of your usual bets.
- **Push** — an exact tie against the number (lands exactly on the spread/total). Stake refunded.
- **No bet** — the model's edge is smaller than the vig, so betting would lose money long-term even if it "feels right." Discipline is the product.
"""

st.title("🏈 NFL Edge Finder")
st.caption("Predictor (sides+totals) • Props • SGP • Lines • Form • H2H (5y) • Injuries — click any game to expand")

# ---------------- auth gate ----------------
authenticator = auth_setup.get_authenticator()
if st.session_state.get("authentication_status") is not True:
    authenticator.login(location="main")
if st.session_state.get("authentication_status") is not True:
    st.stop()
if not st.session_state.get("username"):
    st.stop()  # authenticated but no username — never default to a real account
USER = st.session_state["username"]
NAME = st.session_state.get("name", USER)
LEVEL = db.user_level(USER)
IS_ADMIN = LEVEL == "admin"
IS_PAID = LEVEL in ("admin", "paid")  # full feature access (admins included)
CONTACT_EMAIL = "jeff.riyasat@gmail.com"

# central feature gates: feature -> minimum tier. Change tiers in ONE place.
_LEVEL_RANK = {"user": 0, "paid": 1, "admin": 2}
FEATURE_GATES = {"props": "paid", "sgp": "paid", "journal": "paid", "email_brief": "paid"}


def gate(feature):
    return _LEVEL_RANK.get(LEVEL, 0) >= _LEVEL_RANK[FEATURE_GATES.get(feature, "admin")]


def paywall(feature):
    """Upgrade wall shown to free-tier users behind gated features."""
    st.info(f"🔒 **{feature}** is a **Pro** feature.")
    st.markdown(
        "Pro unlocks: 🎰 **Player Props** (injury-aware projections vs live lines) · "
        "🧩 **SGP correlation finder** · 📒 **Bet Journal + CLV tracker** · "
        "📧 **daily email brief**\n\n"
        f"👉 To upgrade, contact us at [{CONTACT_EMAIL}](mailto:{CONTACT_EMAIL}).")

# ---------------- team logos (shared; same pattern as the games list) ----------------
TEAM_SET = {t for ts in an.DIVISIONS.values() for t in ts}
LOGO_ALIAS = {"STL": "LAR", "SD": "LAC", "OAK": "LV", "LA": "LAR"}  # relocated/legacy abbrs -> current logo
LOGO_CFG = {"Logo": st.column_config.ImageColumn("Logo", width="small")}

# Logo source: jsDelivr CDN mirror of the public repo's static/logos/.
# Streamlit Cloud's proxy/auth wall breaks its own /app/static/ route (logos 303/hang
# there despite enableStaticServing); the CDN works behind any auth, anywhere.
# NOTE: requires the repo to stay PUBLIC. If it ever goes private, switch LOGO_BASE
# back to "/app/static/logos" (works locally + on any VPS we control).
LOGO_BASE = "https://cdn.jsdelivr.net/gh/jriyasat/nflapp@main/static/logos"

def _logo_team(t):
    """Resolve a team abbr (incl. historical) to the abbr that has a logo PNG."""
    return t if t in TEAM_SET else LOGO_ALIAS.get(t)

def logo_img(t, size=24):
    """Inline logo <img> for markdown spots. Self-hides if the PNG is missing."""
    t = _logo_team(t)
    if not t:
        return ""
    return (f'<img src="{LOGO_BASE}/{t}.png" width="{size}" '
            f'style="vertical-align:middle;border-radius:4px;margin-right:4px" '
            f'onerror="this.style.display=\'none\'">')

def team_md(t, size=24):
    return f"{logo_img(t, size)}**{t}**"

def matchup_md(away, home, size=24):
    return f"{team_md(away, size)} @ {team_md(home, size)}"

def logo_url(t):
    """Logo URL for dataframe ImageColumn cells (None -> blank cell)."""
    t = _logo_team(t)
    return f"{LOGO_BASE}/{t}.png" if t else None

def pick_logo(t, picked=False, grade_icon=None, size=76, model=False):
    """Big pick'em-board logo. Green ring = your pick. Blue ring + 🤖 badge = model's
    side. Both on one logo = you're riding with the model; opposite logos = fading it."""
    lt = _logo_team(t)
    if not lt:
        return ""
    if picked:
        ring = "border:3px solid #7cffb2;box-shadow:0 0 14px #7cffb2aa;padding:3px;"
    elif model:
        ring = "border:3px solid #58a6ff;box-shadow:0 0 14px #58a6ff88;padding:3px;"
    else:
        ring = "border:3px solid transparent;"
    img = f'<img src="{LOGO_BASE}/{lt}.png" style="width:{size}px;border-radius:14px;{ring}">'
    robot = ("<span style='position:absolute;top:-10px;right:-10px;font-size:22px'>🤖</span>"
             if model else "")
    badge = f"<div style='font-size:20px;line-height:1'>{grade_icon}</div>" if grade_icon else ""
    return (f"<div style='text-align:center'>"
            f"<div style='position:relative;display:inline-block'>{img}{robot}</div>{badge}</div>")


# top-of-page link to the explainer (hidden when already on it)
if (st.session_state.get("nav_radio") != "❓ How It Works"
        and st.session_state.get("_goto") != "❓ How It Works"):
    if st.button("❓ HOW THE PREDICTOR WORKS", type="secondary"):
        st.session_state["_goto"] = "❓ How It Works"
        st.rerun()

# (loading overlay removed — app is fast enough post-optimization)

games = dl.load_games()

# visible warning if the cloud DB isn't wired (secrets missing/misconfigured)
if not db._turso_cfg()[0]:
    st.warning("⚠️ Not connected to the shared database (Turso secrets missing) — "
               "running on a temporary local DB. Logins and journals will NOT persist. "
               "Admin: check the secrets configuration.")

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

@st.cache_data(ttl=300)
def get_user_settings(username):
    return db.get_user(username)

@st.cache_data(ttl=3600)
def get_projections(team, opp, inj_items, team_line=None):
    """Memoized per-matchup projections (the heaviest per-rerun compute).
    inj_items: tuple(sorted(injuries.items())) for hashability."""
    return pm.project_game(player_stats, def_mults, team, opp,
                           injuries=dict(inj_items), team_line=team_line)

def team_inj_map(team):
    m = {r["name"]: r["status"]
         for r in (nv_injuries.get(team) or {}).get("rows", []) if r.get("status")}
    return tuple(sorted(m.items()))

# ---------------- sidebar ----------------
st.sidebar.header("Controls")
_badge = {"admin": "🛠️ admin", "paid": "⭐ pro"}.get(LEVEL, "free")
st.sidebar.markdown(f"👤 **{NAME}** · {_badge}")
authenticator.logout("🚪 Log out", "sidebar")
st.sidebar.caption("21+ · Entertainment & informational purposes only — not betting advice. "
                   "If gambling stops being fun: **1-800-GAMBLER**. See **📜 Terms**.")
season, week = dl.current_season_week(games)
season = st.sidebar.number_input("Season", 2020, 2030, max(2020, min(2030, season)))
weeks = sorted(games[(games["season"] == season) & (games["game_type"] == "REG")]["week"].unique())
week = st.sidebar.selectbox("Week", weeks, index=weeks.index(week) if week in weeks else 0)
KEY_FILE = os.path.join(dl.CACHE, "odds_api_key.txt")
try:
    with open(KEY_FILE) as _f:
        saved_key = _f.read().strip()
except Exception:
    saved_key = ""
try:
    saved_key = st.secrets.get("ODDS_API_KEY", saved_key)  # house key on cloud
except Exception:
    pass
api_key = saved_key
if IS_ADMIN:
    api_key = st.sidebar.text_input("The Odds API key (optional)", value=saved_key, type="password",
                                    help="Free key at the-odds-api.com -> multi-book lines + line shopping")
    if api_key and api_key.strip() != saved_key:
        try:
            fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as _f:
                _f.write(api_key.strip())
            st.sidebar.success("Key saved to disk — persists across restarts")
        except Exception:
            pass
try:
    props_api_key = st.secrets.get("ODDS_API_KEY_PROPS", "") or api_key  # dedicated props quota pool
except Exception:
    props_api_key = api_key
def _lines_updated_at():
    import glob as _g
    fs = _g.glob(os.path.join(dl.CACHE, "odds_api.json")) + _g.glob(os.path.join(dl.CACHE, "espn_*.json"))
    return max((os.path.getmtime(f) for f in fs), default=None)


@st.cache_data(ttl=900, show_spinner=False)
def _board_rows(season, week):
    """Week-at-a-glance board: model vs market for every game (15-min cache)."""
    wk = games[(games["season"] == season) & (games["game_type"] == "REG") &
               (games["week"] == week)].sort_values(["gameday", "gametime"])
    ts = _lines_updated_at()
    updated = pd.Timestamp.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"
    rows = []
    for _, g in wk.iterrows():
        away, home = g["away_team"], g["home_team"]
        wind_mph = None
        if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
            wind_mph, _ = wx.wind_for_game(g)
        pred = pr.predict_game(g, elo, books_by_abbr.get((away, home)), espn_odds.get((away, home)),
                               nv_injuries, wind_mph=wind_mph)
        ms, mk = pred.get("model_spread"), pred.get("market_spread")
        edge = pred.get("edge_pts")
        mt, kt = pred.get("model_total"), pred.get("market_total")
        rows.append({
            "Away": logo_url(away),
            "Home": logo_url(home),
            "Game": f"{away} @ {home}",
            "Model Line": fmt_spread(ms, home, away) if ms is not None else "—",
            "Market Line": fmt_spread(mk, home, away) if mk is not None else "—",
            "Edge": (f"{abs(edge):.1f} {home if edge > 0 else away}{' ★' if abs(edge) >= 1.5 else ''}"
                     if edge is not None else "—"),
            "Model Total": round(float(mt), 1) if mt is not None else None,
            "Market Total": round(float(kt), 1) if kt is not None else None,
            "Edge Total": round(float(mt - kt), 1) if mt is not None and kt is not None else None,
            "Updated": updated,
        })
    return rows


if st.sidebar.button("🔄 Refresh live data",
                     help="Refreshes spreads, totals, injuries & news. Prop lines use the "
                          "24h daily cache — refresh those per game on the Props tab."):
    import glob
    import os
    for f in glob.glob(os.path.join(dl.CACHE, "espn_*.json")) + glob.glob(os.path.join(dl.CACHE, "odds_api.json")):
        os.remove(f)
    _board_rows.clear()
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
    if IS_ADMIN:
        st.sidebar.warning(f"ESPN odds unavailable: {e}")

books_by_abbr = {}
odds_err = None
odds_source = None
_sgo_key = dl.sgo_api_key()
if _sgo_key or api_key:
    try:
        if _sgo_key:  # SportsGameOdds preferred; The Odds API is the fallback
            raw = dl.sgo_lines(_sgo_key)
            odds_source = "SportsGameOdds"
        else:
            raw = dl.odds_api_lines(api_key)
            odds_source = "The Odds API"
        for (away_name, home_name), books in raw.items():
            key = (dl.TEAM_NAME_TO_ABBR.get(away_name), dl.TEAM_NAME_TO_ABBR.get(home_name))
            if all(key):
                books_by_abbr[key] = books
    except Exception as e:
        odds_err = str(e)
if odds_err and IS_ADMIN:
    st.sidebar.error(f"Odds ({odds_source or 'no key'}): {odds_err}")
elif not books_by_abbr and (_sgo_key or api_key) and IS_ADMIN:
    st.sidebar.info(f"{odds_source}: no NFL markets on the board right now.")

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
views = (["Games", "🔴 Live", "📒 Bet Journal", "📈 Track Record", "🏆 Pick'em", "📰 News", "🏅 Standings",
          "📊 Power Rankings", "❓ How It Works", "📜 Terms", "⚙️ Settings"] + (["👥 Users"] if IS_ADMIN else []))
_qp = st.query_params.get("page")
if _qp:  # deep-link support, e.g. ?page=journal from the bet-slip success link
    del st.query_params["page"]
    if _qp == "journal":
        st.session_state["_goto"] = "📒 Bet Journal"
if "_goto" in st.session_state:
    st.session_state["nav_radio"] = st.session_state.pop("_goto")
page = st.sidebar.radio("View", views, key="nav_radio")

# ---------------- bet journal page ----------------
def journal_page():
    st.header("📒 Bet Journal + CLV Tracker")
    st.caption(f"Private journal of **{NAME}** — only you can see this.")
    bets = journal.settle(journal.load_bets(USER), games, USER)
    s = journal.summary(bets)
    parlays = db.settle_parlays(games, USER)
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
    me_u = get_user_settings(USER) or {}
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
            db.update_bankroll(USER, br_in, un_in)
            get_user_settings.clear()
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
                db.save_parlay(USER, slip, float(comb), float(stake), book, "parlay")
                st.session_state["slip"] = []
                st.success("Parlay saved — legs grade automatically as games finish.")
                st.rerun()
            if b2.button("💾 Save as round robin (manual result)", disabled=len(slip) < 3,
                         help="One ticket, total stake, you enter the result when it settles"):
                db.save_parlay(USER, slip, None, float(stake), book, "round_robin")
                st.session_state["slip"] = []
                st.success("Round robin saved — enter the result below when it settles.")
                st.rerun()

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
                "stake": stake, "book": book}, USER)
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
            journal.delete_bet(del_id, USER)
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

if page == "📒 Bet Journal":
    if not gate("journal"):
        st.header("📒 Bet Journal + CLV Tracker")
        paywall("The Bet Journal + CLV Tracker")
        st.stop()
    journal_page()
    st.stop()

# ---------------- live page ----------------
def _live_body(season, week):
    live = dl.espn_live_scores(season, week)
    if not live:
        st.info("Live scores unavailable right now (ESPN may be rate-limiting). Try again shortly.")
        return
    bets = journal.load_bets(USER)
    pending = bets[bets["status"] == "pending"] if not bets.empty else bets
    wk_picks = db.load_pickem_week(season, week)
    any_live = False
    for ev in live:
        state = ev["state"]
        if state == "in":
            any_live = True
            badge = f"🟢 LIVE Q{ev['period']} {ev['clock']}"
        elif state == "post":
            badge = "✅ Final"
        else:
            badge = f"⏰ {ev['detail'] or 'upcoming'}"
        st.markdown(f"{matchup_md(ev['away'], ev['home'], 22)} — {badge}"
                    + (f"   **{ev['a_score']} – {ev['h_score']}**" if state != "pre" else ""),
                    unsafe_allow_html=True)
        margin = ev["h_score"] - ev["a_score"]
        notes = []
        if not pending.empty:
            for _, b in pending[pending["game"] == ev["label"]].iterrows():
                sel, line = str(b["selection"]), float(b["line"] or 0)
                if state == "pre":
                    notes.append(f"🎟️ your bet: {sel} {line:+g}")
                else:
                    tm = margin if sel == ev["home"] else -margin
                    if b["bet_type"] in ("over", "under"):
                        tot = ev["a_score"] + ev["h_score"]
                        diff = tot - line if b["bet_type"] == "over" else line - tot
                    else:
                        diff = tm + line
                    status = f"✅ by {diff:.0f}" if diff > 0 else (f"❌ by {-diff:.0f}" if diff < 0 else "➖ push")
                    notes.append(f"🎟️ {sel} {line:+g} {b['bet_type']}: {status}")
        if not wk_picks.empty:
            for _, pk in wk_picks[wk_picks["game"] == ev["label"]].iterrows():
                if state != "pre":
                    tm = margin if pk["pick"] == ev["home"] else -margin
                    diff = tm + (pk["line"] or 0)
                    status = "✅" if diff > 0 else ("❌" if diff < 0 else "➖")
                    notes.append(f"🏆 {pk['user']}: {pk['pick']} {pk['line']:+g} {status}")
                else:
                    notes.append(f"🏆 {pk['user']}: {pk['pick']} {pk['line']:+g}")
        if notes:
            st.caption("  •  ".join(notes))
    if not any_live and all(ev["state"] == "pre" for ev in live):
        st.caption("No games in progress — this page lights up at kickoff. Auto-refreshes every 60s.")


def live_page():
    st.header(f"🔴 Live — Week {week}")
    if hasattr(st, "fragment"):
        @st.fragment(run_every=60)
        def _frag():
            _live_body(season, week)
        _frag()
    else:
        _live_body(season, week)
        if st.button("🔄 Refresh"):
            st.rerun()

if page == "🔴 Live":
    live_page()
    st.stop()

# ---------------- pick'em page ----------------
def _kickoff_passed(g):
    """Pick lock for this game: 5 minutes before kickoff (mirrors db.PICK_LOCK)."""
    try:
        if pd.isna(g["gameday"]):
            return False
        gt = str(g.get("gametime", "13:00"))
        hh, mm = int(gt.split(":")[0]), int(gt.split(":")[1])
        return (pd.Timestamp.now()
                > g["gameday"] + pd.Timedelta(hours=hh, minutes=mm) - pd.Timedelta(minutes=5))
    except Exception:
        return False


def pickem_page():
    st.header("🏆 Weekly Pick'em")
    st.caption("Up to **5 games** against the spread, every week. **Change picks freely until "
               "5 minutes before each kickoff** — then they lock. Tap a logo to pick, tap it "
               "again to remove. Your line is whatever's current at the moment you make "
               "(or change) a pick.")

    # 🤖 model picks — public immediately (transparency over gamesmanship; tailing is fine)
    st.subheader(f"🤖 Model picks — Week {week}")
    model_picks = db.load_pickem("model", season, week)
    if model_picks.empty:
        st.info("Model's picks drop with the Monday 8 AM brief — it plays its top-5 edge games, "
                "at the lines posted when it enters.")
    else:
        GRADE_ICON = {"won": "✅ won", "lost": "❌ lost", "push": "➖ push", "pending": "⏳ pending"}
        show = pd.DataFrame({
            "Pick": model_picks["pick"].map(logo_url),  # logo IS the pick
            "Game": model_picks["game"],
            "Line": model_picks["line"].apply(lambda v: f"{float(v):+g}" if pd.notna(v) else "-"),
            "Result": model_picks["grade"].map(lambda g: GRADE_ICON.get(g, g)),
        })
        st.dataframe(show,
                     column_config={"Pick": st.column_config.ImageColumn("Pick", width="small")},
                     hide_index=True, width="stretch")
        made_raw = model_picks["created_at"].dropna().max()
        if made_raw:
            ts = pd.Timestamp(made_raw)
            made = (f"{ts:%a} {ts:%b} {ts.day}, "
                    f"{ts.hour % 12 or 12}:{ts:%M} {'AM' if ts.hour < 12 else 'PM'}")
            st.caption(f"🕐 Picks made **{made}** — locked at the lines posted at that moment.")
        mrec = next((r for r in db.pickem_leaderboard(season) if r["user"] == "model"), None)
        if mrec:
            st.markdown(f"**Model pick'em record:** {mrec['record']} "
                        f"({mrec['win_pct']*100:.0f}%)")
        st.caption("⚠️ **PLEASE NOTE:** The model is **required to pick 5 games every week** in "
                   "pick'em — those are the rules of the game, same as you. On the 📈 **Track "
                   "Record** page it plays by its own discipline: it only logs picks where its "
                   "edge vs the market is **2+ points**, graded at the closing line. Pick'em "
                   "record = the model playing your game. Track Record = the model's real bets.")
    for w in range(1, week + 1):
        db.grade_pickem(games, season, w)

    mine = db.load_pickem(USER, season, week)
    picked = dict(zip(mine["game"], mine["pick"])) if not mine.empty else {}
    line_by_game = dict(zip(mine["game"], mine["line"])) if not mine.empty else {}
    grade_by_game = dict(zip(mine["game"], mine["grade"])) if not mine.empty else {}

    st.markdown("""<style>
.stElementContainer:has(.sticky-picks) { position: sticky; top: 2.9rem; z-index: 999;
  background: rgba(14,17,23,0.97); border-bottom: 1px solid #2a2f3a; }
.sticky-picks { padding: 0.45rem 0 0.35rem; font-size: 1.3rem; font-weight: 700; }
</style>""", unsafe_allow_html=True)
    st.markdown(f"<div class='sticky-picks'>🏆 Week {week} — your picks "
                f"(<span style='color:#7cffb2'>{len(picked)}/5</span>)</div>",
                unsafe_allow_html=True)
    model_side = (dict(zip(model_picks["game"], model_picks["pick"]))
                  if not model_picks.empty else {})
    GRADE_MARK = {"won": "✅", "lost": "❌", "push": "➖"}
    for _, g in week_games.iterrows():
        away, home = g["away_team"], g["home_team"]
        label = f"{away} @ {home}"
        mside = model_side.get(label)
        sp = g["spread_line"]
        locked = _kickoff_passed(g)
        my = picked.get(label)
        grade = grade_by_game.get(label)
        gicon = GRADE_MARK.get(grade) if my and grade != "pending" else None
        day = g["gameday"].strftime("%a %b %d") if pd.notna(g["gameday"]) else ""
        ca, cm, ch = st.columns([2, 1, 2])
        ca.markdown(pick_logo(away, my == away, gicon if my == away else None,
                              model=mside == away), unsafe_allow_html=True)
        ch.markdown(pick_logo(home, my == home, gicon if my == home else None,
                              model=mside == home), unsafe_allow_html=True)
        if pd.notna(sp):
            fav = sp if sp < 0 else -sp  # favorite's line, always negative
            lt = "PK" if sp == 0 else f"{fav:+.1f}"
        else:
            lt = "—"
        cm.markdown(f"<div style='text-align:center;padding-top:14px'>"
                    f"<span style='font-size:24px;font-weight:700'>{lt}</span><br>"
                    f"<span style='color:#888'>@</span><br>"
                    f"<small style='color:#888'>{day} {g.get('gametime', '')} ET"
                    f"{' 🔒' if locked else ''}</small></div>", unsafe_allow_html=True)
        if not locked and pd.notna(sp):
            full = len(picked) >= 5 and label not in picked
            if ca.button(f"{away}", key=f"pk_a_{label}",
                         type="primary" if my == away else "secondary",
                         use_container_width=True):
                if my == away:
                    db.delete_pickem(USER, season, week, label)
                    st.rerun()
                elif full:
                    st.warning("You're at 5/5 — tap one of your glowing picks to remove it first.")
                else:
                    db.save_pickem(USER, season, week, label, away, float(sp))
                    st.rerun()
            if ch.button(f"{home}", key=f"pk_h_{label}",
                         type="primary" if my == home else "secondary",
                         use_container_width=True):
                if my == home:
                    db.delete_pickem(USER, season, week, label)
                    st.rerun()
                elif full:
                    st.warning("You're at 5/5 — tap one of your glowing picks to remove it first.")
                else:
                    db.save_pickem(USER, season, week, label, home, float(-sp))
                    st.rerun()

    st.subheader("🏆 Leaderboard")
    lb = db.pickem_leaderboard(season)
    if lb:
        st.dataframe(pd.DataFrame([{"Player": r["user"], "Record": r["record"],
                                    "Win %": f"{r['win_pct']*100:.0f}%"} for r in lb]),
                     hide_index=True, width="stretch")
    else:
        st.info("No graded picks yet this season — standings appear after Week 1.")

    wk_all = db.load_pickem_week(season, week)
    if not wk_all.empty:
        locked_games = {f"{g['away_team']} @ {g['home_team']}"
                        for _, g in week_games.iterrows() if _kickoff_passed(g)}
        vis = wk_all[wk_all["game"].isin(locked_games)]
        if not vis.empty:
            st.subheader("Everyone's picks (locked games)")
            vis = vis.rename(columns={"user": "Player", "game": "Game", "pick": "Pick",
                                      "line": "Line", "grade": "Result"})
            vis["Pick"] = vis["Pick"].map(logo_url)  # logo IS the pick
            st.dataframe(vis, column_config={"Pick": st.column_config.ImageColumn("Pick", width="small")},
                         hide_index=True, width="stretch")

if page == "🏆 Pick'em":
    pickem_page()
    st.stop()

# ---------------- news page ----------------
@st.cache_data(ttl=900)
def get_news():
    return dl.merged_news()


def _ago(iso):
    try:
        t = pd.Timestamp(iso)
        if t.tzinfo is not None:
            t = t.tz_convert(None)
        d = pd.Timestamp.now() - t
        h = d.total_seconds() / 3600
        return f"{int(d.total_seconds()//60)}m ago" if h < 1 else (f"{int(h)}h ago" if h < 48 else t.strftime("%b %d"))
    except Exception:
        return ""


def news_page():
    st.header("📰 NFL News")
    view = st.radio("Feed", ["All news", "🏥 Injuries & roster moves"], horizontal=True)
    items = get_news()
    if view != "All news":
        items = [i for i in items if dl.is_injury_news(i)]
    if not items:
        st.info("News feed unavailable right now — try again in a few minutes.")
        return
    # top stories with images as cards
    with_img = [i for i in items if i.get("img")]
    top = with_img[:3]
    if top:
        cols = st.columns(len(top))
        for col, it in zip(cols, top):
            with col:
                st.image(it["img"], width="stretch")
                badge = "🏥 " if dl.is_injury_news(it) else ""
                title = f"[{it['title']}]({it['link']})" if it.get("link") else it["title"]
                st.markdown(f"{badge}**{title}**")
                st.caption(f"{it['source']} · {_ago(it.get('published',''))}")
        top_keys = {" ".join(i["title"].lower().split())[:80] for i in top}
        items = [i for i in items if " ".join(i["title"].lower().split())[:80] not in top_keys]
        st.divider()
    st.caption(f"{len(items)} stories • ESPN + CBS • 🏥 = moves lines")
    for it in items:
        badge = "🏥 " if dl.is_injury_news(it) else ""
        title = f"[{it['title']}]({it['link']})" if it.get("link") else it["title"]
        st.markdown(f"{badge}**{title}**  \n<small>{it['source']} · {_ago(it.get('published',''))}</small>",
                    unsafe_allow_html=True)
        if it.get("desc"):
            st.caption(it["desc"][:220])

if page == "📰 News":
    news_page()
    st.stop()

# ---------------- standings page ----------------
def standings_page():
    st.header("🏅 Standings")
    played = sorted(games[games["result"].notna()]["season"].unique())
    default = int(played[-1]) if len(played) else season
    yr = st.selectbox("Season", sorted(set(played + [season])), index=len(set(played + [season])) - 1)
    stats = an.team_stats(games, yr)
    t1, t2 = st.tabs(["🏅 Standings", "🎯 ATS Standings"])
    with t1:
        if yr == default and default != season:
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

if page == "🏅 Standings":
    standings_page()
    st.stop()

# ---------------- power rankings page ----------------
@st.cache_data(ttl=3600)
def _rankings_data(season):
    cur = pr.Elo(games).ratings
    done = games[(games["season"] == season) & games["result"].notna()
                 & games["game_type"].isin(["REG", "POST"])]
    prev = {}
    if not done.empty:
        lw = int(done["week"].max())
        prev = pr.Elo(games[~((games["season"] == season) & (games["week"] == lw))]).ratings
    rows = []
    for t, r in sorted(cur.items(), key=lambda kv: -kv[1]):
        if t not in TEAM_SET:
            continue  # defunct franchises (STL/SD/OAK) — in history, not in current rankings
        d = r - prev.get(t, r)
        rows.append({"#": len(rows) + 1, "Team": t, "Logo": logo_url(t), "Rating": round(r),
                     "Δ wk": f"{'↑' if d > 0.5 else ('↓' if d < -0.5 else '–')} {d:+.0f}" if prev else "–"})
    return rows


def rankings_page():
    st.header("📊 Elo Power Rankings")
    st.caption("Our model's power ratings — updated after every game. "
               "Gap between two ratings predicts the winner (+100 pts ≈ 64% win chance). "
               "More: ❓ How It Works.")
    rows = _rankings_data(season)
    half = (len(rows) + 1) // 2
    c1, c2 = st.columns(2)
    c1.dataframe(pd.DataFrame(rows[:half]), column_config=LOGO_CFG, hide_index=True, width="stretch")
    c2.dataframe(pd.DataFrame(rows[half:]), column_config=LOGO_CFG, hide_index=True, width="stretch")

if page == "📊 Power Rankings":
    rankings_page()
    st.stop()

# ---------------- how-it-works page ----------------
def help_page():
    st.header("❓ How the Predictor Works")
    st.caption("The short version of what every number on the Predictor tab means.")

    st.subheader("🤖 Model line")
    st.markdown("The model's **fair spread** for the game. It's built from three parts: "
                "**85%** the de-vigged consensus of every sportsbook, **15%** our Elo ratings, "
                "plus small backtest-proven adjustments (injuries, rest). "
                "*Example: 'SEA -3.4' means the model thinks Seattle should be favored by 3.4 points.*")

    st.subheader("📚 Market")
    st.markdown("The number the **sportsbooks are actually dealing** right now. The arrow note "
                "beneath tells you the source: **'9 book(s)'** = the median of 9 live books; "
                "**'nflverse current line'** = the reference line when live books aren't loaded. "
                "The market is the toughest opponent in sports betting — the model never fades it without a reason.")

    st.subheader("⚡ Edge")
    st.markdown("**Model minus market, in points**, for the team named. "
                "**'within noise'** = the gap is under 1.5 points — ordinary disagreement, ignore it. "
                "**'value'** = the gap is 1.5+ — the model genuinely disagrees with the books. "
                "*Example: 'Edge 2.3 CAR' = the model likes Carolina 2.3 points more than the market does.*")

    st.subheader("🎚️ Model total")
    st.markdown("The model's fair **combined-points** line: the market total plus validated "
                "adjustments (wind, tight spreads, early season, referee). The note beneath — "
                "*'mkt 44.0 → UNDER 1.0'* — means the model's number is 1.0 lower than the market's, "
                "so the lean is UNDER by 1.0 point.")

    st.subheader("💰 When is a bet suggested?")
    st.markdown("""
- **Only when EV is positive** — the edge beats the book's cut (the vig). That's the whole game.
- **≥1.5 pts** → the Edge card flips to **'value'**
- **≥2 pts** → logged as an official model pick on the 📈 Track Record page and graded at the closing line
- **Stake** → the ¼-Kelly column (a fraction of your bankroll)
- **Everything else → NO BET.** Most games are no-bets. That's discipline, not a bug.
""")

    st.subheader("📐 What is Elo, anyway?")
    st.markdown("""
Elo is a **power rating** — one number per team. The whole idea: **the gap between two
teams' ratings predicts who wins.** A team rated 100 points higher wins about 64% of the
time; 200 points higher, about 76%. Ratings move after every game: win and you take points
from your opponent — beat a *good* team and you take more, lose to a *bad* team and you lose more.

**The actual math (one line each, promise):**

- **Win chance:** `1 / (1 + 10^(-(rating gap + home bonus)/400))`
  *Example: Seattle (1703) at home vs a 1550 team → gap 153 + 48 home bonus = 201 → ~76% win chance.*
- **Update after the game:** `new rating = old + 20 × (actual result − expected)`, scaled by margin
  *Seattle wins as a 76% favorite: +20 × (1 − 0.76) ≈ +5 points. Barely moves — it was expected.
  If they'd LOST: −20 × 0.76 ≈ −15. Upsets move ratings; chalk doesn't.*

**Our version, specifically:** home field is worth ~48 Elo points (≈2 points of spread),
winning big counts more (with a dampener so running it up doesn't), and every offseason
ratings pull one-third of the way back to average (1500) — rosters change, so last year
only counts so much.

**The honest part:** Elo alone picked 51.1% against the closing line over 5 seasons — below
breakeven. That's exactly why it's only 15% of our model: a smart prior, not the prediction.
""")

    st.subheader("📺 45-second video version")
    vcol, _ = st.columns([3, 2])
    with vcol:
        st.video("https://www.youtube.com/watch?v=VXGviaMi03E")

    st.subheader("🗺️ The diagrams")
    GH = "https://jriyasat.github.io/nflapp"
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"[![Data map]({GH}/data-map-preview.png)]({GH}/data-map.html)")
        st.caption("⤴ Data map — click to open the full interactive version")
    with d2:
        st.markdown(f"[![Model pipeline]({GH}/model-diagram-preview.png)]({GH}/model-diagram.html)")
        st.caption("⤴ Model pipeline — click to open the full interactive version")

    st.caption("Want the deep dive with backtest numbers? Click the ❓ next to 'Model line' on any Predictor tab.")

if page == "❓ How It Works":
    help_page()
    st.stop()

# ---------------- terms / disclaimer page ----------------
TERMS_MD = """
**Last updated: August 2026**

**1. What this is.** NFL Edge Finder ("the Service") is an analytics and entertainment
tool that displays publicly available sports data, statistical models, and historical
backtest results. It is **not** a sportsbook: we do not accept, place, or settle wagers
of any kind.

**2. Entertainment & informational purposes only.** Nothing in the Service — predictions,
"edges," projections, suggested stakes, or any other content — constitutes financial,
investment, or legal advice, or a recommendation to place any bet. Sports outcomes are
inherently uncertain; **past performance (including backtests) does not guarantee future
results.** You can lose money. Any betting decision you make is yours alone.

**3. 21+ only.** The Service is intended for users aged 21 or older. By using it you
represent that you are 21+ and that sports betting is legal in your jurisdiction. You are
solely responsible for complying with the laws where you live.

**4. No warranty.** The Service is provided **"as is" and "as available,"** with no
warranties of any kind, express or implied — including accuracy, completeness, uptime,
or fitness for a particular purpose. Data feeds (odds, injuries, weather) come from third
parties and may be delayed, wrong, or unavailable.

**5. Limitation of liability.** To the maximum extent permitted by law, the Service and
its operator(s) are not liable for any losses — including gambling losses, lost profits,
or indirect/consequential damages — arising from use of, or inability to use, the Service.
If you are a paying subscriber, total liability is capped at the amount you paid in the
3 months before the claim.

**6. Responsible gambling.** Bet only what you can afford to lose. If gambling stops
being fun, help is available 24/7: **call or text 1-800-GAMBLER** (US National Problem
Gambling Helpline) or visit ncpgambling.org.

**7. Accounts.** You are responsible for keeping your password confidential and for
activity under your account. We may suspend accounts that abuse the Service (sharing
logins, scraping, reselling access).

**8. Changes.** We may update these terms; continued use after changes means acceptance.
The "last updated" date above always reflects the current version.

**9. Contact.** Questions about these terms: jeff.riyasat@gmail.com.
"""


def terms_page():
    st.header("📜 Terms of Use & Disclaimer")
    st.markdown(TERMS_MD)


if page == "📜 Terms":
    terms_page()
    st.stop()

# ---------------- admin: user management page ----------------
def users_page():
    st.header("👥 User Management")
    with st.expander("➕ Add user", expanded=True):
        c1, c2 = st.columns(2)
        fname = c1.text_input("First name", key="new_fname")
        email = c2.text_input("Email", key="new_email")
        level = st.selectbox("Level", list(db.LEVELS), index=1, key="new_level",
                             help="user = free tier · paid = full features · admin = full + this page")
        if st.button("Create user"):
            uname = fname.strip().lower()
            if not uname:
                st.error("First name is required.")
            elif uname in [u["username"] for u in db.list_users()]:
                st.error(f"'{uname}' already exists.")
            else:
                pw = "edge-" + secrets.token_urlsafe(5)
                db.add_user(uname, fname.strip().title(), email.strip(), level,
                            bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
                st.success(f"✅ User **{uname}** created. Temp password — share it now, "
                           f"it won't be shown again:")
                st.code(pw)
    st.subheader("Accounts")
    _lvl_label = {"user": "free", "paid": "⭐ pro", "admin": "🛠️ admin"}
    for u in db.list_users():
        cols = st.columns([2, 3, 1.8, 2, 1.5])
        cols[0].markdown(f"**{u['name']}** (`{u['username']}`)")
        cols[1].markdown(u["email"] or "—")
        if u["username"] != USER:
            new_lvl = cols[2].selectbox("Level", list(db.LEVELS), key=f"lvl_{u['username']}",
                                        index=list(db.LEVELS).index(u["level"]),
                                        format_func=lambda l: _lvl_label[l],
                                        label_visibility="collapsed")
            if new_lvl != u["level"]:
                if u["level"] == "admin" and db.admin_count() <= 1:
                    st.error("Can't demote the last admin.")
                else:
                    db.set_level(u["username"], new_lvl)
                    st.success(f"**{u['username']}** → {_lvl_label[new_lvl]}")
                    st.rerun()
        else:
            cols[2].markdown(_lvl_label[u["level"]])
        if u["username"] != USER:
            if cols[3].button("🔑 Reset password", key=f"rst_{u['username']}"):
                pw = "edge-" + secrets.token_urlsafe(5)
                db.set_password(u["username"],
                                bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
                st.success(f"New temp password for **{u['username']}** (shown once):")
                st.code(pw)
            if cols[4].button("🗑️", key=f"del_{u['username']}", help="Delete user"):
                db.delete_user(u["username"])
                st.rerun()
        else:
            cols[3].caption("(that's you)")

    st.subheader("📣 Email all users")
    if not emailer.configured():
        st.caption("⚠️ Email not configured yet — needs Gmail or Resend credentials "
                   "(see docs/BUSINESS.md §email).")
    else:
        st.caption(f"Transport: **{emailer.transport()}**"
                   + (" — upgrade to Resend for better deliverability at scale "
                      "(docs/BUSINESS.md §email)" if emailer.transport() == "gmail" else ""))
        with st.form("broadcast_form"):
            b_subj = st.text_input("Subject")
            b_body = st.text_area("Message (plain text)")
            if st.form_submit_button("Send to all users with emails"):
                recips = [u["email"] for u in db.list_users() if u["email"]]
                if not (b_subj.strip() and b_body.strip()):
                    st.error("Subject and message are both required.")
                elif not recips:
                    st.warning("No users have email addresses saved.")
                else:
                    sent, errors = emailer.broadcast(
                        recips, b_subj.strip(),
                        emailer.brief_html(b_body.strip(),
                                           footer_note="Announcement from NFL Edge Finder."))
                    if errors:
                        st.warning(f"Sent to {sent}/{len(recips)}. Errors: {'; '.join(errors)}")
                    else:
                        st.success(f"✅ Sent to all {sent} users.")

if page == "👥 Users":
    if not IS_ADMIN:
        st.error("Admins only.")
        st.stop()
    users_page()
    st.stop()

# ---------------- settings page ----------------
def settings_page():
    st.header("⚙️ Settings")
    me = db.get_user(USER)

    st.subheader("🔑 Change password")
    with st.form("pw_form"):
        cur = st.text_input("Current password", type="password")
        new1 = st.text_input("New password", type="password")
        new2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Update password"):
            if not bcrypt.checkpw(cur.encode(), me["pw_hash"].encode()):
                st.error("Current password is wrong.")
            elif len(new1) < 6:
                st.error("New password must be at least 6 characters.")
            elif new1 != new2:
                st.error("New passwords don't match.")
            else:
                db.set_password(USER, bcrypt.hashpw(new1.encode(), bcrypt.gensalt()).decode())
                st.success("Password updated ✅")

    st.subheader("🔔 Notifications")
    st.caption("The morning brief only sends on days something changed — no news, no message.")
    em_col, tg_col = st.columns(2)
    with em_col:
        st.markdown("**📧 Daily email brief**")
        new_email = st.text_input("Your email", value=me["email"] or "", key="set_email")
        if st.button("Save email"):
            db.update_email(USER, new_email.strip())
            st.success("Email saved ✅")
            st.rerun()
        if gate("email_brief"):
            email_on = st.checkbox("Send me the daily email brief",
                                   value=bool(me["email_enabled"]),
                                   disabled=not (me["email"] or new_email.strip()))
            if not (me["email"] or new_email.strip()):
                st.caption("Add your email above to enable this.")
        else:
            email_on = False
            st.caption("🔒 The daily email brief is a **Pro** feature — "
                       "contact us to upgrade.")
    with tg_col:
        st.markdown("**📱 Daily Telegram brief**")
        if me["telegram_chat_id"]:
            st.success("Telegram linked ✅")
        else:
            st.info("To link: open Telegram and send ANY message to the bot you chat with Jeff's agent on, "
                    "then tell Jeff — he'll confirm the link on his side.")
        tg_on = st.checkbox("Send me the daily Telegram brief",
                            value=bool(me["telegram_enabled"]),
                            disabled=not me["telegram_chat_id"])
        if not me["telegram_chat_id"]:
            st.caption("Available once your Telegram is linked.")
    if st.button("💾 Save notification preferences"):
        db.update_prefs(USER, email_enabled=email_on, telegram_enabled=tg_on)
        st.success("Preferences saved ✅")
        st.rerun()

    st.subheader("🗑️ Delete account")
    st.warning("This deletes your account AND your private bet journal. Permanent.")
    confirm = st.text_input("Type DELETE to confirm", key="del_confirm")
    del_pw = st.text_input("Re-enter your password", type="password", key="del_pw")
    if st.button("Delete my account", disabled=(confirm != "DELETE" or not del_pw)):
        if IS_ADMIN and db.admin_count() <= 1:
            st.error("You're the last admin — promote someone else first, or the app locks everyone out.")
        elif not bcrypt.checkpw(del_pw.encode(), db.get_user(USER)["pw_hash"].encode()):
            st.error("Password doesn't match — account not deleted.")
        else:
            db.delete_user(USER)
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

if page == "⚙️ Settings":
    settings_page()
    st.stop()

# ---------------- track record page ----------------
def _pick_clv(p):
    """Closing line value: pts of line the model captured vs the close, in its favor.
    market_val_log is home-perspective; closing_line is team-perspective (set at grading)."""
    if p["grade"] not in ("won", "lost", "push"):
        return None
    try:
        if p["pick_type"] == "spread":
            away_team = str(p["game"]).split(" @ ")[0]
            log_line = float(p["market_val_log"])
            team_log = -log_line if p["side"] == away_team else log_line
            return team_log - float(p["closing_line"])
        sign = 1.0 if p["side"] == "over" else -1.0
        return sign * (float(p["closing_line"]) - float(p["market_val_log"]))
    except Exception:
        return None


def track_record_page():
    st.header("📈 Model Track Record")
    picks = tracker.grade_predictions(games)
    if not len(picks):
        st.info("No picks logged yet. The morning brief logs every |edge| ≥ 2 pt call the model "
                "makes (sides + totals) and grades them against the **closing line**.")
        return
    s = tracker.summary(picks)
    c = st.columns(5)
    c[0].metric("Sides (at close)", s["spread"]["record"],
                f"{s['spread']['win_pct']:.1f}%" if s["spread"]["win_pct"] is not None else "—")
    c[1].metric("Totals (at close)", s["total"]["record"],
                f"{s['total']['win_pct']:.1f}%" if s["total"]["win_pct"] is not None else "—")
    profit = s["spread"]["profit"] + s["total"]["profit"]
    c[2].metric("Profit (flat -110)", f"{profit:+.2f}u")
    c[3].metric("Graded picks", s["spread"]["n"] + s["total"]["n"])
    c[4].metric("Pending", s["pending"])
    # CLV vs closing line — the fast signal. Did the line the model locked (market_val_log,
    # converted to the pick's perspective) beat the number it closed at?
    clvs = []
    for _, p in picks[picks["grade"].isin(["won", "lost", "push"])].iterrows():
        if pd.isna(p["closing_line"]) or pd.isna(p["market_val_log"]):
            continue
        if p["pick_type"] == "spread":
            home_t = p["game"].split(" @ ")[1]
            taken = float(p["market_val_log"]) if p["side"] == home_t else -float(p["market_val_log"])
            clvs.append(taken - float(p["closing_line"]))
        else:
            taken = float(p["market_val_log"])
            clvs.append((float(p["closing_line"]) - taken) if p["side"] == "over"
                        else (taken - float(p["closing_line"])))
    if clvs:
        beat = sum(1 for v in clvs if v > 0)
        st.markdown(f"**📏 CLV vs close:** avg **{sum(clvs)/len(clvs):+.2f} pts** · "
                    f"beat the close **{beat/len(clvs)*100:.0f}%** ({beat}/{len(clvs)}) — "
                    f"the fast signal: positive avg + >52% beat-rate = real edge forming, "
                    f"readable weeks before win% is.")
    else:
        st.caption("📏 CLV vs the closing line appears once picks grade — it becomes "
                   "meaningful weeks before the win% above it is.")
    st.caption("Breakeven at -110 is 52.4%. Picks lock the morning an edge first hits 2+ pts "
               "(8 AM brief) at that morning's line — never edited after. "
               "Graded at the **closing** line — the honest number.")

    clv = picks.apply(_pick_clv, axis=1).dropna()
    if len(clv):
        cc = st.columns(2)
        cc[0].metric("📈 Avg CLV", f"{clv.mean():+.2f} pts")
        cc[1].metric("🎯 Beat the close", f"{(clv > 0).mean()*100:.0f}% "
                     f"({int((clv > 0).sum())}/{len(clv)})")
        st.caption("CLV = the line the model took vs where it closed, in the model's favor. "
                   "Positive = the model was ahead of the market. Beating the close >53% over "
                   "100+ picks is the strongest known signal of a real edge — and it becomes "
                   "meaningful in weeks, not seasons.")
    else:
        st.caption("CLV metrics appear once picks are graded — the fast signal: does the model "
                   "beat the closing line?")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("By edge size")
        rows = tracker.edge_buckets(picks)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("If bigger edges don't win more, the signal is noise. This table is the truth serum.")
        else:
            st.info("No graded picks yet.")
    with col2:
        st.subheader("Calibration")
        rows = tracker.calibration(picks)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("When the model says 56%, it should win ~56%.")
        else:
            st.info("No graded picks yet.")

    st.subheader("All picks")
    show = picks.copy()
    show["profit"] = show["profit"].apply(lambda v: f"{float(v):+.2f}" if pd.notna(v) and str(v) != "" else "…")
    show["closing_line"] = show["closing_line"].apply(lambda v: f"{float(v):+.1f}" if pd.notna(v) and str(v) != "" else "…")
    show["clv"] = picks.apply(_pick_clv, axis=1).apply(lambda v: f"{v:+.2f}" if pd.notna(v) else "…")
    show.insert(0, "Logo", show["side"].map(logo_url))
    st.dataframe(show[["Logo", "logged_at", "game", "pick_type", "side", "model_val",
                       "market_val_log", "edge_log", "closing_line", "clv", "grade", "profit"]].iloc[::-1],
                 column_config=LOGO_CFG, hide_index=True, width="stretch")

if page == "📈 Track Record":
    track_record_page()
    st.stop()

# ---------------- render helpers ----------------
def fmt_ml(v):
    return f"{v:+d}" if isinstance(v, (int, float)) else "-"

@st.cache_data(ttl=600, show_spinner=False)
def _line_history(game_label):
    """Line-movement history per game (Turso roundtrip — cache 10 min so open
    games don't each pay a network call on every rerun)."""
    return db.line_history(game_label)


def lines_block(g, away, home, espn_o, books):
    # model context — shared by the chart overlay and the pinned table row
    wind_mph = None
    if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
        wind_mph, _ = wx.wind_for_game(g)
    pred = pr.predict_game(g, elo, books=books, espn=espn_o,
                           injuries=nv_injuries, wind_mph=wind_mph)
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
    # pinned 🤖 MODEL row: model spread + total next to the market, ⚡ when |edge| >= 1.5
    edge = pred.get("edge_pts")
    badge = " ⚡ VALUE" if edge is not None and abs(edge) >= 1.5 else ""
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
            st.markdown(f"{team_md(team)} — official NFL report ({nv['label']})",
                        unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{
                "Player": r["name"], "Pos": r["position"], "Status": r["status"],
                "Injury": r["detail"], "Practice": r["practice"],
            } for r in nv["rows"]]), hide_index=True, width="stretch")
        else:
            rows = injuries.get(team, [])
            if rows:
                any_data = True
                st.markdown(f"{team_md(team)} — via ESPN", unsafe_allow_html=True)
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
        st.markdown(f"**Cover probability:** {team_md(home, 20)} {p*100:.0f}% / {team_md(away, 20)} {(1-p)*100:.0f}%",
                    unsafe_allow_html=True)
        st.progress(min(max(p, 0.0), 1.0))
        rows = []
        br = (get_user_settings(USER) or {}).get("bankroll")
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
PROJ_COLS = [("proj_pass", "Pass Yds"), ("proj_rush", "Rush Yds"),
             ("proj_rec_yds", "Rec Yds"), ("proj_rec", "Receptions")]

BOOK_NAMES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
              "caesars": "Caesars", "bovada": "Bovada", "mybookieag": "MyBookie",
              "betonlineag": "BetOnline", "williamhill_us": "Caesars", "espnbet": "ESPN BET",
              "betrivers": "BetRivers", "fanatics": "Fanatics", "hardrockbet": "Hard Rock"}


def _book_name(key):
    if not key:
        return "—"
    return BOOK_NAMES.get(key, key.replace("_", " ").title())

def props_tab(g, away, home):
    if player_stats is None:
        st.warning("Player stats feed unavailable right now.")
        return
    # team lines (negative = favored) for the v2 rushing game-script factor
    mkt = pr.consensus(books_by_abbr.get((away, home)))
    hs = mkt.get("home_spread")
    if hs is None and pd.notna(g.get("spread_line")):
        hs = -float(g["spread_line"])  # nflverse is away-perspective -> flip to home
    lines = st.session_state.get(f"props_{away}_{home}", {})
    if not lines and api_key:  # shared daily cache: show today's lines free, no button press
        cached, ts = dl.cached_event_props(ABBR_TO_NAME[away], ABBR_TO_NAME[home])
        if cached:
            lines = cached
            st.session_state[f"props_{away}_{home}"] = cached
            st.session_state[f"props_ts_{away}_{home}"] = ts
    for team, opp in ((away, home), (home, away)):
        st.markdown(f"{team_md(team)} (vs {team_md(opp, 20)})", unsafe_allow_html=True)
        tl = (-hs if team == away else hs) if hs is not None else None
        res = get_projections(team, opp, team_inj_map(team), tl)
        # 🧪 injury what-if simulator: pretend any player is OUT, watch volume reshuffle
        sim = st.multiselect(f"🧪 Simulate OUT ({team})",
                             [p["player"] for p in res["players"]],
                             key=f"sim_{away}_{home}_{team}",
                             placeholder="What-if: bench a player…")
        if sim:
            inj = dict(team_inj_map(team))
            for nm in sim:
                inj[nm] = "Out"
            res = get_projections(team, opp, tuple(sorted(inj.items())), tl)
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
                    hr = (pm.hit_rate(player_stats, p["player_id"], col, e["line"])
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
        if api_key and st.button("↻ Refresh prop lines", key=f"refreshprops_{away}_{home}",
                                 help="Fetch fresh lines for THIS game now (~4 API credits — "
                                      "admin unlimited, otherwise counts as your daily load)"):
            used = db.usage_today(USER, "prop_load")
            if not IS_ADMIN and used >= 1:
                st.error("Daily prop-line load used (1/day per user — protects the shared free "
                         "API quota). Resets at midnight. Admin loads are unlimited.")
            else:
                with st.spinner("Fetching fresh prop lines..."):
                    try:
                        dl.bust_event_props_cache(ABBR_TO_NAME[away], ABBR_TO_NAME[home])
                        fetched = dl.odds_api_event_props(props_api_key, ABBR_TO_NAME[away], ABBR_TO_NAME[home])
                        if not IS_ADMIN:
                            db.bump_usage(USER, "prop_load")
                        if fetched:
                            st.session_state[f"props_{away}_{home}"] = fetched
                            st.session_state[f"props_ts_{away}_{home}"] = pd.Timestamp.now().timestamp()
                            st.session_state.pop(f"props_none_{away}_{home}", None)
                            st.rerun()
                        else:
                            st.warning("No player props posted for this game yet — books usually hang "
                                       "them a few days before kickoff.")
                    except Exception as e:
                        st.error(f"Props fetch failed: {e}" if IS_ADMIN
                                 else "Props fetch failed right now — try again later.")
    elif api_key:
        if st.button("📡 Load live prop lines", key=f"loadprops_{away}_{home}",
                     help="Lines auto-load Mon & Sat; this fetches fresh now (~4 API credits — "
                          "admin unlimited, otherwise counts as your daily load)."):
            warm, _ = dl.cached_event_props(ABBR_TO_NAME[away], ABBR_TO_NAME[home])
            real_fetch = warm is None
            used = db.usage_today(USER, "prop_load")
            if real_fetch and not IS_ADMIN and used >= 1:
                st.error("Daily prop-line load used (1/day per user — protects the shared free "
                         "API quota). Resets at midnight. Admin loads are unlimited.")
            else:
                with st.spinner("Fetching props from The Odds API..." if real_fetch
                                else "Reading today's shared cache..."):
                    try:
                        fetched = dl.odds_api_event_props(props_api_key, ABBR_TO_NAME[away], ABBR_TO_NAME[home])
                        if real_fetch:
                            db.bump_usage(USER, "prop_load")
                        if fetched:
                            st.session_state[f"props_{away}_{home}"] = fetched
                            st.session_state[f"props_ts_{away}_{home}"] = pd.Timestamp.now().timestamp()
                            st.rerun()
                        else:
                            st.session_state[f"props_none_{away}_{home}"] = True
                            st.warning("No player props posted for this game yet — books usually hang "
                                       "them a few days before kickoff. Check back then.")
                    except Exception as e:
                        st.error(f"Props fetch failed: {e}" if IS_ADMIN
                                 else "Props fetch failed right now — try again later.")
        if st.session_state.get(f"props_none_{away}_{home}"):
            st.caption("Last check: props not on the board yet.")
    else:
        st.caption("Add your Odds API key in the sidebar to compare projections against live prop lines.")

# ---------------- SGP UI ----------------
def sgp_tab(g, away, home):
    lines = st.session_state.get(f"props_{away}_{home}", {})
    if not lines and api_key:  # shared daily cache (same as Props tab)
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
            "Combo boost": f"×{c['lift']:.2f} (n={c['n']})",
            "Both hit": f"{c['p_joint']*100:.0f}%",
            "Fair price": f"{c['fair_american']:+d}",
            "No-boost price": f"{c['naive_american']:+d}",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("**How to use:** Fair price includes the measured combo boost (2024-25, n=544 real games). "
               "Only bet the SGP if your book's price is *longer* than Fair — books adjust for "
               "correlation too, so compare before betting. Boost ≠ guaranteed edge.")

# ---------------- bet slip UI ----------------
def slip_tab(g, away, home):
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

# ---------------- week at a glance (all games: model vs market, sortable/downloadable) ----------------
st.subheader(f"📋 Week {week} at a Glance")
_board = _board_rows(int(season), int(week))
if _board:
    _bdf = pd.DataFrame(_board)

    def _board_style(df):
        """Green-highlight value cells: spread edge >=1.5 (⭐ rows) and |total edge| >=1.5."""
        HILITE = "background-color: #7cffb2; color: #000000; font-weight: 700"
        s = pd.DataFrame("", index=df.index, columns=df.columns)
        s.loc[df["Edge"].astype(str).str.contains("★", regex=False), "Edge"] = HILITE
        m = pd.to_numeric(df["Edge Total"], errors="coerce").abs() >= 1.5
        s.loc[m.fillna(False), "Edge Total"] = HILITE
        return s

    st.dataframe(_bdf.style.apply(_board_style, axis=None), column_config={
        "Away": st.column_config.ImageColumn("Away", width="small"),
        "Home": st.column_config.ImageColumn("Home", width="small"),
        "Model Total": st.column_config.NumberColumn("Model Total", format="%.1f"),
        "Market Total": st.column_config.NumberColumn("Market Total", format="%.1f"),
        "Edge Total": st.column_config.NumberColumn("Edge Total", format="%.1f")},
        hide_index=True, width="stretch")
    st.caption("**★ = spread value** — the model disagrees with the books by ≥1.5 pts; **no ★ on any game "
               "= no spread bet this week** · 🟩 green cell = bettable edge (≥1.5 pts) · **Edge Total** "
               "negative = model leans UNDER, positive = OVER · click a column header to sort · hover the "
               "table's top-right corner for search & CSV download.")

# ---------------- main loop (lazy: only open games render — huge rerun win) ----------------
open_set = st.session_state.setdefault("open_games", {0})


@st.fragment
def render_game(gi, g):
    away, home = g["away_team"], g["home_team"]
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

    tabs = st.tabs(["🎯 Predictor", "🎰 Props", "🧩 SGP", "📊 Lines", "📈 Form (last 3)", "⚔️ H2H (5y)", "🏥 Injuries", "🎟️ Slip"])
    with tabs[0]:
        predictor_tab(g, away, home)
    with tabs[1]:
        if gate("props"):
            props_tab(g, away, home)
        else:
            paywall("Player Props")
    with tabs[2]:
        if gate("sgp"):
            sgp_tab(g, away, home)
        else:
            paywall("The SGP correlation finder")
    with tabs[3]:
        lines_block(g, away, home, espn_odds.get((away, home)), books_by_abbr.get((away, home)))
    with tabs[4]:
        c1, c2 = st.columns(2)
        for col, team in ((c1, away), (c2, home)):
            col.markdown(team_md(team), unsafe_allow_html=True)
            df_team = form_df(team)
            if df_team is not None:
                col.dataframe(df_team, hide_index=True, width="stretch")
            else:
                col.info("No recent games found.")
    with tabs[5]:
        rows, summ = an.h2h(games, away, home, seasons=5)
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
        injuries_block(away, home)
    with tabs[7]:
        if gate("journal"):
            slip_tab(g, away, home)
        else:
            paywall("The bet slip (parlays + journal)")


for gi, (_, g) in enumerate(week_games.iterrows()):
    away, home = g["away_team"], g["home_team"]
    day = g["gameday"].strftime("%a %b %d") if pd.notna(g["gameday"]) else ""
    label = f"{away} @ {home}  •  {day} {g.get('gametime', '')} ET"
    is_open = gi in open_set
    hc1, hc2 = st.columns([11, 1])
    hc1.markdown(f"{matchup_md(away, home, 28)}"
                 f"  •  {day} {g.get('gametime', '')} ET", unsafe_allow_html=True)
    if hc2.button("▾" if is_open else "▸", key=f"tog_{gi}", help="open/close game"):
        st.session_state["open_games"] = open_set ^ {gi}
        st.rerun()
    if is_open:
        with st.container(border=True):
            render_game(gi, g)

st.caption("Historical lines: nflverse closing lines. Live: ESPN + The Odds API. For entertainment/research — bet responsibly.")
