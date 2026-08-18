"""Bet journal + CLV tracker. Storage: SQLite via db.py (per-user).
CLV sign convention: positive = you beat the closing number (good)."""

import pandas as pd

import db

BETS_PATH = db.DB_PATH  # backwards-compat reference


def load_bets(user="jeff"):
    return db.load_bets(user)


def save_bet(bet, user="jeff"):
    return db.save_bet(bet, user)


def delete_bet(bet_id, user="jeff"):
    db.delete_bet(bet_id, user)


def american_payout(odds):
    odds = float(odds)
    return 100 / abs(odds) if odds < 0 else odds / 100


def implied(odds):
    odds = float(odds)
    return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)


def _find_game(games, season, week, game_label):
    g = games[(games["season"] == season) & (games["week"] == week) &
              (games["game_type"] == "REG")]
    for _, r in g.iterrows():
        if f"{r['away_team']} @ {r['home_team']}" == game_label:
            return r
    return None


def settle(bets, games, user="jeff"):
    """Update status/profit/clv for any pending bet whose game has finished,
    and refresh CLV for pending bets. Persists each change to the DB."""
    for _, bet in bets.iterrows():
        r = _find_game(games, int(bet["season"]), int(bet["week"]), bet["game"])
        if r is None:
            continue
        sel = bet["selection"]
        btype = bet["bet_type"]
        status, profit, clv = bet["status"], bet.get("profit"), bet.get("clv")
        # ---- CLV (recomputed while pending; locks at close via status change) ----
        if bet["status"] == "pending":
            new_clv = None
            if btype == "spread" and pd.notna(r["spread_line"]):
                closing = -r["spread_line"] if sel == r["home_team"] else r["spread_line"]
                new_clv = round(float(bet["line"]) - closing, 2)
            elif btype == "total" and pd.notna(r["total_line"]):
                closing = r["total_line"]
                new_clv = (round(closing - float(bet["line"]), 2) if sel == "over"
                           else round(float(bet["line"]) - closing, 2))
            elif btype == "ml":
                closing_ml = (r["home_moneyline"] if sel == r["home_team"]
                              else r["away_moneyline"])
                if pd.notna(closing_ml):
                    new_clv = round((implied(closing_ml) - implied(bet["odds"])) * 100, 2)
            if new_clv is not None:
                clv = new_clv
            # ---- grading ----
            if pd.notna(r["result"]):
                margin = r["result"] if sel == r["home_team"] else -r["result"]
                if btype == "spread":
                    diff = margin + float(bet["line"])
                elif btype == "total":
                    diff = (r["total"] - float(bet["line"])) * (1 if sel == "over" else -1)
                else:
                    diff = margin
                stake = float(bet["stake"])
                if diff > 0:
                    status, profit = "won", round(stake * american_payout(bet["odds"]), 2)
                elif diff < 0:
                    status, profit = "lost", -stake
                else:
                    status, profit = "push", 0.0
        if status != bet["status"] or clv != bet.get("clv") or \
                (pd.notna(profit) and profit != bet.get("profit")):
            db.update_bet_result(bet["id"], user, status,
                                 profit if pd.notna(profit) else None,
                                 clv if clv is not None else None)
    return db.load_bets(user)


def summary(bets):
    graded = bets[bets["status"].isin(["won", "lost", "push"])]
    s = {"n": len(bets), "pending": int((bets["status"] == "pending").sum())}
    if len(graded):
        decided = graded[graded["status"] != "push"]
        s["record"] = (f"{int((graded['status']=='won').sum())}-"
                       f"{int((graded['status']=='lost').sum())}-"
                       f"{int((graded['status']=='push').sum())}")
        s["win_pct"] = (decided["status"] == "won").mean() * 100 if len(decided) else 0
        s["profit"] = graded["profit"].astype(float).sum()
        s["staked"] = graded["stake"].astype(float).sum()
        s["roi"] = s["profit"] / s["staked"] * 100 if s["staked"] else 0
    clv = bets[pd.to_numeric(bets["clv"], errors="coerce").notna()].copy()
    if len(clv):
        clv["clv"] = clv["clv"].astype(float)
        s["avg_clv"] = clv["clv"].mean()
        s["beat_close_pct"] = (clv["clv"] > 0).mean() * 100
        s["n_clv"] = len(clv)
    return s
