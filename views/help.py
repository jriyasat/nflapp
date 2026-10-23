"""
Help and terms pages.
"""
import streamlit as st

# ---------- help page ----------
def help_page(ctx):
    st.header("❓ How the Predictor Works")
    st.caption("The short version of what every number on the Predictor tab means.")

    st.subheader("🤖 Model line")
    st.markdown(
        "The model's **fair spread** for the game. It's built from three parts: "
        "**85%** the de-vigged consensus of every sportsbook, **15%** our Elo ratings, "
        "plus small backtest-proven adjustments (injuries, rest). "
        "*Example: 'SEA -3.4' means the model thinks Seattle should be favored by 3.4 points.*"
    )

    st.subheader("📚 Market")
    st.markdown(
        "The number the **sportsbooks are actually dealing** right now. The arrow note "
        "beneath tells you the source: **'9 book(s)'** = the median of 9 live books; "
        "**'nflverse current line'** = the reference line when live books aren't loaded. "
        "The market is the toughest opponent in sports betting — the model never fades it without a reason."
    )

    st.subheader("⚡ Edge")
    st.markdown(
        "**Model minus market, in points**, for the team named. "
        "**'within noise'** = the gap is under 1.5 points — ordinary disagreement, ignore it. "
        "**'value'** = the gap is 1.5+ — the model genuinely disagrees with the books. "
        "*Example: 'Edge 2.3 CAR' = the model likes Carolina 2.3 points more than the market does.*"
    )

    st.subheader("🎚️ Model total")
    st.markdown(
        "The model's fair **combined-points** line: the market total plus validated "
        "adjustments (wind, tight spreads, early season, referee). The note beneath — "
        "*'mkt 44.0 → UNDER 1.0'* — means the model's number is 1.0 lower than the market's, "
        "so the lean is UNDER by 1.0 point."
    )

    st.subheader("💰 When is a bet suggested?")
    st.markdown("""\
- **Only when EV is positive** — the edge beats the book's cut (the vig). That's the whole game.
- **≥2 pts** → the Edge card flips to **'value'**, the board shows ★, **and** it's logged as an official model pick on the 📈 Track Record page, graded at the closing line. One number, everywhere.
- **Stake** → the ¼-Kelly column (a fraction of your bankroll)
- **Everything else → NO BET.** Most games are no-bets. That's discipline, not a bug.
""")

    st.subheader("📐 What is Elo, anyway?")
    st.markdown("""\
Elo is a **power rating** — one number per team. The whole idea: **the gap between two
teams' ratings predicts who wins.** A team rated 100 points higher wins about 64% of the
time; 200 points higher, about 76%. Ratings move after every game: win and you take points
from your opponent — beat a *good* team and you take more, lose to a *bad* team and you lose more.

**The actual math (one line each, promise):**

- **Win chance:** `1 / (1 + 10^(-(rating gap + home bonus)/400))`
  *Example: Seattle (1703) at home vs a 1550 team → gap 153 + 48 home bonus = 201 → ~76% win chance.*
- **Update after the game:** `new rating = old + 20 × (actual result − expected)`, scaled by margin
  *Seattle wins as a 76% favorite: +20 × (1 − 0.76) ≈ +5 points. Barely moves — it was expected.
  If they'd LOST: −20 × 0.76 ≈ −15. Upsets move ratings; chalk doesn't.*

**Our version, specifically:** home field is worth ~48 Elo points (≈2 points of spread),
winning big counts more (with a dampener so running it up doesn't), and every offseason
ratings pull one-third of the way back to average (1500) — rosters change, so last year
only counts so much.

**The honest part:** Elo alone picked 51.1% against the closing line over 5 seasons — below
breakeven. That's exactly why it's only 15% of our model: a smart prior, not the prediction.
""")

    st.subheader("📺 45-second video version")
    vcol, _ = st.columns([3, 2])
    with vcol:
        st.video("https://www.youtube.com/watch?v=VXGviaMi03E")

    st.subheader("🗺️ The diagrams")
    GH = "https://jriyasat.github.io/nflapp"
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"[![Data map]({GH}/data-map-preview.png)]({GH}/data-map.html)")
        st.caption("⤴ Data map — click to open the full interactive version")
    with d2:
        st.markdown(f"[![Model pipeline]({GH}/model-diagram-preview.png)]({GH}/model-diagram.html)")
        st.caption("⤴ Model pipeline — click to open the full interactive version")

    st.caption("Want the deep dive with backtest numbers? Click the ❓ next to 'Model line' on any Predictor tab.")


# ---------- terms constant ----------
TERMS_MD = """\
**Last updated: August 2026**

**1. What this is.** NFL Edge Finder ("the Service") is an analytics and entertainment
tool that displays publicly available sports data, statistical models, and historical
backtest results. It is **not** a sportsbook: we do not accept, place, or settle wagers
of any kind.

**2. Entertainment & informational purposes only.** Nothing in the Service — predictions,
"edges," projections, suggested stakes, or any other content — constitutes financial,
investment, or legal advice, or a recommendation to place any bet. Sports outcomes are
inherently uncertain; **past performance (including backtests) does not guarantee future
results.** You can lose money. Any betting decision you make is yours alone.

**3. 21+ only.** The Service is intended for users aged 21 or older. By using it you
represent that you are 21+ and that sports betting is legal in your jurisdiction. You are
solely responsible for complying with the laws where you live.

**4. No warranty.** The Service is provided **"as is" and "as available,"** with no
warranties of any kind, express or implied — including accuracy, completeness, uptime,
or fitness for a particular purpose. Data feeds (odds, injuries, weather) come from third
parties and may be delayed, wrong, or unavailable.

**5. Limitation of liability.** To the maximum extent permitted by law, the Service and
its operator(s) are not liable for any losses — including gambling losses, lost profits,
or indirect/consequential damages — arising from use of, or inability to use, the Service.
If you are a paying subscriber, total liability is capped at the amount you paid in the
3 months before the claim.

**6. Responsible gambling.** Bet only what you can afford to lose. If gambling stops
being fun, help is available 24/7: **call or text 1-800-GAMBLER** (US National Problem
Gambling Helpline) or visit ncpgambling.org.

**7. Accounts.** You are responsible for keeping your password confidential and for
activity under your account. We may suspend accounts that abuse the Service (sharing
logins, scraping, reselling access).

**8. Changes.** We may update these terms; continued use after changes means acceptance.
The "last updated" date above always reflects the current version.

**9. Contact.** Questions about these terms: jeff.riyasat@gmail.com.
"""


# ---------- terms page ----------
def terms_page(ctx):
    st.header("📜 Terms of Use & Disclaimer")
    st.markdown(TERMS_MD)