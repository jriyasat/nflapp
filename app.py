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
import views.standings
import views.rankings
import views.news
import views.help
import views.users
import views.settings
import views.live
import views.journal
import views.pickem
import views.track_record
import views.sentiment_lab
import views.game_detail
week_games = None

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
_LEVEL_RANK = {"user": 0, "paid": 1, "admin": 2, "superadmin": 3}
FEATURE_GATES = {"props": "paid", "sgp": "paid", "journal": "paid", "email_brief": "paid", "experiment_lab": "superadmin"}

# ONE value threshold everywhere: ★ stars, green cells, ⚡ badges, Completed
# receipts = exactly the Track Record bar (tracker.EDGE_MIN). "★ = the model
# bets this." No second, looser number for users to reconcile.
VALUE_EDGE_MIN = 2.0


def gate(feature):
    return _LEVEL_RANK.get(LEVEL, 0) >= _LEVEL_RANK[FEATURE_GATES.get(feature, "admin")]


def paywall(feature):
    """Upgrade wall shown to free-tier users behind gated features."""
    st.info(f"🔒 **{feature}** is a **Pro** feature.")
st.set_page_config(page_title="NFL Edge Finder", page_icon="🏈", layout="wide")
st.markdown(
    "Pro unlocks: 🎰 **Player Props** (injury-aware projections vs live lines) · "
    "🧩 **SGP correlation finder** · 📒 **Bet Journal + CLV tracker** · "
    "📧 **daily email brief**\n\n"
    f"👉 To upgrade, contact us at [{CONTACT_EMAIL}](mailto:{CONTACT_EMAIL})."
)
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

_ABBR_TO_NAME = {v: k for k, v in dl.TEAM_NAME_TO_ABBR.items()}

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
week_games = games[(games["season"] == season) & (games["game_type"] == "REG") & (games["week"] == week)].sort_values(["gameday", "gametime"])
completed_games = week_games[week_games["result"].notna()]
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
    # primary: the Turso single-fetcher payload (what Cloud actually serves —
    # its disk caches are usually empty, so the old disk-only check showed "—")
    try:
        _, ts = dl._sgo_board_raw()
        if ts:
            return ts
    except Exception:
        pass
    import glob as _g
    fs = _g.glob(os.path.join(dl.CACHE, "sgo_odds.json")) + _g.glob(os.path.join(dl.CACHE, "odds_api.json")) \
        + [f for f in _g.glob(os.path.join(dl.CACHE, "espn_*.json"))
           if not os.path.basename(f).startswith(("espn_live", "espn_sb", "espn_sum"))]
    return max((os.path.getmtime(f) for f in fs), default=None)


def _et(ts):
    """Epoch -> 'Sep 20, 4:25 PM ET'. Server-local formatting showed UTC on
    Streamlit Cloud ('it does local'); everything user-facing is ET now."""
    from zoneinfo import ZoneInfo
    return pd.Timestamp.fromtimestamp(ts, tz=ZoneInfo("America/New_York")).strftime("%b %-d, %-I:%M %p ET")


@st.cache_data(ttl=900, show_spinner=False)
def fmt_spread(spread, home, away):
    if spread is None:
        return "—"
    side = home if spread < 0 else away
    pts = abs(spread)
    return f"{side} -{pts:.1f}" if spread < 0 else f"{side} +{pts:.1f}"

def _board_rows(season, week):
    """Week-at-a-glance board: model vs market for every UPCOMING game (15-min cache).
    Completed games move to the Completed section (score + model receipts)."""
    wk = games[(games["season"] == season) & (games["game_type"] == "REG") &
               (games["week"] == week) & (games["result"].isna())].sort_values(["gameday", "gametime"])
    ts = _lines_updated_at()
    updated = _et(ts) if ts else "—"
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
            "Edge": (f"{abs(edge):.1f} {home if edge > 0 else away}{' ★' if abs(edge) >= VALUE_EDGE_MIN else ''}"
                     if edge is not None and pred.get("market_src") == "books" else "—"),
            "Model Total": round(float(mt), 1) if mt is not None else None,
            "Market Total": round(float(kt), 1) if kt is not None else None,
            "Edge Total": round(float(mt - kt), 1) if mt is not None and kt is not None else None,
            "Updated": updated,
        })
    return rows


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
try:
    raw = dl.cached_sgo_lines()  # free & keyless: Turso shared cache / disk (works on Cloud)
    odds_source = "SportsGameOdds" if raw else None
    if not raw and _sgo_key:  # live fetch only when the shared cache is empty
        raw = dl.sgo_lines(_sgo_key)
        odds_source = "SportsGameOdds"
    if not raw and api_key:  # last resort: The Odds API (quota-dead main key)
        raw = dl.odds_api_lines(api_key)
        odds_source = "The Odds API"
    for (away_name, home_name), books in (raw or {}).items():
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
    nv_injuries = dl.apply_manual_outs(nv_injuries, season, week)
    nv_injuries = dl.apply_sleeper_outs(nv_injuries, season, week)
except Exception:
    nv_injuries, nv_status = {}, "unavailable"

st.sidebar.markdown(f"**{len(week_games)} games** loaded • injuries for {len(injuries)} teams")
page_options = (["Games", "🔴 Live", "📒 Bet Journal", "📈 Track Record", "🏆 Pick'em", "📰 News", "🏅 Standings",
          "📊 Power Rankings", "❓ How It Works", "📜 Terms", "⚙️ Settings", "🧠 Sentiment Lab"] + (["👥 Users"] if IS_ADMIN else []))
_qp = st.query_params.get("page")
if _qp:  # deep-link support, e.g. ?page=journal from the bet-slip success link
    del st.query_params["page"]
    if _qp == "journal":
        st.session_state["_goto"] = "📒 Bet Journal"
    elif _qp == "sentiment_lab":
        st.session_state["_goto"] = "🧠 Sentiment Lab"
if "_goto" in st.session_state:
    st.session_state["nav_radio"] = st.session_state.pop("_goto")
page = st.sidebar.radio("View", page_options, key="nav_radio")

# ---------------- bet journal page ----------------
if page == "📒 Bet Journal":
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN, gate, paywall
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    if not gate(ctx, "journal"):
        st.header("📒 Bet Journal + CLV Tracker")
        paywall(ctx, "The Bet Journal + CLV Tracker")
        st.stop()
    import views.journal
    views.journal.journal_page(ctx)
    st.stop()
# ---------------- live page ----------------
def live_page():
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.live
    views.live.live_page(ctx)

if page == "🔴 Live":
    live_page()
    st.stop()

# ---------------- pick'em page ----------------
if page == "🏆 Pick'em":
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.pickem
    views.pickem.pickem_page(ctx)
    st.stop()

# ---------------- news page ----------------
def news_page():
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.news
    views.news.news_page(ctx)

if page == "📰 News":
    news_page()
    st.stop()

# ---------------- standings page ----------------
def standings_page():
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.standings
    views.standings.standings_page(ctx)

if page == "🏅 Standings":
    standings_page()
    st.stop()

# ---------------- power rankings page ----------------
def rankings_page():
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.rankings
    views.rankings.rankings_page(ctx)

if page == "📊 Power Rankings":
    rankings_page()
    st.stop()
# ---------------- how-it-works page ----------------
def help_page():
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.help
    views.help.help_page(ctx)

def terms_page():
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.help
    views.help.terms_page(ctx)

if page == "❓ How It Works":
    help_page()
    st.stop()

if page == "📜 Terms":
    terms_page()
    st.stop()

# ---------------- admin: user management page ----------------
def users_page():
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.users
    views.users.users_page(ctx)

if page == "👥 Users":
    if not IS_ADMIN:
        st.error("Admins only.")
        st.stop()
    users_page()
    st.stop()
# ---------------- settings page ----------------
def settings_page():
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.settings
    views.settings.settings_page(ctx)

if page == "⚙️ Settings":
    settings_page()
    st.stop()

if page == "📈 Track Record":
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.track_record
    views.track_record.track_record_page(ctx)
    st.stop()

# ---------------- sentiment lab page ----------------

if page == "🧠 Sentiment Lab":
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )
    import views.sentiment_lab
    views.sentiment_lab.sentiment_lab_page(ctx)
    st.stop()

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

# ---------------- predictor UI ----------------
# ---------------- props UI ----------------

if page == "Games":
    from views.context import AppContext
    from shared import FEATURE_GATES, VALUE_EDGE_MIN, gate, paywall, logo_url, team_md, logo_img, TEAM_SET, LOGO_CFG, matchup_md
    ctx = AppContext(
        games=games,
        elo=elo,
        season=season,
        week=week,
        weeks=weeks,
        week_games=week_games,
        espn_odds=espn_odds,
        books_by_abbr=books_by_abbr,
        injuries=nv_injuries,
        injuries_err=injuries_err,
        api_key=api_key,
        props_api_key=props_api_key,
        player_stats=player_stats,
        def_mults=def_mults,
        USER=USER,
        NAME=NAME,
        LEVEL=LEVEL,
        IS_ADMIN=IS_ADMIN,
        IS_PAID=IS_PAID,
        CONTACT_EMAIL=CONTACT_EMAIL,
        FEATURE_GATES=FEATURE_GATES,
        VALUE_EDGE_MIN=VALUE_EDGE_MIN,
        page=page
    )

    open_set = st.session_state.setdefault("open_games", {0})
    # ---------------- week-at-a-glance board ----------------
    _board = _board_rows(season, week)
    if _board:
        _bdf = pd.DataFrame(_board)

        def _board_style(df):
            """Green-highlight value cells: spread edge >=1.5 (⭐ rows) and |total edge| >=1.5."""
            HILITE = "background-color: #7cffb2; color: #000000; font-weight: 700"
            s = pd.DataFrame("", index=df.index, columns=df.columns)
            s.loc[df["Edge"].astype(str).str.contains("★", regex=False), "Edge"] = HILITE
            m = pd.to_numeric(df["Edge Total"], errors="coerce").abs() >= VALUE_EDGE_MIN
            s.loc[m.fillna(False), "Edge Total"] = HILITE
            return s

        st.dataframe(_bdf.style.apply(_board_style, axis=None), column_config={
            "Away": st.column_config.ImageColumn("Away", width="small"),
            "Home": st.column_config.ImageColumn("Home", width="small"),
            "Model Total": st.column_config.NumberColumn("Model Total", format="%.1f"),
            "Market Total": st.column_config.NumberColumn("Market Total", format="%.1f"),
            "Edge Total": st.column_config.NumberColumn("Edge Total", format="%.1f")},
            hide_index=True, width="stretch")
        st.caption("**★ = the model bets this** — edge vs the books ≥2 pts, the exact bar the 📈 Track Record "
                   "is graded on; **no ★ on any game = no spread bet this week** · 🟩 green cell = bettable edge "
                   "(≥2 pts) · **Edge Total** negative = model leans UNDER, positive = OVER · click a column "
                   "header to sort · hover the table's top-right corner for search & CSV download.")

    from views.live import _live_score_map
    from views.game_detail import _live_strip, _pre_game_tag

    upcoming_games = week_games[week_games["result"].isna()]
    completed_games = week_games[week_games["result"].notna()]
    _live_scores = _live_score_map(season, week)

    for gi, (_, g) in enumerate(upcoming_games.iterrows()):
        away, home = g["away_team"], g["home_team"]
        day = g["gameday"].strftime("%a %b %d") if pd.notna(g["gameday"]) else ""
        label = f"{away} @ {home}  •  {day} {g.get('gametime', '')} ET"
        is_open = gi in open_set
        _ev = _live_scores.get((away, home))
        _live_txt = (f"  •  🔴 **LIVE {_ev['away']} {_ev['a_score']} @ "
                     f"{_ev['home']} {_ev['h_score']}** ({_ev['detail']})"
                     if _ev and _ev["state"] == "in" else "")
        hc1, hc2 = st.columns([11, 1])
        hc1.markdown(f"{matchup_md(away, home, 28)}"
                     f"  •  {day} {g.get('gametime', '')} ET{_live_txt}", unsafe_allow_html=True)
        if hc2.button("▾" if is_open else "▸", key=f"tog_{gi}", help="open/close game"):
            st.session_state["open_games"] = open_set ^ {gi}
            st.rerun()
        if is_open:
            with st.container(border=True):
                _live_strip(ctx, away, home)
                views.game_detail.render_game(ctx, gi, g)

    # ---------------- completed games (auto-moved here as finals post) ----------------
    if not completed_games.empty:
        with st.expander(f"🏁 Completed — Week {week} ({len(completed_games)} final)", expanded=False):
            _cr = views.game_detail._completed_rows(ctx, season, week)
            if _cr:
                st.dataframe(pd.DataFrame(_cr), column_config={
                    "Winner": st.column_config.ImageColumn("Winner", width="small"),
                    "Spread pick": st.column_config.ImageColumn("Spread pick", width="small")},
                    hide_index=True, width="stretch")
                st.caption("Badges appear only where the model had a bettable lean (≥2 pts vs the "
                           "closing line — same bar as the ★/🟩 on the board above). Graded at the "
                           "nflverse **closing** line, same standard as 📈 Track Record. **Model line "
                           "= pre-game** (Elo rebuilt without that game's own result — no hindsight).")

    st.caption("Historical lines: nflverse closing lines. Live: ESPN + The Odds API. For entertainment/research — bet responsibly.")

