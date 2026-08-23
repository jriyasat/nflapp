"""Transactional + broadcast email via Resend (https://resend.com).

Config (either env vars or .streamlit/secrets.toml):
    RESEND_API_KEY  — from resend.com dashboard
    RESEND_FROM     — e.g. "NFL Edge <briefs@yourdomain.com>" (domain must be
                      verified in Resend, DKIM/SPF set)

Until both are present, configured() is False and every send is a no-op —
safe to wire into cron before the domain exists.
"""

import html
import os

import requests

_API = "https://api.resend.com/emails"


def _cfg():
    key = os.environ.get("RESEND_API_KEY")
    frm = os.environ.get("RESEND_FROM")
    if not (key and frm):
        try:
            import tomllib
            sp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              ".streamlit", "secrets.toml")
            with open(sp, "rb") as f:
                sec = tomllib.load(f)
            key = key or sec.get("RESEND_API_KEY")
            frm = frm or sec.get("RESEND_FROM")
        except Exception:
            pass
    return key, frm


def configured():
    key, frm = _cfg()
    return bool(key and frm)


def send_email(to, subject, html_body, reply_to=None):
    """Send one email. Returns (ok, error_or_id)."""
    key, frm = _cfg()
    if not (key and frm):
        return False, "email not configured (RESEND_API_KEY / RESEND_FROM missing)"
    payload = {"from": frm, "to": [to], "subject": subject, "html": html_body}
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        r = requests.post(_API, json=payload,
                          headers={"Authorization": f"Bearer {key}"}, timeout=30)
        if r.status_code in (200, 201):
            return True, r.json().get("id", "")
        return False, f"HTTP {r.status_code}: {r.text[:300]}"
    except Exception as e:
        return False, str(e)


def broadcast(recipients, subject, html_body):
    """Send the same email to a list of addresses. Returns (sent, [errors])."""
    sent, errors = 0, []
    for to in recipients:
        ok, info = send_email(to, subject, html_body)
        if ok:
            sent += 1
        else:
            errors.append(f"{to}: {info}")
    return sent, errors


def brief_html(brief_text, footer_note=""):
    """Wrap the Telegram-markdown morning brief in a clean HTML email."""
    body = html.escape(brief_text)
    # light markdown: *bold* -> <b>bold</b> (Telegram-style single stars)
    import re
    body = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", body)
    note = (f'<p style="color:#888;font-size:12px">{html.escape(footer_note)}</p>'
            if footer_note else "")
    return f"""<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:640px">
<div style="white-space:pre-wrap;font-size:14px;line-height:1.5">{body}</div>
<hr style="border:none;border-top:1px solid #ddd;margin:16px 0">
{note}
<p style="color:#aaa;font-size:11px">NFL Edge Finder — for entertainment &amp; informational
purposes only. Not betting advice. 21+. If gambling stops being fun: 1-800-GAMBLER.
Reply to this email to stop the daily brief.</p>
</div>"""
