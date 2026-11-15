"""Model prediction tracker: logs model picks (|edge| >= 2) and grades them
against the CLOSING line. Storage: SQLite via db.py (global, shared)."""

import pandas as pd

import data as dl
import db
import predictor as pr

PICKS_PATH = db.DB_PATH  # backwards-compat reference
EDGE_MIN = 2.0


def load_picks():
    return db.load_picks()


def log_predictions(games, elo, season, week, books_by_abbr=None, espn_odds=None,
                    injuries=None, quiet=True):
    """Log new picks for a week (deduped by game+pick_type). Returns new count.

    MUST receive the same context the app displays with (books + espn +
    injuries) or the logged model diverges from the shown model."""
    existing = db.existing_pick_keys()
    wk = games[(games["season"] == season) & (games["game_type"] == "REG")
               & (games["week"] == week)]
    books_by_abbr = books_by_abbr or {}
    espn_odds = espn_odds or {}
    new = 0
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    for _, g in wk.iterrows():
        away, home = g["away_team"], g["home_team"]
        label = f"{away} @ {home}"
        pred = pr.predict_game(g, elo, books=books_by_abbr.get((away, home)),
                               espn=espn_odds.get((away, home)), injuries=injuries)
        rows = []
        # spread picks log ONLY against a real multi-book market. The espn_ml/nflverse
        # fallbacks exist to carry the DISPLAY before lines post — an "edge" vs a
        # fallback line is phantom (W1-2 2026: 10 picks logged vs fallback lines 6-28
        # pts off the true market, all graded losses vs real closings).
        if (pred.get("edge_pts") is not None and abs(pred["edge_pts"]) >= EDGE_MIN
                and pred.get("market_src") == "books"):
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
            db.insert_pick({"logged_at": now, "season": season, "week": week,
                            "game": label, **r})
            existing.add((label, r["pick_type"]))
            new += 1
    if not quiet:
        print(f"logged {new} new picks for {season} W{week}")
    return new


GUST_PAPER_MIN = 20.0  # paper-trade trigger: forecast gusts (mph) at kickoff

# paper-trade rules (Jeff, 2026-10-08 — per-rule records, samples disclosed).
# Priority: snow > rain > gust (one paper per game; snow is the rarest claim).
# Basis: BACKTESTS.md weather deep-dive (2021-25, n=897 outdoor vs closing totals).
PAPER_RULES = [
    ("snow",   "over",  "snow>0 → OVER (73% historically, n=15 — smallest sample)"),
    ("rain",   "under", "rain>0 → UNDER (~65% historically, n=80)"),
    ("gust20", "under", "gust ≥20 mph → UNDER (60-70% historically, n=290)"),
]


def log_weather_papers(games, season, week, books_by_abbr=None, quiet=True):
    """PAPER TRADE (experimental=1): log a totals lean for every outdoor game
    whose kickoff forecast trips a weather rule (snow → OVER, rain → UNDER,
    gust ≥20 mph → UNDER) and has a REAL books consensus total (books-only
    honesty rule). One paper per game, rule-tagged (paper_rule) for per-rule
    receipts. Graded at close, excluded from the headline record."""
    import weather
    existing = db.existing_pick_keys()
    wk = games[(games["season"] == season) & (games["game_type"] == "REG")
               & (games["week"] == week)]
    books_by_abbr = books_by_abbr or {}
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    new = 0
    for _, g in wk.iterrows():
        if str(g.get("roof", "")).lower() not in ("outdoors", "open"):
            continue
        label = f"{g['away_team']} @ {g['home_team']}"
        if (label, "total") in existing:
            continue  # the model already has an official totals pick on this game
        books = books_by_abbr.get((g["away_team"], g["home_team"])) or {}
        totals = [b["total"] for b in books.values() if b.get("total") is not None]
        if not totals:
            continue
        try:
            gust = weather.kickoff_gust(g.get("stadium"), g.get("gameday"), g.get("gametime"))
            rain, snow = weather.kickoff_precip(g.get("stadium"), g.get("gameday"), g.get("gametime"))
        except Exception:
            continue
        if snow and snow > 0:
            rule, side, val = "snow", "over", round(float(snow), 2)
        elif rain and rain > 0:
            rule, side, val = "rain", "under", round(float(rain), 2)
        elif gust and gust >= GUST_PAPER_MIN:
            rule, side, val = "gust20", "under", round(float(gust), 1)
        else:
            continue
        db.insert_pick({"logged_at": now, "season": season, "week": week, "game": label,
                        "pick_type": "total", "side": side, "model_val": val,
                        "market_val_log": float(pd.Series(totals).median()),
                        "edge_log": None, "p_cover_log": None, "experimental": 1,
                        "paper_rule": rule})
        existing.add((label, "total"))
        new += 1
    if not quiet:
        print(f"logged {new} weather paper trades for {season} W{week}")
    return new


# backward-compat alias (original name when it was gust-only)
def log_gust_papers(games, season, week, books_by_abbr=None, quiet=True):
    return log_weather_papers(games, season, week, books_by_abbr, quiet)


def log_divdog_papers(games, season, week, books_by_abbr=None, quiet=True):
    """PAPER TRADE (experimental=1, paper_rule='divdog'): divisional underdogs
    getting ≤3 points, BOTH teams on normal rest (≥7 days), weeks ≥12 only →
    bet the DOG ATS vs the books consensus line.
    Backtest (2021-25, n=61): dogs cover 68.9%, positive ALL 5 seasons
    (90/60/61/67/73%), z=+2.58; dogs win outright 52.6% in the parent bucket.
    The short-rest variant is DEAD (25-33%) — do NOT widen this rule."""
    if week < 12:
        return 0
    existing = db.existing_pick_keys()
    wk = games[(games["season"] == season) & (games["game_type"] == "REG")
               & (games["week"] == week)]
    books_by_abbr = books_by_abbr or {}
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    new = 0
    for _, g in wk.iterrows():
        if not g.get("div_game"):
            continue
        hr, ar = g.get("home_rest"), g.get("away_rest")
        if pd.isna(hr) or pd.isna(ar) or hr < 7 or ar < 7:
            continue  # short-rest divisional dogs are the DEAD slice
        label = f"{g['away_team']} @ {g['home_team']}"
        if (label, "spread") in existing:
            continue
        books = books_by_abbr.get((g["away_team"], g["home_team"])) or {}
        aways = [b["away_spread"] for b in books.values() if b.get("away_spread") is not None]
        if not aways:
            continue  # books-only honesty rule
        med = float(pd.Series(aways).median())
        if med == 0 or abs(med) > 3:
            continue  # pick'em or real favorite — rule is dogs ≤3 only
        dog, dog_line = (g["away_team"], med) if med > 0 else (g["home_team"], -med)
        db.insert_pick({"logged_at": now, "season": season, "week": week, "game": label,
                        "pick_type": "spread", "side": dog, "model_val": dog_line,
                        "market_val_log": dog_line, "edge_log": None, "p_cover_log": None,
                        "experimental": 1, "paper_rule": "divdog"})
        existing.add((label, "spread"))
        new += 1
    if not quiet:
        print(f"logged {new} divdog paper trades for {season} W{week}")
    return new


def grade_predictions(games):
    """Grade pending picks whose games have results. Returns updated df."""
    picks = db.load_picks()
    for _, p in picks.iterrows():
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
        if p["pick_type"] == "spread":
            if pd.isna(g["spread_line"]):
                continue
            closing = g["spread_line"] if p["side"] == away else -g["spread_line"]
            margin = g["result"] if p["side"] == home else -g["result"]
            diff = margin + closing
        else:
            if pd.isna(g["total_line"]):
                continue
            closing = g["total_line"]
            diff = (g["total"] - g["total_line"]) * (1 if p["side"] == "over" else -1)
        if diff > 0:
            db.grade_pick(p["id"], float(closing), "won", 100 / 110)
        elif diff < 0:
            db.grade_pick(p["id"], float(closing), "lost", -1.0)
        else:
            db.grade_pick(p["id"], float(closing), "push", 0.0)
    return db.load_picks()


def _clean(picks):
    """Picks that count toward the record: excludes flagged (data-quality) rows
    and experimental paper trades (graded separately, never headline)."""
    out = picks[picks["flag"].isna()] if "flag" in picks.columns else picks
    if "experimental" in out.columns:
        out = out[out["experimental"].fillna(0) != 1]
    return out


def summary(picks):
    out = {}
    flagged = int(picks["flag"].notna().sum()) if "flag" in picks.columns else 0
    picks = _clean(picks)
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
    out["flagged"] = flagged
    return out


def edge_buckets(picks):
    picks = _clean(picks)
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
    picks = _clean(picks)
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
