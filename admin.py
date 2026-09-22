"""
Admin interface for NFL‑Edge V2 model weight tuning.
Run with: streamlit run admin.py --server.port 8505
"""
import streamlit as st
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config/model_weights.json")
DEFAULTS = {
    "snap_share_weight": 1.0,
    "target_share_weight": 0.0,
    "ryoe_multiplier": 1.0,
    "separation_multiplier": 1.0,
    "cushion_multiplier": 1.0,
    "pass_volume_factor": 1.0,
    "rush_volume_factor": 1.0,
    "ypp_weight": 0.85,
    "elo_weight": 0.15,
    "admin_secret": "CHANGE_ME"
}

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
    except Exception:
        config = {}
    # ensure all keys exist
    for k, v in DEFAULTS.items():
        if k not in config:
            config[k] = v
    return config

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, indent=2, fp=f)

st.set_page_config(page_title="NFL‑Edge Model Tuning", layout="wide")
st.title("🔧 NFL‑Edge V2 Model Weight Tuner")
st.caption("Super‑admin only – changes affect containers on ports 8503/8504")

config = load_config()

# Password check
admin_secret = config.get("admin_secret", "CHANGE_ME")
if admin_secret == "CHANGE_ME":
    st.warning("⚠️ Admin secret not set. Please edit `config/model_weights.json` and set `admin_secret`.")
    entered = st.text_input("Temporary admin password", type="password")
else:
    entered = st.text_input("Admin password", type="password")

if entered == admin_secret:
    st.success("✅ Access granted")
    
    # Snap‑share vs target‑share blend
    st.subheader("📊 Snap‑share vs Target‑share Weights")
    snap_share_weight = st.slider(
        "snap_share_weight (0 = ignore snaps, 1 = full snap‑share)",
        0.0, 2.0, config["snap_share_weight"], step=0.05,
        help="Weight of snap‑share in target share calculation"
    )
    target_share_weight = st.slider(
        "target_share_weight (0 = ignore targets, 1 = full target‑share)",
        0.0, 2.0, config["target_share_weight"], step=0.05,
        help="Weight of target‑share in target share calculation"
    )
    
    # Volume scaling
    st.subheader("📈 Team Volume Scaling")
    pass_volume_factor = st.slider(
        "pass_volume_factor (scale team pass attempts)",
        0.5, 2.0, config["pass_volume_factor"], step=0.05,
        help="Multiplier for team_pass_att"
    )
    rush_volume_factor = st.slider(
        "rush_volume_factor (scale team rush attempts)",
        0.5, 2.0, config["rush_volume_factor"], step=0.05,
        help="Multiplier for team_rush_att"
    )
    
    # NGS multipliers (placeholder)
    st.subheader("🧠 NGS Metrics Multipliers")
    ryoe_multiplier = st.slider(
        "ryoe_multiplier (RYOE effect on rush yards)",
        0.5, 2.0, config["ryoe_multiplier"], step=0.05,
        help="Multiplier for rush yards over expected"
    )
    separation_multiplier = st.slider(
        "separation_multiplier (separation effect on receiving yards)",
        0.5, 2.0, config["separation_multiplier"], step=0.05,
        help="Multiplier for separation metric"
    )
    cushion_multiplier = st.slider(
        "cushion_multiplier (cushion effect on receiving yards)",
        0.5, 2.0, config["cushion_multiplier"], step=0.05,
        help="Multiplier for cushion metric"
    )
    
    # YPP vs Elo blend
    st.subheader("🎯 YPP vs Elo Blend")
    ypp_weight = st.slider(
        "ypp_weight (weight of YPP in sides/totals model)",
        0.0, 1.0, config["ypp_weight"], step=0.05,
        help="Weight of YPP‑diff model vs Elo (USE_YPP env)"
    )
    elo_weight = 1.0 - ypp_weight
    
    # Save button
    if st.button("💾 Save Configuration"):
        new_config = {
            "snap_share_weight": snap_share_weight,
            "target_share_weight": target_share_weight,
            "ryoe_multiplier": ryoe_multiplier,
            "separation_multiplier": separation_multiplier,
            "cushion_multiplier": cushion_multiplier,
            "pass_volume_factor": pass_volume_factor,
            "rush_volume_factor": rush_volume_factor,
            "ypp_weight": ypp_weight,
            "elo_weight": elo_weight,
            "admin_secret": admin_secret
        }
        save_config(new_config)
        st.success("✅ Configuration saved to `config/model_weights.json`")
        st.info("⚠️ Restart containers for changes to take effect.")
        
    # Display current values
    with st.expander("📋 Current Configuration JSON"):
        st.json(config)
        
elif entered != "":
    st.error("❌ Incorrect password")

else:
    st.info("🔒 Enter admin password to access tuning controls")
