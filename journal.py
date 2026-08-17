"""Bet journal + CLV (closing line value) tracker.

Storage: data/bets.csv. Auto-grades settled bets and computes CLV vs nflverse
closing lines (spread_line/total_line/moneylines are final pregame numbers).

CLV sign convention: positive = you beat the closing number (good).
  spread (team perspective): taken - closing   (took -3, closed -3.5 -> +0.5)
  total over:  closing - taken   (took o47.5, closed 48.5 -> +1.0)
  total under: taken - closing
  ML: implied_prob(closing) - implied_prob(taken), in percentage points
"""

import os
import uuid

import pandas as pd

BETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bets.csv")

COLUMNS = ["id", "date", "season", "week", "game", "bet_type", "selection",
           "line", "odds", "stake", "book", "status", "profit", "clv"]


def load_bets():
    if os.path.exists(BETS_PATH):
        return pd.read_csv(BETS_PATH)
    return pd.DataFrame(columns=COLUMNS)


def save_bet(bet):
    bets = load_bets()
    bet = dict(bet)
    bet["id"] = uuid.uuid4().hex[:8]
    bet.setdefault("status", "pending")
    bet.setdefault("profit", "")
    bet.setdefault("clv", "")
    bets = pd.concat([bets, pd.DataFrame([bet])], ignore_index=True)
    bets.to_csv(BETS_PATH, index=False)
    return bet["id"]


def delete_bet(bet_id):
    bets = load_bets()
    bets = bets[bets["id"] != bet_id]
    bets.to_csv(BETS_PATH, index=False)


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


def grade_and_clv(bets, games):
    """Update status/profit/clv for any bet whose game has finished. Returns bets."""
    for i, bet in bets.iterrows():
        r = _find_game(games, int(bet["season"]), int(bet["week"]), bet["game"])
        if r is None:
            continue
        sel = bet["selection"]          # home/away/over/under team abbr for spread/ml
        btype = bet["bet_type"]
        # ---- CLV (only needs closing lines) ----
        if pd.isna(bet.get("clv")) or bet.get("clv") == "" or bet["status"] == "pending":
            clv = None
            if btype == "spread" and pd.notna(r["spread_line"]):
                closing = -r["spread_line"] if sel == r["home_team"] else r["spread_line"]
                clv = round(float(bet["line"]) - closing, 2)
            elif btype == "total" and pd.notna(r["total_line"]):
                closing = r["total_line"]
                clv = round(closing - float(bet["line"]), 2) if sel == "over" else round(float(bet["line"]) - closing, 2)
            elif btype == "ml":
                closing_ml = r["home_moneyline"] if sel == r["home_team"] else r["away_moneyline"]
                if pd.notna(closing_ml):
                    clv = round((implied(closing_ml) - implied(bet["odds"])) * 100, 2)
            if clv is not None:
                bets.at[i, "clv"] = clv
        # ---- grading (needs final score) ----
        if bet["status"] == "pending" and pd.notna(r["result"]):
            margin = r["result"] if sel == r["home_team"] else -r["result"]
            if btype == "spread":
                diff = margin + float(bet["line"])
            elif btype == "total":
                diff = (r["total"] - float(bet["line"])) * (1 if sel == "over" else -1)
            else:  # ml
                diff = margin
            stake = float(bet["stake"])
            if diff > 0:
                bets.at[i, "status"] = "won"
                bets.at[i, "profit"] = round(stake * american_payout(bet["odds"]), 2)
            elif diff < 0:
                bets.at[i, "status"] = "lost"
                bets.at[i, "profit"] = -stake
            else:
                bets.at[i, "status"] = "push"
                bets.at[i, "profit"] = 0.0
    return bets


def settle(bets, games):
    out = grade_and_clv(bets, games.copy())
    out.to_csv(BETS_PATH, index=False)
    return out


def summary(bets):
    graded = bets[bets["status"].isin(["won", "lost", "push"])]
    s = {"n": len(bets), "pending": int((bets["status"] == "pending").sum())}
    if len(graded):
        decided = graded[graded["status"] != "push"]
        s["record"] = f"{int((graded['status']=='won').sum())}-{int((graded['status']=='lost').sum())}-{int((graded['status']=='push').sum())}"
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
