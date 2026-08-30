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
import db
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


def recap_sections(games, season, journal_user=None):
    """Monday recap: last week's graded model picks + optional user journal.
    Returns (model_sections, user_sections)."""
    import journal
    done = games[(games.season == season) & games.result.notna() & (games.game_type == "REG")]
    if done.empty:
        return [], []
    lw = int(done.week.max())
    picks = tracker.load_picks()
    model_out, user_out = [], []
    if not picks.empty:
        wk = picks[(picks.season == season) & (picks.week == lw) & picks.grade.isin(["won", "lost", "push"])]
        if not wk.empty:
            w = int((wk.grade == "won").sum()); l = int((wk.grade == "lost").sum())
            p = int((wk.grade == "push").sum()); prof = wk.profit.fillna(0).sum()
            lines = [f"*Week {lw} model: {w}-{l}-{p} ({prof:+.2f}u)*"]
            for _, r in wk.iterrows():
                mark = {"won": "✅", "lost": "❌", "push": "➖"}[r.grade]
                lines.append(f"{mark} {r.game}: {r.side} ({r.pick_type})")
            s = tracker.summary(picks)
            if s["n"]:
                lines.append(f"Season: *{s['wins']}-{s['losses']}-{s['pushes']} ({s['profit']:+.2f}u, {s['roi']:+.1f}% ROI)*")
            model_out.append("📅 *MONDAY RECAP — model*\n" + "\n".join(lines))
    if journal_user:
        bets = journal.settle(journal.load_bets(journal_user), games, journal_user)
        wk_b = bets[(bets.season == season) & (bets.week == lw) & bets.status.isin(["won", "lost", "push"])]
        if not wk_b.empty:
            w = int((wk_b.status == "won").sum()); l = int((wk_b.status == "lost").sum())
            prof = wk_b.profit.fillna(0).sum()
            lines = [f"*Week {lw}: {w}-{l} ({prof:+.2f}u)*"]
            for _, r in wk_b.iterrows():
                mark = {"won": "✅", "lost": "❌", "push": "➖"}[r.status]
                clv = f" · CLV {r.clv:+.1f}" if pd.notna(r.get("clv")) and r.get("clv") != "" else ""
                lines.append(f"{mark} {r.game} {r.selection} {r.line:+g}{clv}")
            user_out.append(f"📒 *{journal_user}'s journal*\n" + "\n".join(lines))
    # pick'em: last week's results + season standings (shared section)
    try:
        wk_p = db.load_pickem_week(season, lw)
        if not wk_p.empty:
            graded = wk_p[wk_p["grade"].isin(["won", "lost", "push"])]
            if not graded.empty:
                per_user = {}
                for _, r in graded.iterrows():
                    w_, l_, p_ = per_user.get(r["user"], (0, 0, 0))
                    per_user[r["user"]] = (w_ + (r["grade"] == "won"),
                                           l_ + (r["grade"] == "lost"),
                                           p_ + (r["grade"] == "push"))
                wk_lines = [f"• {u}: {w}-{l}-{p}" for u, (w, l, p) in
                            sorted(per_user.items(), key=lambda kv: -kv[1][0])]
                lb = db.pickem_leaderboard(season)
                lb_txt = ", ".join(f"{r['user']} {r['record']}" for r in lb)
                model_out.append("🏆 *PICK'EM — last week*\n" + "\n".join(wk_lines)
                                 + f"\nSeason: {lb_txt}")
    except Exception:
        pass
    return model_out, user_out


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
    today_s = datetime.now().strftime("%Y-%m-%d")
    for label, cur in cur_lines.items():
        try:
            db.append_line_history(label, cur.get("spread_away"), cur.get("total"), today_s)
        except Exception:
            pass

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
    try:
        espn_odds = dl.espn_week_odds(season, week)
    except Exception:
        espn_odds = {}
    tracker.log_predictions(games, elo, season, week, books_by_abbr, espn_odds, nv)
    tracker.grade_predictions(games)
    try:
        for w in range(1, week + 1):
            db.grade_pickem(games, season, w)
    except Exception:
        pass
    edges, angles = [], []
    model_cands = []
    new_edge_snap = {}
    old_tot = load_snap(SNAP_TOTALS) or {}
    new_tot, tot_hits = {}, []
    for _, g in wk.iterrows():
        wind_mph = None
        if pd.notna(g["gameday"]) and g["gameday"] <= pd.Timestamp.now() + pd.Timedelta(days=15):
            wind_mph, _ = wx.wind_for_game(g)
        pred = pr.predict_game(g, elo, books=books_by_abbr.get((g["away_team"], g["home_team"])),
                               espn=espn_odds.get((g["away_team"], g["home_team"])),
                               injuries=nv, wind_mph=wind_mph)
        label = f"{g['away_team']} @ {g['home_team']}"
        if pred.get("edge_pts") is not None and pd.notna(g["spread_line"]):
            side_t = g["home_team"] if pred["edge_pts"] > 0 else g["away_team"]
            t_line = -float(g["spread_line"]) if pred["edge_pts"] > 0 else float(g["spread_line"])
            model_cands.append((abs(pred["edge_pts"]), label, side_t, t_line))
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

    # 🤖 model enters pick'em: top-5 edge games, once per week
    try:
        if db.load_pickem("model", season, week).empty and model_cands:
            model_cands.sort(reverse=True)
            for _, lbl, team, tl in model_cands[:5]:
                db.save_pickem("model", season, week, lbl, team, tl)
    except Exception:
        pass

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

    # ---- Monday recap edition ----
    is_monday = pd.Timestamp.now().weekday() == 0
    model_rec, jeff_rec = [], []
    if is_monday:
        model_rec, jeff_rec = recap_sections(games, season, journal_user="jeff")

    if not sections and not (model_rec or jeff_rec):
        return
    first = wk.iloc[0]["gameday"]
    kickoff = first.strftime("%a %b %d") if pd.notna(first) else ""
    today = datetime.now().strftime("%a %b %d")
    header = f"🏈 *NFL Edge Morning Brief* — {today}\nWeek {week} kicks off {kickoff}\n"
    full = header + "\n" + "\n\n".join(model_rec + jeff_rec + sections)
    print(full)

    # ---- fan-out to opted-in users (email + telegram DMs); each gets THEIR recap ----
    try:
        sys.path.insert(0, "/Users/jeff/nfl-edge")
        import emailer
        import notify
        for u in db.list_users():
            try:
                if u["username"] == "jeff":
                    urec = jeff_rec
                elif is_monday:
                    _, urec = recap_sections(games, season, journal_user=u["username"])
                else:
                    urec = []
                user_full = header + "\n" + "\n\n".join(model_rec + urec + sections)
                # email brief is a Pro feature (admin/paid only)
                if (u.get("email_enabled") and u.get("email")
                        and u.get("level", "user") in ("admin", "paid")):
                    emailer.send_email(u["email"], f"NFL Edge Brief — {today}",
                                       emailer.brief_html(user_full))
                if u.get("telegram_enabled") and u.get("telegram_chat_id"):
                    notify.send_telegram(u["telegram_chat_id"], user_full)
            except Exception:
                continue
    except Exception:
        pass

    # ---- cross-post to the public channel (growth funnel) ----
    try:
        import notify as _notify
        chan = _notify._env("NFL_PUBLIC_CHANNEL")
        if chan:
            _notify.send_telegram(chan, full)
    except Exception:
        pass


if __name__ == "__main__":
    main()
    os._exit(0)  # libsql client threads can hang interpreter shutdown
