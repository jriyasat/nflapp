"""
Admin interface for NFL‑Edge V2 model weight tuning with historical logging.
"""
import streamlit as st
import json
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime
import csv

sys.path.insert(0, os.path.dirname(__file__))

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config/model_weights.json")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "config/tuning_history.csv")
MAX_HISTORY_ROWS = 500

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
    "admin_secret": "admin123"
}

# Market groups for labeling
MARKET_AFFECTS = {
    "snap_share_weight": "🎯 Player Props (target share)",
    "target_share_weight": "🎯 Player Props (target share)",
    "ryoe_multiplier": "🧠 Player Props (rush yards)",
    "separation_multiplier": "🧠 Player Props (receiving yards)",
    "cushion_multiplier": "🧠 Player Props (receiving yards)",
    "pass_volume_factor": "📈 Both (team pass attempts → props + sides/totals)",
    "rush_volume_factor": "📈 Both (team rush attempts → props + sides/totals)",
    "ypp_weight": "🏈 Sides/Totals (YPP vs Elo blend)",
    "elo_weight": "🏈 Sides/Totals (YPP vs Elo blend)"
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

def load_history():
    """Load tuning history CSV, limit to MAX_HISTORY_ROWS."""
    if not os.path.exists(HISTORY_PATH):
        return pd.DataFrame()
    try:
        df = pd.read_csv(HISTORY_PATH)
        # Keep only last MAX_HISTORY_ROWS rows
        if len(df) > MAX_HISTORY_ROWS:
            df = df.tail(MAX_HISTORY_ROWS)
        return df
    except Exception as e:
        st.error(f"Failed to load history: {e}")
        return pd.DataFrame()

def append_history(config_dict, backtest_results=None):
    """Append a new tuning record to history CSV."""
    record = {
        "timestamp": datetime.now().isoformat(),
        **{k: config_dict.get(k, "") for k in DEFAULTS.keys() if k != "admin_secret"}
    }
    
    # Add backtest results if provided
    if backtest_results and isinstance(backtest_results, dict):
        for market, metrics in backtest_results.items():
            if isinstance(metrics, dict):
                for metric, value in metrics.items():
                    record[f"{market}_{metric}"] = value
    
    # Load existing history
    df = load_history()
    new_df = pd.DataFrame([record])
    df = pd.concat([df, new_df], ignore_index=True)
    
    # Trim to max rows
    if len(df) > MAX_HISTORY_ROWS:
        df = df.tail(MAX_HISTORY_ROWS)
    
    # Save
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    df.to_csv(HISTORY_PATH, index=False)
    return df

def run_backtest():
    """Run props backtest and return parsed results dict."""
    try:
        import subprocess
        # Run the backtest in the nfl-edge-v2-ypp container
        cmd = ["docker", "exec", "nfl-edge-v2-ypp", "python3", "/app/scripts/backtest_props_v2.py"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            return {"error": f"Backtest failed: {result.stderr[:200]}"}
        
        output = result.stdout
        metrics = {}
        lines = output.split('\n')
        
        # Parse MAE section
        mae_section = False
        for line in lines:
            if "=== GATE 1+2: MAE vs actuals" in line:
                mae_section = True
                continue
            elif "=== GATE 3: lean hit-rate" in line:
                mae_section = False
                break
            
            if mae_section and line.strip() and not line.startswith("    market"):
                parts = line.strip().split()
                if len(parts) >= 7 and parts[0] in ["rec_yds", "rec", "rush", "pass"]:
                    market = parts[0]
                    mae_v2 = float(parts[5])
                    metrics[market] = {"mae": mae_v2}
        
        # Parse hit-rate section (7.5% screen)
        hit_rate_section = False
        for line in lines:
            if "=== GATE 3: lean hit-rate vs naive line" in line:
                hit_rate_section = True
                continue
            elif "=== PER-SEASON consistency" in line:
                hit_rate_section = False
                break
            
            if hit_rate_section and "7.5%" in line:
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0] in ["rec_yds", "rec", "rush", "pass"]:
                    market = parts[0]
                    hit_rate = float(parts[3].replace("%", ""))
                    if market in metrics:
                        metrics[market]["hit_rate"] = hit_rate
        
        return {"output": output, "metrics": metrics}
    except Exception as e:
        return {"error": str(e)}

# Streamlit app
st.set_page_config(page_title="NFL‑Edge Model Tuning", layout="wide")

# Create tabs
tab1, tab2 = st.tabs(["🎛️ Model Tuning", "📈 Tuning History"])

with tab1:
    st.title("🔧 NFL‑Edge V2 Model Weight Tuner")
    st.caption("Super‑admin only – changes affect containers on ports 8503/8504")
    
    config = load_config()
    
    # Password check
    admin_secret = config.get("admin_secret", "admin123")
    entered = st.text_input("Admin password", type="password")
    
    if entered == admin_secret:
        st.success("✅ Access granted")
        
        # Player Props - Target Share
        st.subheader("🎯 Player Props - Target Share")
        st.markdown("**Affects:** Player Props (receiving targets)")
        
        col1, col2 = st.columns(2)
        with col1:
            snap_share_weight = st.slider(
                "snap_share_weight",
                0.0, 2.0, config["snap_share_weight"], step=0.05,
                help="Weight of snap‑share in target share calculation."
            )
        with col2:
            target_share_weight = st.slider(
                "target_share_weight",
                0.0, 2.0, config["target_share_weight"], step=0.05,
                help="Weight of target‑share in target share calculation."
            )
        
        # Team Volume Scaling
        st.subheader("📈 Team Volume Scaling")
        st.markdown("**Affects:** Both Player Props & Sides/Totals")
        
        col1, col2 = st.columns(2)
        with col1:
            pass_volume_factor = st.slider(
                "pass_volume_factor",
                0.5, 2.0, config["pass_volume_factor"], step=0.05,
                help="Multiplier for team pass attempts."
            )
        with col2:
            rush_volume_factor = st.slider(
                "rush_volume_factor",
                0.5, 2.0, config["rush_volume_factor"], step=0.05,
                help="Multiplier for team rush attempts."
            )
        
        # NGS Multipliers
        st.subheader("🧠 NGS Metrics Multipliers")
        st.markdown("**Affects:** Player Props (efficiency adjustments)")
        
        ngs_col1, ngs_col2, ngs_col3 = st.columns(3)
        with ngs_col1:
            ryoe_multiplier = st.slider(
                "ryoe_multiplier",
                0.5, 2.0, config["ryoe_multiplier"], step=0.05,
                help="Rush yards over expected (RYOE) multiplier"
            )
        with ngs_col2:
            separation_multiplier = st.slider(
                "separation_multiplier",
                0.5, 2.0, config["separation_multiplier"], step=0.05,
                help="Separation metric multiplier"
            )
        with ngs_col3:
            cushion_multiplier = st.slider(
                "cushion_multiplier",
                0.5, 2.0, config["cushion_multiplier"], step=0.05,
                help="Cushion metric multiplier"
            )
        
        # Sides/Totals Blend
        st.subheader("🏈 Sides/Totals Blend")
        st.markdown("**Affects:** Sides/Totals predictions only")
        
        ypp_weight = st.slider(
            "ypp_weight",
            0.0, 1.0, config["ypp_weight"], step=0.05,
            help="Weight of YPP‑diff model vs Elo"
        )
        elo_weight = 1.0 - ypp_weight
        st.metric("elo_weight", f"{elo_weight:.2f}")
        
        # Save configuration
        st.subheader("💾 Save & Test")
        
        run_backtest_now = st.checkbox("Run backtest after saving", value=True,
                                      help="Takes ~30 seconds")
        
        if st.button("💾 Save Configuration", type="primary"):
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
            
            backtest_results = None
            if run_backtest_now:
                with st.spinner("Running backtest (30-60 seconds)..."):
                    backtest_results = run_backtest()
                    if "error" in backtest_results:
                        st.warning(f"Backtest failed: {backtest_results['error']}")
                    else:
                        st.info("Backtest completed. Check output below.")
                        with st.expander("Backtest Output"):
                            st.text(backtest_results.get("output", "")[:1000])
            
            # Append to history
            history_df = append_history(new_config, backtest_results)
            st.success("✅ Configuration saved and recorded in history")
            
            if history_df is not None and not history_df.empty:
                st.metric("Total tuning records", len(history_df))
            
            st.info("⚠️ Restart containers for changes to take effect immediately.")
        
        # Current config
        with st.expander("📋 Current Configuration"):
            st.json(config)
    
    elif entered != "":
        st.error("❌ Incorrect password")
    else:
        st.info("🔒 Enter admin password to access tuning controls")

with tab2:
    st.title("📈 Tuning History")
    
    history_df = load_history()
    
    if history_df.empty:
        st.info("No tuning history yet. Save some configurations to start recording.")
    else:
        st.metric("Records in history", len(history_df))
        
        # Recent records
        st.subheader("Recent Tuning Runs")
        display_cols = ["timestamp"] + [k for k in DEFAULTS.keys() if k != "admin_secret"]
        if all(col in history_df.columns for col in display_cols):
            display_df = history_df[display_cols].tail(10)
            st.dataframe(display_df, use_container_width=True)
        
        # Charts
        st.subheader("Performance Analysis")
        
        # Check for MAE columns
        mae_columns = [col for col in history_df.columns if 'mae' in col.lower()]
        if mae_columns:
            col1, col2 = st.columns(2)
            with col1:
                if len(mae_columns) > 0:
                    st.line_chart(history_df.set_index("timestamp")[[mae_columns[0]]].tail(20))
            with col2:
                if len(mae_columns) > 1:
                    st.line_chart(history_df.set_index("timestamp")[[mae_columns[1]]].tail(20))
        
        # Weight trends
        st.subheader("Weight Trends")
        
        weight_options = [k for k in DEFAULTS.keys() if k != "admin_secret" and k in history_df.columns]
        if weight_options:
            selected_weight = st.selectbox("Select weight to track", weight_options)
            st.line_chart(history_df.set_index("timestamp")[[selected_weight]].tail(30))
        
        # Export
        st.subheader("Data Export")
        
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "📥 Download CSV",
                history_df.to_csv(index=False),
                file_name=f"tuning_history_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        with col2:
            if st.button("🧹 Clear History (keep last 10)"):
                if not history_df.empty:
                    history_df = history_df.tail(10)
                    history_df.to_csv(HISTORY_PATH, index=False)
                    st.success("History cleared (last 10 records kept)")
                    st.rerun()
        
        # Full data
        with st.expander("📊 Full History Data"):
            st.dataframe(history_df, use_container_width=True)