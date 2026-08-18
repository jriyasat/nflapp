"""Morning brief generator. Prints a Telegram-ready digest ONLY when something
notable changed (line movers, injury report changes, model edges, weekly angles).
Empty stdout = silent day. Run via morning_brief.sh (venv python)."""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, "/Users/jeff/nfl-edge")
os.environ.pop("PYTHONPATH", None)

import pandas as pd
import data as dl
import predictor as pr
import weather as wx
import tracker

SNAP_LINES = os.path.join(dl.CACHE, "snap_lines.json")
SNAP_INJ = os.path.join(dl.CACHE, "snap_inj.json")
SNAP_EDGES = os.path.join(dl.CACHE, "snap_edges.json")
SNAP_WEEK = os.path.join(dl.CACHE, "snap_week.json")
SNAP_WX = os.path.join(dl.CACHE, "snap_wx.json")
SNAP_TOTALS = os.path.join(dl.CACHE, "snap_totals.json")
LINE_MOVE_MIN = 1.0
EDGE_MIN = 2.0
STATUS_RANK = {"": 0, "Questionable": 1, "Doubtful": 2, "Out": 3}


def load_snap(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def save_snap(path, obj):
    json.dump(obj, open(path, "w"))


def main():
    games = dl.load_games()
    season, week = dl.current_season_week(games)
    wk = games[(games["season"] == season) & (games["game_type"] == "REG")
               & (games["week"] == week)].sort_values(["gameday", "gametime"])
    if wk.empty:
        return

    sections = []

    # ---- line movers (nflverse current lines for upcoming games) ----
    cur_lines, movers = {}, []
    for _, g in wk.iterrows():
        label = f"{g['away_team']} @ {g['home_team']}"
        if pd.notna(g["spread_line"]):
            cur_lines[label] = {"spread_away": float(g["spread_line"]),
                                "total": float(g["total_line"]) if pd.notna(g["total_line"]) else None}
    old_lines = load_snap(SNAP_LINES)
    if old_lines is not None:
        for label, cur in cur_lines.items():
            old = old_lines.get(label)
            if not old:
                continue
            ds = cur["spread_away"] - (old.get("spread_away") or cur["spread_away"])
            if abs(ds) >= LINE_MOVE_MIN:
                movers.append(f"• {label}: spread {'+' if ds > 0 else ''}{ds:.1f} "
                              f"(now {label.split(' @ ')[0]} {cur['spread_away']:+.1f})")
            ot, ct = old.get("total"), cur.get("total")
            if ot and ct and abs(ct - ot) >= LINE_MOVE_MIN:
                movers.append(f"• {label}: total {ot:.1f} → {ct:.1f}")
    if movers:
        sections.append("📉 *LINE MOVERS*\n" + "\n".join(movers[:8]))
    save_snap(SNAP_LINES, cur_lines)

    # ---- injury report changes (escalations to Questionable/Doubtful/Out) ----
    try:
        nv, status = dl.nflverse_injuries()
    except Exception:
        nv = {}
    cur_inj = {t: {r["name"]: r["status"] for r in e["rows"]} for t, e in nv.items()}
    old_inj = load_snap(SNAP_INJ)
    inj_changes = []
    if old_inj is not None:
        playing = set(wk["away_team"]) | set(wk["home_team"])
        for team, players in cur_inj.items():
            if team not in playing:
                continue
            for name, st in players.items():
                old_st = (old_inj.get(team) or {}).get(name, "")
                if STATUS_RANK.get(st, 0) > STATUS_RANK.get(old_st, 0) and STATUS_RANK.get(st, 0) >= 1:
                    inj_changes.append((STATUS_RANK[st], f"• {team}: {name} — *{st}*"
                                        + (f" (was {old_st})" if old_st else " (new)")))
    if inj_changes:
        inj_changes.sort(reverse=True)
        sections.append("🏥 *INJURY ESCALATIONS*\n" + "\n".join(m for _, m in inj_changes[:10]))
    save_snap(SNAP_INJ, cur_inj)

    # ---- model edges + angles + totals for the week (de-duped vs last brief) ----
    elo = pr.Elo(games)
    # log model picks (>=2pt edges) daily; grade settled picks
    books_by_abbr = {}
    key_path = os.path.join(dl.CACHE, "odds_api_key.txt")
    if os.path.exists(key_path):
        try:
            _key = open(key_path).read().strip()
            if _key:
                raw = dl.odds_api_lines(_key)
                for (an_, hn), books in raw.items():
                    k = (dl.TEAM_NAME_TO_ABBR.get(an_), dl.TEAM_NAME_TO_ABBR.get(hn))
                    if all(k):
                        books_by_abbr[k] = books
        except Exception:
            pass
    tracker.log_predictions(games, elo, season, week, books_by_abbr)
    tracker.grade_predictions(games)
    edges, angles = [], []
    new_edge_snap = {}
    old_tot = load_snap(SNAP_TOTALS) or {}
    new_tot, tot_hits = {}, []
    for _, g in wk.iterrows():
        wind_mph = None
        if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
            wind_mph, _ = wx.wind_for_game(g)
        pred = pr.predict_game(g, elo, wind_mph=wind_mph)
        label = f"{g['away_team']} @ {g['home_team']}"
        if pred.get("model_total") is not None:
            gap = pred["model_total"] - pred["market_total"]
            if abs(gap) >= 1.5:
                new_tot[label] = round(gap, 1)
                prev = old_tot.get(label)
                if prev is None or abs(abs(gap) - abs(prev)) >= 0.75:
                    lean = "UNDER" if gap < 0 else "OVER"
                    ev = pred.get("ev_under" if gap < 0 else "ev_over", 0)
                    tot_hits.append((abs(gap),
                                     f"• {label}: model {pred['model_total']:.1f} vs mkt "
                                     f"{pred['market_total']:.1f} → *{lean}* (EV {ev*100:+.1f}%)"))
        if pred.get("edge_pts") is not None and abs(pred["edge_pts"]) >= EDGE_MIN:
            new_edge_snap[label] = round(pred["edge_pts"], 1)
            side = g["home_team"] if pred["edge_pts"] > 0 else g["away_team"]
            ev = pred.get("ev_home" if pred["edge_pts"] > 0 else "ev_away", 0)
            edges.append((abs(pred["edge_pts"]), label,
                          f"• {label}: model likes *{side}* "
                          f"by {abs(pred['edge_pts']):.1f} pts vs market "
                          f"(EV {ev*100:+.1f}%)"))
        for name, info in pred["angles"]:
            angles.append(f"• {label}: {info['note']} — {info['record']}")
    old_edges = load_snap(SNAP_EDGES) or {}
    fresh = [e for e in edges
             if e[1] not in old_edges or abs(abs(e[0]) - abs(old_edges[e[1]])) >= 0.5]
    if fresh:
        fresh.sort(reverse=True)
        sections.append(f"🎯 *MODEL EDGES — Week {week}*\n" + "\n".join(m for _, _, m in fresh[:6]))
    save_snap(SNAP_EDGES, new_edge_snap)
    if tot_hits:
        tot_hits.sort(reverse=True)
        sections.append("🎚️ *TOTALS LEANS*\n" + "\n".join(m for _, m in tot_hits[:5]))
    save_snap(SNAP_TOTALS, new_tot)

    last_week = load_snap(SNAP_WEEK)
    if angles and last_week != f"{season}-{week}":
        sections.append("📐 *ANGLES THIS WEEK*\n" + "\n".join(angles[:5]))
    save_snap(SNAP_WEEK, f"{season}-{week}")

    # ---- wind alerts (games inside the 16-day forecast window) ----
    old_wx = load_snap(SNAP_WX) or {}
    new_wx, wind_hits = {}, []
    for _, g in wk.iterrows():
        if pd.isna(g["gameday"]) or g["gameday"] > pd.Timestamp.now() + pd.Timedelta(days=15):
            continue
        mph, flag = wx.wind_for_game(g)
        label = f"{g['away_team']} @ {g['home_team']}"
        if flag == "under":
            new_wx[label] = round(mph)
            prev = old_wx.get(label)
            if prev is None or abs(mph - prev) >= 3:
                wind_hits.append(f"• {label}: *{mph:.0f} mph* at kickoff — UNDER angle (60.9%, n=87)")
        else:
            pass  # below threshold: drop from snapshot so a later rise re-alerts
    if wind_hits:
        sections.append("🌬️ *WIND ALERTS*\n" + "\n".join(wind_hits[:5]))
    save_snap(SNAP_WX, new_wx)

    if not sections:
        return
    first = wk.iloc[0]["gameday"]
    kickoff = first.strftime("%a %b %d") if pd.notna(first) else ""
    print(f"🏈 *NFL Edge Morning Brief* — {datetime.now().strftime('%a %b %d')}")
    print(f"Week {week} kicks off {kickoff}\n")
    print("\n\n".join(sections))


if __name__ == "__main__":
    main()
    os._exit(0)  # libsql client threads can hang interpreter shutdown
