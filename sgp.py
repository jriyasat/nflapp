"""SGP (same-game parlay) correlation finder.

Empirical lifts from 2024-25 REG team-games (scripts/sgp_analysis.py, n=544):
  joint P(A&B) vs naive P(A)*P(B). A lift of 1.17 means the combo hits 17%
  more often than independence implies -- if the book prices the SGP as if
  legs were independent (or under-adjusts), that's the +EV pocket.

Honest framing: books DO adjust SGP prices for correlation. This tool computes
fair odds so the user can compare against the book's actual SGP price.
"""

import math

LIFTS = {
    ("qb_over", "wr_over"): {"lift": 1.099, "n": 544},
    ("qb_over", "game_over"): {"lift": 1.171, "n": 544},
    ("qb_over", "covers"): {"lift": 1.029, "n": 544},
    ("rb_over", "covers"): {"lift": 1.149, "n": 544},
    ("rb_over", "wins"): {"lift": 1.197, "n": 544},
    ("covers", "game_over"): {"lift": 0.997, "n": 544},
    ("wins", "game_over"): {"lift": 0.997, "n": 544},
    ("wr_over", "game_over"): {"lift": 1.062, "n": 544},
}
# symmetric lookup
LIFTS_SYMM = {}
for (a, b), v in LIFTS.items():
    LIFTS_SYMM[(a, b)] = v
    LIFTS_SYMM[(b, a)] = v

SD_RATIO = {"pass": 0.33, "rush": 0.61, "rec_yds": 0.57, "rec": 0.50}
PROP_LABEL = {"pass": "pass yds", "rush": "rush yds", "rec_yds": "rec yds", "rec": "receptions"}


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def leg_prob(proj, line, kind):
    sd = max(SD_RATIO[kind] * proj, 1.0)
    return _phi((proj - line) / sd)


def build_legs(projs_with_edges, pred, home, away):
    """All candidate legs for a game with probabilities.

    Returns list of {id, kind, label, p} where kind keys into LIFTS.
    """
    legs = []
    # role kinds are stat-specific: lifts were measured on these exact combos
    ROLE_FOR = {("QB", "proj_pass"): "qb_over",
                ("RB", "proj_rush"): "rb_over",
                ("WR", "proj_rec_yds"): "wr_over",
                ("TE", "proj_rec_yds"): "wr_over"}
    for pl in projs_with_edges:
        pos = pl["pos"]
        for col, e in (pl.get("edges") or {}).items():
            kind = {"proj_pass": "pass", "proj_rush": "rush",
                    "proj_rec_yds": "rec_yds", "proj_rec": "rec"}.get(col)
            role = ROLE_FOR.get((pos, col))
            if not kind or not role:
                continue  # no empirical lift measured for this stat/role combo
            p_over = leg_prob(pl[col], e["line"], kind)
            legs.append({
                "id": f"{pl['player']}|{kind}", "kind": role, "team": pl["team"],
                "label": f"{pl['player']} over {e['line']} {PROP_LABEL[kind]}",
                "side": "over", "p": p_over, "proj": pl[col], "line": e["line"],
            })
    # game-level legs from predictor (when market posted)
    if pred.get("p_home_cover") is not None:
        for team, p in ((home, pred["p_home_cover"]), (away, 1 - pred["p_home_cover"])):
            legs.append({"id": f"{team}|covers", "kind": "covers", "team": team,
                         "label": f"{team} covers {fmt_line(pred, home, away)}",
                         "side": "covers", "p": p})
        if pred.get("p_market") is not None:
            for team, p in ((home, pred["p_market"]), (away, 1 - pred["p_market"])):
                legs.append({"id": f"{team}|wins", "kind": "wins", "team": team,
                             "label": f"{team} wins (ML)", "side": "wins", "p": p})
    if pred.get("market_total"):
        p_over = pred.get("p_over", 0.5)  # totals model when available, else coin flip
        legs.append({"id": "game|over", "kind": "game_over", "team": None,
                     "label": f"Game OVER {pred['market_total']:.1f}",
                     "side": "over", "p": p_over})
    return legs


def compatible(a, b):
    """True if the empirical lift for this pair applies (same-team rules)."""
    pair = {a["kind"], b["kind"]}
    if pair == {"qb_over", "wr_over"}:
        return a["team"] == b["team"]
    if pair in ({"qb_over", "covers"}, {"qb_over", "wins"},
                {"rb_over", "covers"}, {"rb_over", "wins"}):
        return a["team"] == b["team"]
    return True  # game-over pairs, covers/wins + game_over: measured game-wide


def fmt_line(pred, home, away):
    sp = pred.get("market_spread")
    return f"(line {home} {sp:+.1f})" if sp is not None else ""


def best_combos(legs, top_n=6):
    """Rank 2-leg combos by correlation-adjusted value."""
    combos = []
    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            a, b = legs[i], legs[j]
            if a["id"].split("|")[0] == b["id"].split("|")[0]:
                continue  # same subject
            if not compatible(a, b):
                continue
            lift_info = LIFTS_SYMM.get((a["kind"], b["kind"]))
            if not lift_info:
                continue
            naive = a["p"] * b["p"]
            adj = min(naive * lift_info["lift"], min(a["p"], b["p"]) * 0.98)
            if naive <= 0:
                continue
            fair_dec = 1 / adj
            naive_dec = 1 / naive
            edge_score = adj / naive * (1 + abs(a["p"] - 0.5) + abs(b["p"] - 0.5))
            combos.append({
                "legs": (a, b), "lift": lift_info["lift"], "n": lift_info["n"],
                "p_joint": adj, "fair_dec": fair_dec, "naive_dec": naive_dec,
                "fair_american": dec_to_american(fair_dec),
                "naive_american": dec_to_american(naive_dec),
                "score": edge_score,
            })
    combos.sort(key=lambda c: -c["score"])
    return combos[:top_n]


def dec_to_american(dec):
    if dec <= 1:
        return 0
    return round(-100 / (dec - 1)) if dec < 2 else round((dec - 1) * 100)
