"""
Shared helper functions and constants for NFL Edge Finder.
"""
import streamlit as st
import analytics as an
import data as dl
import predictor as pr
import props_model as pm
import pandas as pd
import db

# ---------- feature gates ----------
_LEVEL_RANK = {"user": 0, "paid": 1, "admin": 2, "superadmin": 3}
FEATURE_GATES = {
    "props": "paid",
    "sgp": "paid",
    "journal": "paid",
    "email_brief": "paid",
    "experiment_lab": "superadmin",
}
VALUE_EDGE_MIN = 2.0

def gate(ctx, feature):
    """Check if current user level passes the gate for a feature."""
    return _LEVEL_RANK.get(ctx.LEVEL, 0) >= _LEVEL_RANK[ctx.FEATURE_GATES.get(feature, "admin")]

def paywall(ctx, feature):
    """Upgrade wall shown to free-tier users behind gated features."""
    st.info(f"🔒 **{feature}** is a **Pro** feature.")
    st.markdown(
        "Pro unlocks: 🎰 **Player Props** (injury-aware projections vs live lines) · "
        "🧩 **SGP correlation finder** · 📒 **Bet Journal + CLV tracker** · "
        "📧 **daily email brief**\n\n"
        f"👉 To upgrade, contact us at [{ctx.CONTACT_EMAIL}](mailto:{ctx.CONTACT_EMAIL})."
    )


# ---------- team logos ----------
TEAM_SET = {t for ts in an.DIVISIONS.values() for t in ts}
LOGO_ALIAS = {"STL": "LAR", "SD": "LAC", "OAK": "LV", "LA": "LAR"}  # relocated/legacy abbrs -> current logo
LOGO_CFG = {"Logo": st.column_config.ImageColumn("Logo", width="small")}
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


# ---------- data helpers ----------
@st.cache_resource
def get_elo(games):
    """Return Elo ratings for the given games DataFrame."""
    return pr.Elo(games)

@st.cache_data(ttl=12 * 3600)
def get_player_stats():
    """Load player stats and compute defense multipliers."""
    ps = dl.load_player_stats()
    return ps, pm.defense_multipliers(ps)

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

@st.cache_data(ttl=300)
def get_user_settings(username):
    return db.get_user(username)
