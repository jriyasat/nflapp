"""
Admin interface for NFL‑Edge V2 model weight tuning with historical logging.
"""
import streamlit as st
import json
import os
import sys
import pandas as pd
import numpy as np
import datetime
import csv
import hashlib

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
    "props_pass_volume_factor": 1.0,
    "props_rush_volume_factor": 1.0,
    "ypp_weight": 0.85,
    "elo_weight": 0.15,
    "market_weight": 0.85,
    "admin_secret": "SET_A_SECRET",
    "superadmin_secret": "SET_A_SUPER_SECRET"
}

# Market groups for labeling
MARKET_AFFECTS = {
    "snap_share_weight": "🎯 Player Props (target share)",
    "target_share_weight": "🎯 Player Props (target share)",
    "ryoe_multiplier": "🧠 Player Props (rush yards)",
    "separation_multiplier": "🧠 Player Props (receiving yards)",
    "cushion_multiplier": "🧠 Player Props (receiving yards)",
    "pass_volume_factor": "📈 Player Props only (team pass attempts)",
    "rush_volume_factor": "📈 Player Props only (team rush attempts)",
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

def append_history(config_dict, backtest_results=None, test_name=""):
    """Append a new tuning record to history CSV."""
    record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "test_name": test_name,
        **{k: config_dict.get(k, "") for k in DEFAULTS.keys() if k not in ["admin_secret", "superadmin_secret"]}
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
                    try:
                        mae_v2 = float(parts[4])  # MAE v2 is at index 4
                        metrics[market] = {"mae": mae_v2}
                    except (ValueError, IndexError):
                        continue
        
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
                    try:
                        hit_rate = float(parts[3].replace("%", ""))
                        if market in metrics:
                            metrics[market]["hit_rate"] = hit_rate
                    except (ValueError, IndexError):
                        continue
        
        return {"output": output, "metrics": metrics}
    except Exception as e:
        return {"error": str(e)}

def get_system_status():
    """Return system status dict: SGO quota, YPP freshness, container health."""
    import datetime, os, json, subprocess, time
    
    status = {}
    
    # SGO quota status
    sgo_log = "/app/data/sgo_rate_check.log"
    reset_date = datetime.datetime(2026, 10, 1, tzinfo=datetime.timezone.utc)  # Known reset
    now = datetime.datetime.now(datetime.timezone.utc)
    days_left = (reset_date - now).days
    hours_left = int((reset_date - now).total_seconds() / 3600)
    
    status['sgo_reset'] = reset_date.isoformat()
    status['sgo_days_left'] = days_left
    status['sgo_hours_left'] = hours_left
    status['sgo_quota_exhausted'] = True if days_left > 0 else False
    
    # YPP coefficient freshness
    coeff_path = "/app/data/model_fits/ypp_coefficients.json"
    if os.path.exists(coeff_path):
        with open(coeff_path) as f:
            coeff = json.load(f)
        last = coeff.get("last_updated")
        if last:
            try:
                if last.endswith('Z'):
                    last = last.replace('Z', '+00:00')
                last_dt = datetime.datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
                age_days = (now - last_dt).days
                status['ypp_age_days'] = age_days
                status['ypp_fresh'] = age_days <= 30
            except Exception:
                status['ypp_age_days'] = None
    else:
        status['ypp_age_days'] = None
    
    return status

def analyze_tuning_history(df):
    """Analyze tuning history dataframe, return insights dict."""
    # Make a copy
    df = df.copy()
    
    # Convert numeric columns
    df['sides_win_pct'] = pd.to_numeric(df['sides_win_pct'], errors='coerce')
    df['sides_roi'] = pd.to_numeric(df['sides_roi'], errors='coerce')
    df['sides_clv'] = pd.to_numeric(df['sides_clv'], errors='coerce')
    df['sides_n_picks'] = pd.to_numeric(df['sides_n_picks'], errors='coerce')
    
    # Filter rows with valid win_pct and enough picks
    df = df.dropna(subset=['sides_win_pct'])
    if 'sides_n_picks' not in df.columns:
        return {'error': 'Missing sides_n_picks column'}
    df = df[df['sides_n_picks'] >= 10]  # minimum credible sample
    
    if len(df) == 0:
        return {'error': 'No valid tuning records with >=10 picks.'}
    
    # Define weight columns and plausible bounds
    weight_cols = [
        'snap_share_weight', 'target_share_weight',
        'ryoe_multiplier', 'separation_multiplier', 'cushion_multiplier',
        'pass_volume_factor', 'rush_volume_factor',
        'ypp_weight', 'elo_weight',
        'props_pass_volume_factor', 'props_rush_volume_factor'
    ]
    
    # Convert weight columns to numeric
    for col in weight_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Filter unrealistic weight values
    # ypp_weight and elo_weight should be between 0 and 1
    if 'ypp_weight' in df.columns:
        df = df[(df['ypp_weight'] >= 0) & (df['ypp_weight'] <= 1)]
    if 'elo_weight' in df.columns:
        df = df[(df['elo_weight'] >= 0) & (df['elo_weight'] <= 1)]
    
    if len(df) == 0:
        return {'error': 'No valid tuning records after filtering unrealistic weights.'}
    
    # Compute correlations with performance metrics
    correlations = {}
    for target in ['sides_win_pct', 'sides_roi', 'sides_clv']:
        if target not in df.columns:
            continue
        corrs = {}
        for col in weight_cols:
            if col in df.columns:
                # Drop NA pairs
                valid = df[[col, target]].dropna()
                if len(valid) >= 3:
                    # Spearman rank correlation
                    corr = valid[col].corr(valid[target], method='spearman')
                    if not pd.isna(corr):
                        corrs[col] = corr
        correlations[target] = corrs
    
    # Identify best configuration
    best_win_idx = df['sides_win_pct'].idxmax()
    best_win = df.loc[best_win_idx]
    
    # Identify best ROI configuration
    best_roi_idx = df['sides_roi'].idxmax() if 'sides_roi' in df.columns else None
    best_roi = df.loc[best_roi_idx] if best_roi_idx is not None else None
    
    # Compute explored ranges for each weight
    ranges = {}
    for col in weight_cols:
        if col in df.columns:
            valid = df[col].dropna()
            if len(valid) > 0:
                ranges[col] = {'min': float(valid.min()), 'max': float(valid.max())}
    
    # Generate suggestions
    suggestions = []
    
    # Correlation-based suggestions
    win_corrs = correlations.get('sides_win_pct', {})
    for col, corr in win_corrs.items():
        if abs(corr) >= 0.2:
            direction = 'increase' if corr > 0 else 'decrease'
            suggestions.append({
                'type': 'correlation',
                'weight': col,
                'direction': direction,
                'strength': abs(corr),
                'reason': f'{col} correlation with win%: {corr:.2f}'
            })
    
    # Exploration suggestions
    global_ranges = {
        'snap_share_weight': (0.0, 2.0),
        'target_share_weight': (0.0, 2.0),
        'ryoe_multiplier': (0.5, 2.0),
        'separation_multiplier': (0.5, 2.0),
        'cushion_multiplier': (0.5, 2.0),
        'pass_volume_factor': (0.5, 2.0),
        'rush_volume_factor': (0.5, 2.0),
        'ypp_weight': (0.0, 1.0),
        'elo_weight': (0.0, 1.0),
        'props_pass_volume_factor': (0.5, 2.0),
        'props_rush_volume_factor': (0.5, 2.0)
    }
    
    for col, rng in ranges.items():
        if col in global_ranges:
            gmin, gmax = global_ranges[col]
            explored_width = rng['max'] - rng['min']
            total_width = gmax - gmin
            if explored_width < total_width * 0.5:  # less than 50% explored
                suggestions.append({
                                    'type': 'exploration',
                                    'weight': col,
                                    'reason': f"Only tested {col} between {rng['min']:.2f}-{rng['max']:.2f} (possible range {gmin:.1f}-{gmax:.1f})"
                                })
    
    # Recommend next configuration based on correlations
    recommended = {}
    for col, corr in win_corrs.items():
        if col in ranges and col in global_ranges:
            gmin, gmax = global_ranges[col]
            current_mid = (ranges[col]['min'] + ranges[col]['max']) / 2
            if corr > 0.2:
                # Move toward max
                recommended[col] = min(gmax, current_mid + (gmax - current_mid) * 0.5)
            elif corr < -0.2:
                # Move toward min
                recommended[col] = max(gmin, current_mid - (current_mid - gmin) * 0.5)
            else:
                # No strong signal, stay near current mid
                recommended[col] = current_mid
        else:
            # No range data, use default mid
            if col in global_ranges:
                gmin, gmax = global_ranges[col]
                recommended[col] = (gmin + gmax) / 2
    
    # Compile results
    result = {
        'n_records': len(df),
        'best_win_config': best_win.to_dict() if not pd.isna(best_win_idx) else None,
        'best_roi_config': best_roi.to_dict() if best_roi is not None else None,
        'correlations': correlations,
        'ranges': ranges,
        'suggestions': suggestions,
        'recommended_weights': recommended,
        'df': df  # cleaned dataframe for further analysis
    }
    return result

def advanced_tuning_analysis(df, target='sides_win_pct'):
    """Advanced AI/ML analysis of tuning history.
    Returns dict with clustering, feature importance, interactions, pareto frontier.
    """
    import pandas as pd
    import numpy as np
    from collections import defaultdict
    
    result = {'clusters': {}, 'feature_importance': {}, 'interactions': [], 'pareto_frontier': []}
    
    # Ensure target exists
    if target not in df.columns:
        return result
    
    # Weight columns (same as basic analysis)
    weight_cols = [
        'snap_share_weight', 'target_share_weight',
        'ryoe_multiplier', 'separation_multiplier', 'cushion_multiplier',
        'pass_volume_factor', 'rush_volume_factor',
        'ypp_weight', 'elo_weight',
        'props_pass_volume_factor', 'props_rush_volume_factor'
    ]
    weight_cols = [col for col in weight_cols if col in df.columns]
    
    # Filter rows with valid target and weights
    keep_cols = weight_cols + [target]
    valid = df[keep_cols].dropna()
    if len(valid) < 5:
        result['insufficient_data'] = f'Only {len(valid)} valid rows, need at least 5'
        return result
    
    # Drop constant weight columns (zero variance)
    varying_cols = []
    for col in weight_cols:
        if col in valid.columns:
            if valid[col].nunique() > 1:
                varying_cols.append(col)
            else:
                result.get('constant_weights', []).append(col)
    if len(varying_cols) < 2:
        result['insufficient_variance'] = f'Only {len(varying_cols)} varying weight columns, need at least 2'
        return result
    
    X = valid[varying_cols].values
    y = valid[target].values
    
    # 1. Feature importance via Random Forest
    try:
        from sklearn.ensemble import RandomForestRegressor
        rf = RandomForestRegressor(n_estimators=50, random_state=42, max_depth=3)
        rf.fit(X, y)
        importances = rf.feature_importances_
        result['feature_importance'] = {col: float(imp) for col, imp in zip(varying_cols, importances)}
    except Exception as e:
        result['feature_importance_error'] = str(e)
    
    # 2. Clustering (KMeans, k=2 or 3)
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        
        # Scale features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Determine k (max 3 clusters, but not more than n_samples/2)
        k = min(3, len(X_scaled) // 2)
        if k >= 2:
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(X_scaled)
            
            # Compute average performance per cluster
            cluster_perf = {}
            for cluster_id in range(k):
                mask = labels == cluster_id
                cluster_y = y[mask]
                cluster_weights = X[mask].mean(axis=0)
                cluster_perf[f'cluster_{cluster_id}'] = {
                    'size': int(mask.sum()),
                    f'avg_{target}': float(cluster_y.mean()),
                    'avg_weights': {col: float(cluster_weights[i]) for i, col in enumerate(varying_cols)}
                }
            result['clusters'] = cluster_perf
    except Exception as e:
        result['clustering_error'] = str(e)
    
    # 3. Interaction detection (simplified: correlation of product term)
    try:
        # Only if we have enough samples
        if len(valid) >= 10:
            interactions = []
            # Use varying columns
            for i in range(len(varying_cols)):
                for j in range(i+1, len(varying_cols)):
                    col1, col2 = varying_cols[i], varying_cols[j]
                    # Compute product
                    product = valid[col1] * valid[col2]
                    # Correlation with target
                    corr = product.corr(valid[target])
                    if abs(corr) > 0.3:
                        interactions.append({
                            'weight_pair': f'{col1} × {col2}',
                            'correlation': float(corr),
                            'interpretation': 'Positive interaction' if corr > 0 else 'Negative interaction'
                        })
            result['interactions'] = interactions
    except Exception as e:
        result['interaction_error'] = str(e)
    
    # 4. Pareto frontier (win_pct vs roi)
    try:
        if 'sides_roi' in df.columns and 'sides_win_pct' in df.columns:
            pareto_df = df[['sides_win_pct', 'sides_roi']].dropna()
            if len(pareto_df) > 0:
                # Simple domination check
                frontier = []
                for idx, row in pareto_df.iterrows():
                    dominated = False
                    for _, other in pareto_df.iterrows():
                        if (other['sides_win_pct'] >= row['sides_win_pct'] and 
                            other['sides_roi'] >= row['sides_roi'] and
                            (other['sides_win_pct'] > row['sides_win_pct'] or 
                             other['sides_roi'] > row['sides_roi'])):
                            dominated = True
                            break
                    if not dominated:
                        frontier.append({
                            'sides_win_pct': float(row['sides_win_pct']),
                            'sides_roi': float(row['sides_roi']),
                            'index': int(idx) if isinstance(idx, (int, np.integer)) else str(idx)
                        })
                result['pareto_frontier'] = frontier
    except Exception as e:
        result['pareto_error'] = str(e)
    
    return result

# Streamlit app
st.set_page_config(page_title="NFL‑Edge Model Tuning", layout="wide")

# System status sidebar
with st.sidebar:
    import datetime
    status = get_system_status()
    st.subheader("📊 System Status")
    
    # SGO quota
    if status['sgo_quota_exhausted']:
        st.warning(f"⚠️ SGO quota exhausted")
        st.caption(f"Resets Oct 1 ({status['sgo_days_left']} days, {status['sgo_hours_left']} hours)")
    else:
        st.success("✅ SGO quota available")
    
    # YPP freshness
    if status['ypp_age_days'] is not None:
        if status['ypp_fresh']:
            st.success(f"✅ YPP coefficients fresh ({status['ypp_age_days']} days)")
        else:
            st.warning(f"⚠️ YPP coefficients stale ({status['ypp_age_days']} days)")
    else:
        st.info("ℹ️ YPP coefficients not found")
    
    st.divider()
    st.caption(f"Admin panel v2 | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Create tabs
tab1, tab2, tab3, tab4 = st.tabs(["🎛️ Model Tuning", "📈 Tuning History", "🔬 Experiment Lab", "👁️ Overseer"])

with tab1:
    st.title("🔧 NFL‑Edge V2 Model Weight Tuner")
    st.caption("Super‑admin only – changes affect containers on ports 8503/8504")
    
    config = load_config()
    
    # Password check
    admin_secret = config.get("admin_secret", "SET_A_SECRET")
    superadmin_secret = config.get("superadmin_secret", "SET_A_SUPER_SECRET")
    entered = st.text_input("Admin password", type="password")
    if entered:
        entered_hash = hashlib.sha256(entered.encode()).hexdigest()[:8]
        admin_hash = hashlib.sha256(admin_secret.encode()).hexdigest()[:8]
        super_hash = hashlib.sha256(superadmin_secret.encode()).hexdigest()[:8]
        admin_match = entered.strip() == admin_secret.strip()
        super_match = entered.strip() == superadmin_secret.strip()
        print(f"[DEBUG] Password check: entered_hash={entered_hash}, admin_hash={admin_hash}, super_hash={super_hash}, admin_match={admin_match}, super_match={super_match}")
    if entered.strip() == admin_secret.strip() or entered.strip() == superadmin_secret.strip():
        st.success("✅ Access granted")
        
        # Load tuning history for reference
        history_df = load_history()
        if not history_df.empty:
            st.subheader("Recent Past Tests")
            display_cols = ["timestamp", "test_name", "sides_win_pct", "sides_n_picks", "ypp_weight", "elo_weight"]
            available_cols = [c for c in display_cols if c in history_df.columns]
            if available_cols:
                total_records = len(history_df)
                # Slider to choose how many recent records to display
                show_count = st.slider(
                    "Show last N records",
                    min_value=3,
                    max_value=total_records,
                    value=min(5, total_records),
                    step=1,
                    help="Display the most recent N tuning runs."
                )
                display_df = history_df[available_cols].tail(show_count)
                st.dataframe(display_df, use_container_width=True)
                # Option to show all
                if total_records > show_count:
                    st.caption(f"Showing {show_count} of {total_records} records. Adjust slider to see more.")
            else:
                st.info("No test name or performance columns in history.")
        
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
               "Pass volume factor (props_pass_volume_factor)",
               0.5, 2.0, config.get("props_pass_volume_factor", config.get("pass_volume_factor", 1.0)), step=0.05,
               help="Multiplier for team pass attempts affecting player props."
            )
        with col2:
            rush_volume_factor = st.slider(
                "Rush volume factor (props_rush_volume_factor)",
                0.5, 2.0, config.get("props_rush_volume_factor", config.get("rush_volume_factor", 1.0)), step=0.05,
                help="Multiplier for team rush attempts affecting player props."
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

        # Sentiment Tuning
        st.subheader("🧠 Sentiment Layer")
        st.markdown("**Affects:** Enhanced model (sentiment‑weighted) + Sentiment‑only predictor")
        
        sentiment_weight = st.slider(
            "sentiment_weight",
            0.0, 0.1, config.get("sentiment_weight", 0.0), step=0.01,
            help="Weight of sentiment composite (confidence+morale‑controversy) into model spread."
        )
        sentiment_only_threshold = st.slider(
            "sentiment_only_threshold",
            0.0, 1.5, config.get("sentiment_only_threshold", 0.5), step=0.05,
            help="Composite difference threshold for sentiment‑only binary picks."
        )
        sentiment_enabled = st.checkbox("Enable sentiment layer", value=config.get("sentiment_weight", 0.0) > 0, key="sentiment_enable_tab1")
        if sentiment_enabled:
            st.info("Sentiment layer active. Scores will be fetched and used.")
        else:
            st.warning("Sentiment layer disabled. No sentiment impact.")

        # Sentiment Scores Display
        with st.expander("📊 Sentiment Scores (Week 4)", expanded=False):
            import sentiment as stm
            import data as dl
            import pandas as pd
            season = 2026
            week = 4
            df = dl.load_games()
            games = df[(df['season'] == season) & (df['week'] == week)]
            teams = set(games['away_team'].tolist() + games['home_team'].tolist())
            rows = []
            for team in sorted(teams):
                scores = stm.get_sentiment_score(team, season, week, 'combined')
                if scores:
                    rows.append({
                        'Team': team,
                        'Confidence': scores['confidence'],
                        'Morale': scores['morale'],
                        'Controversy': scores['controversy'],
                        'Composite': scores['confidence'] + scores['morale'] - scores['controversy'],
                    })
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                st.caption(f'{len(rows)} teams scored')
            else:
                st.info('No sentiment scores yet.')
            if st.button('🔄 Refresh sentiment scores for Week 4'):
                with st.spinner('Collecting sentiment for all teams...'):
                    import time
                    for team in sorted(teams):
                        existing = stm.get_sentiment_score(team, season, week, 'combined')
                        if existing:
                            continue
                        snippets = stm.collect_all_snippets(team, season, week)
                        if snippets:
                            scores = stm.score_sentiment_llm(snippets)
                            stm.store_sentiment_score(team, season, week, 'combined', scores)
                            time.sleep(2)
                    st.success('Sentiment scores updated')
                    st.rerun()
        
        # Sentiment‑Only Picks Table
        with st.expander("🎯 Sentiment‑Only Picks (Week 4)", expanded=False):
            import sentiment as stm
            import data as dl
            import pandas as pd
            season = 2026
            week = 4
            df = dl.load_games()
            games = df[(df['season'] == season) & (df['week'] == week)]
            picks_rows = []
            for _, game in games.iterrows():
                away, home = game['away_team'], game['home_team']
                away_scores = stm.get_sentiment_score(away, season, week, 'combined')
                home_scores = stm.get_sentiment_score(home, season, week, 'combined')
                if away_scores is None or home_scores is None:
                    continue
                diff = home_scores['composite'] - away_scores['composite']
                pick = 'home' if diff > sentiment_only_threshold else 'away'
                picks_rows.append({
                    'Matchup': f'{away} @ {home}',
                    'Composite Diff': round(diff, 2),
                    'Pick': pick,
                    'Threshold': sentiment_only_threshold,
                })
            if picks_rows:
                st.dataframe(pd.DataFrame(picks_rows), hide_index=True, use_container_width=True)
                st.caption(f'Sentiment‑only picks (threshold {sentiment_only_threshold})')
            else:
                st.info('Insufficient sentiment scores to generate picks.')
        
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
                "props_pass_volume_factor": pass_volume_factor,
                "props_rush_volume_factor": rush_volume_factor,
                "ypp_weight": ypp_weight,
                "elo_weight": elo_weight,
                "sentiment_weight": sentiment_weight,
                "sentiment_only_threshold": sentiment_only_threshold,
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
        import datetime as dt
        with col1:
            st.download_button(
                "📥 Download CSV",
                history_df.to_csv(index=False),
                file_name=f"tuning_history_{dt.datetime.now().strftime('%Y%m%d')}.csv",
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

with tab3:
    st.title("🔬 Experiment Lab")
    st.caption("Super‑admin only – staged weight tuning with walk‑forward backtests")

    config = load_config()
    superadmin_secret = config.get("superadmin_secret", "SET_A_SUPER_SECRET")
    entered = st.text_input("Superadmin password", type="password")
    if entered:
        entered_hash = hashlib.sha256(entered.encode()).hexdigest()[:8]
        expected_hash = hashlib.sha256(superadmin_secret.encode()).hexdigest()[:8]
        print(f"[DEBUG] Superadmin password check: entered_hash={entered_hash}, expected_hash={expected_hash}, match={entered.strip() == superadmin_secret.strip()}")
    if entered.strip() == superadmin_secret.strip():
        st.success("✅ Super‑admin access granted")
        
        # Display current config
        st.subheader("📋 Current Configuration")
        st.json({k: config[k] for k in config if k not in ["admin_secret", "superadmin_secret"]})
        
        # Candidate config sliders
        st.subheader("🎛️ Candidate Configuration")
        st.markdown("Adjust sliders to propose new weights. Backtest will compare candidate vs current.")
        
        col1, col2 = st.columns(2)
        with col1:
            candidate_snap_share_weight = st.slider(
                "snap_share_weight (candidate)",
                0.0, 2.0, config["snap_share_weight"], step=0.05,
                help="🎯 Player Props only (target share)"
            )
            candidate_target_share_weight = st.slider(
                "target_share_weight (candidate)",
                0.0, 2.0, config["target_share_weight"], step=0.05,
                help="🎯 Player Props only (target share)"
            )
            candidate_pass_volume_factor = st.slider(
                "Pass volume factor (props_pass_volume_factor) (candidate)",
                0.0, 4.0, config.get("props_pass_volume_factor", config.get("pass_volume_factor", 1.0)), step=0.05,
                help="Candidate multiplier for team pass attempts (props)."
            )
        with col2:
            candidate_rush_volume_factor = st.slider(
                "Rush volume factor (props_rush_volume_factor) (candidate)",
                0.0, 4.0, config.get("props_rush_volume_factor", config.get("rush_volume_factor", 1.0)), step=0.05,
                help="Candidate multiplier for team rush attempts (props)."
            )
            candidate_ypp_weight = st.slider(
                "ypp_weight (candidate)",
                0.0, 1.0, config["ypp_weight"], step=0.05,
                help="🏈 Sides/Totals only (YPP vs Elo blend)"
            )
            candidate_elo_weight = 1.0 - candidate_ypp_weight
            st.metric("elo_weight (derived)", f"{candidate_elo_weight:.2f}")
        
        # Show affected markets
        st.info("""
        ### Slider Impact
        * **snap_share_weight / target_share_weight** → Player Props only
        * **pass_volume_factor / rush_volume_factor** → Player Props only
        * **ypp_weight / elo_weight** → Sides/Totals only (within the 15% model prior; market anchor remains 85%)
        """)
        
        # Edge Distribution Histogram
        st.subheader("📊 Edge Distribution Histogram")
        st.caption("Analyze edge magnitude distribution for current config (threshold=0).")
        if st.button("Compute Edge Distribution (Current Config)"):
            status = get_system_status()
            if status['sgo_quota_exhausted']:
                st.warning(f"SGO quota exhausted. Resets Oct 1 ({status['sgo_days_left']} days, {status['sgo_hours_left']} hours). Cannot compute edges.")
                st.info("Histogram will be available after quota reset.")
            else:
                with st.spinner("Computing edges..."):
                    try:
                        import sys, os, json, pandas as pd, numpy as np
                        sys.path.insert(0, '/app')
                        import data as dl
                        import predictor as pr
                        from ypp_model import YPPModel
                        from scripts.walk_forward_sides_no_ypp import evaluate_config
                        games = dl.load_games()
                        ypp_model = YPPModel()
                        ABBR_TO_LONG = {abbr: long for long, abbr in dl.TEAM_NAME_TO_ABBR.items()}
                        def market_line_fn(game_row):
                            books = dl.cached_sgo_lines()
                            if books:
                                away_long = ABBR_TO_LONG.get(game_row['away_team'].upper())
                                home_long = ABBR_TO_LONG.get(game_row['home_team'].upper())
                                if away_long and home_long:
                                    key = (away_long, home_long)
                                    if key in books:
                                        market = pr.consensus(books[key])
                                        return market.get('home_spread'), 'books'
                            if pd.notna(game_row.get('spread_line')):
                                return -float(game_row['spread_line']), 'nflverse'
                            return None, 'none'
                        market_weight = config.get('market_weight', 0.85)
                        nonmarket_weight = 1.0 - market_weight
                        ypp_weight = config.get('ypp_weight', 0.85)
                        elo_weight = config.get('elo_weight', 0.15)
                        total = ypp_weight + elo_weight
                        if total > 0:
                            ypp_weight /= total
                            elo_weight /= total
                        result = evaluate_config(games, ypp_model, market_line_fn, market_weight, nonmarket_weight,
                                                 ypp_weight, elo_weight, threshold=0)
                        if 'full_df' in result:
                            edges = result['full_df']['edge'].abs()
                            st.metric('Games evaluated', len(edges))
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric('Edges ≥ 2.0', (edges >= 2.0).sum())
                            with col2:
                                st.metric('Edges ≥ 1.5', (edges >= 1.5).sum())
                            with col3:
                                st.metric('Edges ≥ 1.0', (edges >= 1.0).sum())
                            # Histogram
                            st.bar_chart(pd.cut(edges, bins=[0,0.5,1.0,1.5,2.0,2.5,3.0,4.0,10.0],
                                                labels=['0-0.5','0.5-1','1-1.5','1.5-2','2-2.5','2.5-3','3-4','4+']).value_counts())
                        else:
                            st.error('Failed to compute edges')
                    except Exception as e:
                        st.error(f'Error computing edges: {e}')
        
        # Run walk‑forward backtest
        st.subheader("🔬 Backtest & Compare")
        
        # YPP coefficient freshness
        coeff_path = "/app/data/model_fits/ypp_coefficients.json"
        if os.path.exists(coeff_path):
            import json, datetime
            with open(coeff_path) as f:
                coeff = json.load(f)
            last = coeff.get("last_updated")
            if last:
                try:
                    # Handle both timezone-aware and naive datetimes
                    if last.endswith('Z'):
                        last = last.replace('Z', '+00:00')
                    last_dt = datetime.datetime.fromisoformat(last)
                    
                    # Make both datetimes timezone-aware or both naive
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if last_dt.tzinfo is None:
                        # Convert naive to UTC-aware
                        last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
                    
                    age_days = (now - last_dt).days
                    if age_days > 30:
                        st.warning(f"⚠️ YPP coefficients are {age_days} days old – consider retraining.")
                    else:
                        st.success(f"✅ YPP coefficients fresh ({age_days} days old).")
                except Exception as e:
                    st.error(f"❌ Error parsing timestamp: {e}")
            else:
                st.warning("⚠️ YPP coefficients lack timestamp.")
        else:
            st.error("❌ YPP coefficients file missing.")
        
        if st.button("🔄 Retrain YPP Coefficients from Cache"):
            with st.spinner("Retraining YPP model (10‑15 seconds)..."):
                import subprocess
                result = subprocess.run(
                    ["python3", "/app/scripts/fit_ypp_model_from_cache.py"],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    st.success("✅ YPP coefficients retrained")
                    st.code(result.stdout[:2000])
                else:
                    st.error(f"❌ Retraining failed: {result.stderr[:1000]}")
        
        st.warning("⚠️ YPP coefficients need retraining before tuning meaningful.")
        
        if st.button("🚀 Run Walk‑Forward Backtest (2021‑2025)", type="primary"):
            with st.spinner("Running walk‑forward backtest (2‑3 minutes)..."):
                # TODO: implement
                import time
                time.sleep(2)
                st.error("Backtest execution not yet implemented. Requires YPP coeff retraining.")
        
        # Results placeholder
        st.subheader("📊 Backtest Results")
        st.info("Results will appear here after backtest completes.")
        
    elif entered != "":
        st.error("❌ Incorrect super‑admin password")
    else:
        st.info("🔒 Enter super‑admin password to access Experiment Lab")


with tab4:
    st.title("👁️ Tuning Overseer")
    st.caption("Analyzes tuning history and recommends optimal weight combinations.")
    
    # Password check (same as tab1)
    config = load_config()
    admin_secret = config.get("admin_secret", "SET_A_SECRET")
    superadmin_secret = config.get("superadmin_secret", "SET_A_SUPER_SECRET")
    entered = st.text_input("Admin password", type="password", key="overseer_pw")
    if entered.strip() == admin_secret.strip() or entered.strip() == superadmin_secret.strip():
        st.success("✅ Access granted")
        
        # Button to refresh analysis
        if st.button("📊 Analyze Tuning History", type="primary"):
            import pandas as pd, os
            history_path = "/app/config/tuning_history.csv"
            if os.path.exists(history_path):
                df = pd.read_csv(history_path)
                if len(df) > 0:
                    # Find row with highest sides_win_pct (ensure numeric)
                    df['sides_win_pct'] = pd.to_numeric(df['sides_win_pct'], errors='coerce')
                    df = df.dropna(subset=['sides_win_pct'])
                    if len(df) > 0:
                        best = df.loc[df['sides_win_pct'].idxmax()]
                        st.subheader("🏆 Best Observed Configuration")
                        st.metric("Win %", f"{best['sides_win_pct']:.2f}%")
                        st.metric("Picks", int(best['sides_n_picks']))
                        st.metric("ROI %", f"{best['sides_roi']:.2f}%")
                        st.metric("CLV", f"{best['sides_clv']:.3f}")
                        # Display relevant weights
                        st.write("**Key weights:**")
                        cols = ['ypp_weight', 'elo_weight', 'pass_volume_factor', 'rush_volume_factor']
                        for col in cols:
                            if col in best:
                                st.metric(col, f"{best[col]:.3f}")
                        # Show top 5
                        st.subheader("📈 Top 5 Configurations by Win %")
                        top5 = df.nlargest(5, 'sides_win_pct')[['test_name', 'sides_win_pct', 'sides_n_picks', 'sides_roi', 'sides_clv', 'ypp_weight', 'elo_weight', 'pass_volume_factor', 'rush_volume_factor']]
                        st.dataframe(top5, use_container_width=True)
                        
                        # AI‑Powered Analysis
                        st.subheader("🤖 AI‑Powered Insights")
                        st.caption("Analysis based on Spearman correlations and explored weight ranges.")
                        
                        # Run analysis
                        analysis = analyze_tuning_history(df)
                        if 'error' in analysis:
                            st.warning(f"Analysis limited: {analysis['error']}")
                        else:
                            st.info(f"Analyzed {analysis['n_records']} valid tuning records.")
                            
                            # Correlation table
                            win_corrs = analysis['correlations'].get('sides_win_pct', {})
                            if win_corrs:
                                st.subheader("📊 Weight‑Performance Correlations")
                                corr_df = pd.DataFrame([
                                    {'Weight': col, 'Correlation with Win%': corr}
                                    for col, corr in win_corrs.items()
                                ]).sort_values('Correlation with Win%', ascending=False)
                                st.dataframe(corr_df, use_container_width=True)
                            
                            # Suggestions
                            suggestions = analysis.get('suggestions', [])
                            if suggestions:
                                st.subheader("💡 Recommended Tuning Actions")
                                for i, s in enumerate(suggestions, 1):
                                    if s['type'] == 'correlation':
                                        st.markdown(f"{i}. **{s['direction'].title()} {s['weight']}** ({s['reason']})")
                                    else:
                                        st.markdown(f"{i}. **Explore wider range** — {s['reason']}")
                            else:
                                st.info("No strong signals detected. Keep exploring weight space.")
                            
                            # Recommended next configuration
                            recommended = analysis.get('recommended_weights', {})
                            if recommended:
                                st.subheader("🎯 Suggested Next Configuration")
                                st.caption("Weights derived from correlation trends and exploration gaps.")
                                cols = st.columns(3)
                                idx = 0
                                for col, val in recommended.items():
                                    with cols[idx % 3]:
                                        st.metric(col, f"{val:.2f}")
                                    idx += 1
                                
                                # Pre‑fill sliders for quick testing
                                st.markdown("**Copy to Model Tuning:** Use these values in the Model Tuning tab.")
                                st.json({k: round(v, 2) for k, v in recommended.items()})

                                # Advanced AI/ML analysis
                                st.subheader("🧠 Advanced AI/ML Analysis")
                                advanced_on = st.checkbox("Show clustering, feature importance, interactions, and Pareto frontier", value=False)
                                if advanced_on:
                                    with st.spinner("Running advanced analysis..."):
                                        advanced = advanced_tuning_analysis(df)
                                    if advanced.get('feature_importance'):
                                        st.subheader("📈 Feature Importance (Random Forest)")
                                        fi_df = pd.DataFrame([
                                            {'Weight': col, 'Importance': imp}
                                            for col, imp in advanced['feature_importance'].items()
                                        ]).sort_values('Importance', ascending=False)
                                        st.dataframe(fi_df, use_container_width=True)
                                    
                                    if advanced.get('clusters'):
                                        st.subheader("📊 Configuration Clusters (K‑Means)")
                                        for cluster_name, cluster_info in advanced['clusters'].items():
                                            st.markdown(f"**{cluster_name}** (size={cluster_info['size']})")
                                            st.metric(f"Avg Win %", f"{cluster_info['avg_sides_win_pct']:.2f}%")
                                            # Show key weight differences
                                            weights = cluster_info['avg_weights']
                                            top3 = sorted(weights.items(), key=lambda x: abs(x[1] - df[weights.keys()].mean()[x[0]]), reverse=True)[:3]
                                            if top3:
                                                st.caption("Key weight differences: " + ", ".join([f"{col}={val:.2f}" for col, val in top3]))
                                    
                                    if advanced.get('interactions'):
                                        st.subheader("🔄 Weight Interaction Effects")
                                        for interaction in advanced['interactions']:
                                            st.markdown(f"**{interaction['weight_pair']}**: correlation={interaction['correlation']:.2f} ({interaction['interpretation']})")
                                    
                                    if advanced.get('pareto_frontier'):
                                        st.subheader("🏆 Pareto Frontier (Win% vs ROI)")
                                        frontier_df = pd.DataFrame(advanced['pareto_frontier'])
                                        st.dataframe(frontier_df[['sides_win_pct', 'sides_roi']], use_container_width=True)
                                        st.caption("Configurations not dominated in both win% and ROI.")

                            else:
                                st.info("No recommendation generated (insufficient data).")
                        
                    else:
                        st.warning("No valid tuning records with numeric win_pct.")
                else:
                    st.warning("No valid tuning records found.")
            else:
                st.error("Tuning history file not found.")
    elif entered != "":
        st.error("❌ Incorrect password")
    else:
        st.info("🔒 Enter admin password to access Overseer")
