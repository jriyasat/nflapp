"""Model prediction tracker: logs model picks (|edge| >= 2) and grades them
against the CLOSING line. Storage: data/predictions.csv.

Pick rules:
- spread: |model_spread - market_spread| >= 2 -> pick = the side the model likes
- total:  |model_total - market_total| >= 2  -> pick = OVER/UNDER
Grading (at close): did the picked side cover the closing spread / closing total?
Profit: flat 1u at -110 (+0.909 / -1 / 0).
"""

import os
import uuid

import pandas as pd

import data as dl
import predictor as pr

PICKS_PATH = os.path.join(dl.CACHE, "predictions.csv")
EDGE_MIN = 2.0
COLUMNS = ["id", "logged_at", "season", "week", "game", "pick_type", "side",
           "model_val", "market_val_log", "edge_log", "p_cover_log",
           "closing_line", "grade", "profit"]


def load_picks():
    if os.path.exists(PICKS_PATH):
        return pd.read_csv(PICKS_PATH)
    return pd.DataFrame(columns=COLUMNS)


def _save(df):
    df.to_csv(PICKS_PATH, index=False)


def log_predictions(games, elo, season, week, books_by_abbr=None, quiet=True):
    """Log new picks for a week (deduped by game+pick_type). Returns new pick count."""
    picks = load_picks()
    existing = set(zip(picks["game"], picks["pick_type"])) if len(picks) else set()
    wk = games[(games["season"] == season) & (games["game_type"] == "REG")
               & (games["week"] == week)]
    books_by_abbr = books_by_abbr or {}
    new = 0
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    for _, g in wk.iterrows():
        away, home = g["away_team"], g["home_team"]
        label = f"{away} @ {home}"
        pred = pr.predict_game(g, elo, books=books_by_abbr.get((away, home)))
        rows = []
        if pred.get("edge_pts") is not None and abs(pred["edge_pts"]) >= EDGE_MIN:
            side = home if pred["edge_pts"] > 0 else away
            rows.append({
                "pick_type": "spread", "side": side,
                "model_val": round(pred["model_spread"], 2),
                "market_val_log": pred["market_spread"],
                "edge_log": round(abs(pred["edge_pts"]), 2),
                "p_cover_log": round(pred["p_home_cover"] if side == home
                                     else 1 - pred["p_home_cover"], 4),
            })
        if pred.get("model_total") is not None:
            gap = pred["model_total"] - pred["market_total"]
            if abs(gap) >= EDGE_MIN:
                side = "over" if gap > 0 else "under"
                rows.append({
                    "pick_type": "total", "side": side,
                    "model_val": round(pred["model_total"], 1),
                    "market_val_log": pred["market_total"],
                    "edge_log": round(abs(gap), 2),
                    "p_cover_log": round(pred["p_over"] if side == "over"
                                         else 1 - pred["p_over"], 4),
                })
        for r in rows:
            if (label, r["pick_type"]) in existing:
                continue
            picks = pd.concat([picks, pd.DataFrame([{
                "id": uuid.uuid4().hex[:8], "logged_at": now, "season": season,
                "week": week, "game": label, **r,
                "closing_line": None, "grade": "pending", "profit": None,
            }])], ignore_index=True)
            new += 1
    if new:
        _save(picks)
    if not quiet:
        print(f"logged {new} new picks for {season} W{week}")
    return new


def grade_predictions(games):
    """Grade pending picks whose games have results. Returns updated df."""
    picks = load_picks()
    if not len(picks):
        return picks
    changed = False
    for i, p in picks.iterrows():
        if p["grade"] != "pending":
            continue
        season, week, label = int(p["season"]), int(p["week"]), p["game"]
        away, home = label.split(" @ ")
        m = games[(games["season"] == season) & (games["week"] == week) &
                  (games["game_type"] == "REG") &
                  (games["away_team"] == away) & (games["home_team"] == home)]
        if m.empty or pd.isna(m.iloc[0]["result"]):
            continue
        g = m.iloc[0]
        changed = True
        if p["pick_type"] == "spread":
            if pd.isna(g["spread_line"]):
                continue
            picks.at[i, "closing_line"] = g["spread_line"] if p["side"] == away else -g["spread_line"]
            margin = g["result"] if p["side"] == home else -g["result"]
            diff = margin + picks.at[i, "closing_line"]
        else:
            if pd.isna(g["total_line"]):
                continue
            picks.at[i, "closing_line"] = g["total_line"]
            diff = (g["total"] - g["total_line"]) * (1 if p["side"] == "over" else -1)
        if diff > 0:
            picks.at[i, "grade"], picks.at[i, "profit"] = "won", 100 / 110
        elif diff < 0:
            picks.at[i, "grade"], picks.at[i, "profit"] = "lost", -1.0
        else:
            picks.at[i, "grade"], picks.at[i, "profit"] = "push", 0.0
    if changed:
        _save(picks)
    return picks


def summary(picks):
    out = {}
    for ptype in ("spread", "total"):
        sub = picks[(picks["pick_type"] == ptype) & picks["grade"].isin(["won", "lost", "push"])]
        decided = sub[sub["grade"] != "push"]
        out[ptype] = {
            "record": f"{int((sub['grade']=='won').sum())}-{int((sub['grade']=='lost').sum())}-{int((sub['grade']=='push').sum())}",
            "win_pct": (decided["grade"] == "won").mean() * 100 if len(decided) else None,
            "profit": float(pd.to_numeric(sub["profit"], errors="coerce").fillna(0).sum()),
            "n": len(sub),
        }
    out["pending"] = int((picks["grade"] == "pending").sum())
    return out


def edge_buckets(picks):
    graded = picks[picks["grade"].isin(["won", "lost"])]
    if graded.empty:
        return []
    bins = [(2.0, 2.5), (2.5, 3.5), (3.5, 99)]
    rows = []
    for lo, hi in bins:
        sub = graded[(graded["edge_log"] >= lo) & (graded["edge_log"] < hi)]
        if len(sub):
            rows.append({"Edge size": f"{lo}-{hi if hi < 99 else '+'} pts",
                         "Picks": len(sub),
                         "Win %": f"{(sub['grade']=='won').mean()*100:.1f}%",
                         "Profit": f"{pd.to_numeric(sub['profit']).sum():+.2f}u"})
    return rows


def calibration(picks):
    graded = picks[picks["grade"].isin(["won", "lost"])].copy()
    if graded.empty:
        return []
    graded["bucket"] = pd.cut(graded["p_cover_log"], [0, .53, .56, .60, 1.0],
                              labels=["50-53%", "53-56%", "56-60%", "60%+"])
    rows = []
    for b, sub in graded.groupby("bucket", observed=True):
        rows.append({"Model confidence": str(b), "Picks": len(sub),
                     "Actual win %": f"{(sub['grade']=='won').mean()*100:.1f}%"})
    return rows
