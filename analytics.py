"""Analytics: H2H history, recent form (ATS/O-U), situational spots."""

import pandas as pd

DIVISIONS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"], "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"], "AFC West": ["DEN", "KC", "LAC", "LV"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"], "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"], "NFC West": ["ARI", "LAR", "SEA", "SF"],
}


def team_stats(games, season):
    """Per-team W-L-T, PF/PA, ATS records for a season (REG).
    ATS vs closing spread (away-perspective): home covers when result - spread_line > 0."""
    reg = games[(games["season"] == season) & (games["game_type"] == "REG")
                & games["result"].notna()]
    stats = {t: {"w": 0, "l": 0, "t": 0, "pf": 0, "pa": 0,
                 "ats_w": 0, "ats_l": 0, "ats_p": 0}
             for ts in DIVISIONS.values() for t in ts}
    for _, g in reg.iterrows():
        h, a = g["home_team"], g["away_team"]
        if h not in stats or a not in stats:
            continue
        res = g["result"]
        hs, as_ = g.get("home_score"), g.get("away_score")
        if pd.notna(hs) and pd.notna(as_):
            stats[h]["pf"] += hs; stats[h]["pa"] += as_
            stats[a]["pf"] += as_; stats[a]["pa"] += hs
        if res > 0:
            stats[h]["w"] += 1; stats[a]["l"] += 1
        elif res < 0:
            stats[a]["w"] += 1; stats[h]["l"] += 1
        else:
            stats[h]["t"] += 1; stats[a]["t"] += 1
        sp = g.get("spread_line")
        if pd.notna(sp):
            margin = res - sp  # home cover margin
            if margin > 0:
                stats[h]["ats_w"] += 1; stats[a]["ats_l"] += 1
            elif margin < 0:
                stats[a]["ats_w"] += 1; stats[h]["ats_l"] += 1
            else:
                stats[h]["ats_p"] += 1; stats[a]["ats_p"] += 1
    return stats


def _winpct(s):
    n = s["w"] + s["l"] + s["t"]
    return (s["w"] + 0.5 * s["t"]) / n if n else 0.0


def playoff_seeds(stats, conf):
    """Seed 1-7 for a conference: division winners by win%, then 3 wildcards."""
    divs = [d for d in DIVISIONS if d.startswith(conf)]
    leaders = [max(DIVISIONS[d], key=lambda t: _winpct(stats[t])) for d in divs]
    leaders.sort(key=lambda t: _winpct(stats[t]), reverse=True)
    seeds = {t: i + 1 for i, t in enumerate(leaders)}
    rest = sorted((t for d in divs for t in DIVISIONS[d] if t not in seeds),
                  key=lambda t: _winpct(stats[t]), reverse=True)
    for i, t in enumerate(rest[:3]):
        seeds[t] = 5 + i
    return seeds

# Team home timezones (for travel/body-clock spots)
TEAM_TZ = {
    "ARI": "MT", "ATL": "ET", "BAL": "ET", "BUF": "ET", "CAR": "ET", "CHI": "CT",
    "CIN": "ET", "CLE": "ET", "DAL": "CT", "DEN": "MT", "DET": "ET", "GB": "CT",
    "HOU": "CT", "IND": "ET", "JAX": "ET", "KC": "CT", "LV": "PT", "LAC": "PT",
    "LA": "PT", "MIA": "ET", "MIN": "CT", "NE": "ET", "NO": "CT", "NYG": "ET",
    "NYJ": "ET", "PHI": "ET", "PIT": "ET", "SF": "PT", "SEA": "PT", "TB": "ET",
    "TEN": "CT", "WAS": "ET",
}
TZ_RANK = {"PT": 0, "MT": 1, "CT": 2, "ET": 3}


def _team_view(row, team):
    """Stats from one team's perspective for a completed game."""
    home = row["home_team"] == team
    pf = row["home_score"] if home else row["away_score"]
    pa = row["away_score"] if home else row["home_score"]
    spread = -row["spread_line"] if home else row["spread_line"]  # team's own line (away-perspective data)
    won = pf > pa
    margin_vs_spread = (pf - pa) + spread
    if pd.isna(row["spread_line"]):
        ats = "-"
    elif margin_vs_spread > 0:
        ats = "COVERED"
    elif margin_vs_spread < 0:
        ats = "NO COVER"
    else:
        ats = "PUSH"
    if pd.isna(row["total_line"]):
        ou = "-"
    elif row["total"] > row["total_line"]:
        ou = "OVER"
    elif row["total"] < row["total_line"]:
        ou = "UNDER"
    else:
        ou = "PUSH"
    opp = row["away_team"] if home else row["home_team"]
    return {
        "date": row["gameday"].strftime("%Y-%m-%d") if pd.notna(row["gameday"]) else "",
        "season": int(row["season"]), "week": int(row["week"]),
        "type": row["game_type"], "opp": opp, "loc": "vs" if home else "@",
        "score": f"{int(pf)}-{int(pa)}",
        "result": "W" if won else ("L" if pf < pa else "T"),
        "line": spread, "total_line": row["total_line"],
        "ats": ats, "ou": ou,
    }


def h2h(df, team_a, team_b, seasons=5):
    """Meetings between two teams over the last N completed seasons."""
    max_season = int(df.loc[df["result"].notna(), "season"].max())
    since = max_season - seasons + 1
    mask = (df["season"] >= since) & df["result"].notna() & (
        ((df["home_team"] == team_a) & (df["away_team"] == team_b)) |
        ((df["home_team"] == team_b) & (df["away_team"] == team_a)))
    games = df[mask].sort_values("gameday", ascending=False)
    rows, summary = [], {team_a: {"w": 0, "ats": 0}, team_b: {"w": 0, "ats": 0},
                       "over": 0, "under": 0, "push": 0, "n": 0}
    for _, g in games.iterrows():
        va = _team_view(g, team_a)
        rows.append({
            "date": va["date"], "matchup": f"{g['away_team']} @ {g['home_team']}",
            "score": f"{int(g['away_score'])}-{int(g['home_score'])}",
            "winner": team_a if va["result"] == "W" else (team_b if va["result"] == "L" else "T"),
            "closing_spread": f"{g['away_team']} {g['spread_line']:+.1f}" if pd.notna(g["spread_line"]) else "-",
            "ats": g.get("ats_winner", "-"), "total_line": g["total_line"],
            "ou": g.get("ou_result", "-"),
        })
        summary["n"] += 1
        if va["result"] == "W":
            summary[team_a]["w"] += 1
        elif va["result"] == "L":
            summary[team_b]["w"] += 1
        if g.get("ats_winner") == "HOME":
            summary[g["home_team"]]["ats"] += 1
        elif g.get("ats_winner") == "AWAY":
            summary[g["away_team"]]["ats"] += 1
        if g.get("ou_result") == "OVER":
            summary["over"] += 1
        elif g.get("ou_result") == "UNDER":
            summary["under"] += 1
        else:
            summary["push"] += 1
    return rows, summary


def last_n(df, team, n=3):
    """Last n completed games (REG + POST) for a team, most recent first."""
    games = df[(df["result"].notna()) & (df["game_type"].isin(["REG", "POST"])) &
               ((df["home_team"] == team) | (df["away_team"] == team))]
    games = games.sort_values("gameday", ascending=False).head(n)
    return [_team_view(g, team) for _, g in games.iterrows()]


def situational_spots(df, game_row):
    """Flags for one upcoming game. Returns list of (label, detail, lean)."""
    spots = []
    away, home = game_row["away_team"], game_row["home_team"]
    ar, hr = game_row.get("away_rest"), game_row.get("home_rest")
    if pd.notna(ar) and pd.notna(hr):
        diff = ar - hr
        if diff >= 3:
            spots.append(("REST EDGE", f"{away} on {int(ar)} days rest vs {home} on {int(hr)}", away))
        elif diff <= -3:
            spots.append(("REST EDGE", f"{home} on {int(hr)} days rest vs {away} on {int(ar)}", home))
        if min(ar, hr) <= 5:
            spots.append(("SHORT WEEK", f"Both teams on short rest ({int(ar)}/{int(hr)} days) -- sloppy-game angles", None))
    if game_row.get("div_game") == 1:
        spots.append(("DIVISION GAME", "Divisional dogs historically cover more often", away))
    wd = str(game_row.get("weekday", ""))
    if wd.lower().startswith("thu"):
        spots.append(("THURSDAY NIGHT", "TNF: totals and favorites behave differently on short weeks", None))
    # Body-clock spot: Pacific team playing early (1pm ET) on East Coast
    away_tz, home_tz = TZ_RANK.get(TEAM_TZ.get(away)), TZ_RANK.get(TEAM_TZ.get(home))
    gt = str(game_row.get("gametime", ""))
    try:
        hour = int(gt.split(":")[0]) if gt and gt != "nan" else None
    except ValueError:
        hour = None
    if away_tz is not None and home_tz is not None and hour is not None:
        hops = home_tz - away_tz  # >0 = traveling east
        if hops >= 2 and hour <= 13:
            spots.append(("BODY CLOCK", f"{away} (West) playing {gt} ET on East Coast -- slow-start angle", home))
        elif hops <= -3 and hour >= 20:
            spots.append(("BODY CLOCK", f"{away} (East) in late/west window -- prime-time travel angle", home))
    # Division on deck (lookahead): next game is divisional, this one isn't
    if game_row.get("div_game") != 1:
        for team in (away, home):
            nxt = _next_game(df, team, game_row)
            if nxt is not None and nxt.get("div_game") == 1:
                spots.append(("LOOKAHEAD?", f"{team} has a division game on deck", _opp(team, game_row)))
    # Key numbers: 14.6% of NFL games land on 3, 8.7% on 7 (2015-25, n=2,895)
    sp = game_row.get("spread_line")
    if pd.notna(sp):
        a = abs(sp)
        if 2.5 <= a <= 3.5:
            spots.append(("🔑 KEY NUMBER", "Line sits on the 3 — 14.6% of games land exactly on 3. The half point is worth real money: shop both sides.", None))
        elif 6.5 <= a <= 7.5:
            spots.append(("🔑 KEY NUMBER", "Line sits on the 7 — 8.7% of games land exactly on 7. The half point is worth real money: shop both sides.", None))
    return spots


def _next_game(df, team, after_row):
    fut = df[(df["result"].isna()) & (df["game_type"] == "REG") &
             ((df["home_team"] == team) | (df["away_team"] == team)) &
             (df["gameday"] > after_row["gameday"])].sort_values("gameday")
    return fut.iloc[0] if len(fut) else None


def _opp(team, game_row):
    return game_row["home_team"] if game_row["away_team"] == team else game_row["away_team"]


def line_shopping(books):
    """Best available price per market across books.

    books: {book_key: {home_spread, home_spread_price, total, over_price, home_ml, away_ml, ...}}
    Returns dict of best offers + whether books disagree on the number.
    """
    best = {}
    spreads, totals = set(), set()
    for bk, e in books.items():
        if e.get("home_spread") is not None:
            spreads.add(e["home_spread"])
        if e.get("total") is not None:
            totals.add(e["total"])
    # spread: best = highest point for the side you take, then best price
    for side in ("home", "away"):
        cands = [(e.get(f"{side}_spread"), e.get(f"{side}_spread_price"), bk)
                 for bk, e in books.items() if e.get(f"{side}_spread") is not None]
        if cands:
            pt, price, bk = max(cands, key=lambda c: (c[0], -abs(c[1] or -110)))
            best[f"{side}_spread"] = {"point": pt, "price": price, "book": bk}
    for ou in ("over", "under"):
        cands = [(e.get("total"), e.get(f"{ou}_price"), bk)
                 for bk, e in books.items() if e.get("total") is not None and e.get(f"{ou}_price") is not None]
        if cands:
            key = (min if ou == "over" else max)
            pt, price, bk = key(cands, key=lambda c: c[0])
            best[ou] = {"point": pt, "price": price, "book": bk}
    for side in ("home", "away"):
        cands = [(e.get(f"{side}_ml"), bk) for bk, e in books.items() if e.get(f"{side}_ml") is not None]
        if cands:
            ml, bk = max(cands, key=lambda c: c[0])
            best[f"{side}_ml"] = {"price": ml, "book": bk}
    best["books_disagree"] = len(spreads) > 1 or len(totals) > 1
    return best
