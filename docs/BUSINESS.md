# NFL Edge Finder — Business Roadmap

*Created Aug 22, 2026. Decisions log + build order for turning the app into a paid subscription product.*

## Decisions locked in (Aug 22)

| Decision | Choice |
|---|---|
| Payments | **Manual first** (Venmo/Zelle + admin flips user to `paid`), then **Lemon Squeezy** (~5%+50¢, merchant-of-record handles sales tax) once ~10 strangers have paid |
| Scale target | Build for the **50–200 user** tier; don't pay 200+ complexity tax yet. Sunday 12:30–1PM ET is the load spike to design for |
| Pricing | Freemium funnel: free tier + monthly ($15–25) + season pass ($99–129 Aug–Super Bowl) |
| Tier split | **Free:** Predictor, Lines, Form, H2H, Injuries, News, Standings, Pick'em. **Pro:** Props, SGP, Bet Journal+CLV, daily email brief |
| Upgrade CTA | "Contact us" only — no public pricing while payments are manual |
| Keith & Shane | Grandfathered as `paid` forever (done Aug 22) |
| Email | Resend (free tier, 100/day) + purchased sending domain |
| Disclaimer | Generic US (no state governing-law clause), 21+, 1-800-GAMBLER |

## Shipped (Aug 24 update)

- ✅ **Email is LIVE via Gmail SMTP** (`emailer.py` auto-selects: Resend if configured, else Gmail app password — already in secrets). Daily brief emails, inactives alerts, and the 📣 broadcast form all work today. Jeff opted in (jeff.riyasat@gmail.com). Brief fan-out now enforces the Pro tier (admin/paid only).
- Domain + Resend remains the **deliverability upgrade path** for when the list grows (below) — no longer a blocker.

## Shipped (Aug 22)

- ✅ **📜 Terms page** — full Terms of Use & Disclaimer (entertainment-only, 21+, liability cap, responsible gambling) + persistent sidebar footer on every page
- ✅ **Tier system** — `user` (free) / `paid` (⭐ pro) / `admin` levels in the users table; Props tab, SGP tab, Bet Journal, and email-brief opt-in gated behind Pro with a "contact us" upgrade wall; sidebar shows tier badge
- ✅ **Email plumbing** — `emailer.py` (Resend REST, safe no-op until configured), `scripts/send_brief_emails.py` (emails the morning brief to opted-in Pro users, runs after the Telegram brief in the 8 AM cron), 📣 broadcast form on the 👥 Users admin page
- ✅ **Admin: level management** — per-user level dropdown on 👥 Users (last-admin demote protected); new-user form defaults to `paid`

## Roadmap — not built yet

### 1. Admin console completion (user mgmt+)
*Why second: needed at ~10 users, not at 3.*
Already have: add/delete users, reset passwords, set levels, broadcast email.
Still needed:
- **Invite codes** — self-serve signup link with a code (you text the code; they register themselves). Removes you hand-creating every account.
- **Usage visibility** — last-login + prop-load counts per user on 👥 Users page (data already in `usage_counters`).
- **Paid-until date** — `paid_until` column so manual Venmo subs auto-expire; cron demotes expired `paid` → `user`.

### 5. Lemon Squeezy checkout + webhook
*Trigger: only after ~10 people have paid manually.*
- Product + monthly/season-pass variants in Lemon Squeezy dashboard
- Webhook endpoint (small FastAPI/Flask sidecar on the Mac, or Streamlit webhook component): `subscription_created` → set level `paid` + paid_until; `subscription_cancelled/expired` → demote to `user`
- Checkout link replaces "contact us" on the upgrade wall
- They will ask for the Terms/disclaimer page during store review — already shipped ✅

### 6. Revenue & subscriber dashboard
*Last — until payments are automated it's a number you already know.*
- Admin page: MRR, active subs by tier, churn, email-brief engagement
- Data source: Lemon Squeezy API (or manual count until #5)

## Email setup walkthrough (do this to turn on #email)

1. **Buy the domain** (~$10–12/yr): Namecheap or Cloudflare — grab `nfledge.app` or similar. Cloudflare is preferred (free DNS, no upsells).
2. **Resend account** (free, 100 emails/day): resend.com → sign up with jeff.riyasat@gmail.com.
3. **Add domain in Resend** → Domains → Add. It shows DNS records (DKIM TXT, SPF TXT, optional MX for replies).
4. **Paste records into Cloudflare/Namecheap DNS** → wait for Resend to show "Verified" (usually minutes).
5. **API key** → Resend → API Keys → Create (send permission only).
6. **Add to secrets** — `.streamlit/secrets.toml` locally AND Streamlit Cloud dashboard:
   ```toml
   RESEND_API_KEY = "re_..."
   RESEND_FROM = "NFL Edge <briefs@yourdomain.com>"
   ```
7. **Test**: 👥 Users page → save your email in ⚙️ Settings, enable the brief → run
   `env -u PYTHONPATH .venv/bin/python scripts/send_brief_emails.py` — or use the 📣 broadcast form.
8. Broadcast form unlocks on the 👥 Users page automatically once secrets exist.

*Until then: everything email-related is a safe silent no-op (broadcast form shows a "not configured" note). Log of brief sends: `data/email_brief.log`.*

## Legal note

The Terms page is the minimum viable cover. Before the first stranger pays: read it once end-to-end and confirm you're comfortable. Consider an LLC once revenue is real (separates personal liability). This is not legal advice — if subscriber count or revenue gets serious, a one-hour consult with a small-business attorney is worth it.
