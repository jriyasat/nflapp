"""Transactional + broadcast email. Two transports, auto-selected:

1. Resend (https://resend.com) — preferred once a sending domain exists:
   RESEND_API_KEY + RESEND_FROM (env or .streamlit/secrets.toml)
2. Gmail SMTP — works today, no domain needed:
   GMAIL_USER + GMAIL_APP_PASSWORD (env, ~/.hermes/.env, or secrets.toml)

configured() is True if EITHER transport has credentials. Gmail is fine at
small scale (~500/day); move to Resend for deliverability as the list grows.
"""

import html
import os
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

_API = "https://api.resend.com/emails"
_SECRETS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ".streamlit", "secrets.toml")
_HERMES_ENV = os.path.expanduser("~/.hermes/.env")


def _secret(name):
    v = os.environ.get(name)
    if v:
        return v
    try:
        for line in open(_HERMES_ENV):
            line = line.strip()
            if line.startswith(name + "=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    try:
        import tomllib
        with open(_SECRETS, "rb") as f:
            return tomllib.load(f).get(name)
    except Exception:
        pass
    return None


def _cfg():
    return _secret("RESEND_API_KEY"), _secret("RESEND_FROM")


def _gmail_cfg():
    return _secret("GMAIL_USER"), _secret("GMAIL_APP_PASSWORD")


def configured():
    key, frm = _cfg()
    user, pw = _gmail_cfg()
    return bool((key and frm) or (user and pw))


def transport():
    key, frm = _cfg()
    if key and frm:
        return "resend"
    user, pw = _gmail_cfg()
    if user and pw:
        return "gmail"
    return None


def _send_gmail(to, subject, html_body):
    user, pw = _gmail_cfg()
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    text = re.sub(r"<[^>]+>", "", html_body)  # rough plain-text fallback
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                          context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.sendmail(user, to, msg.as_string())
    return True, "gmail"


def send_email(to, subject, html_body, reply_to=None):
    """Send one email. Returns (ok, error_or_id)."""
    key, frm = _cfg()
    if key and frm:
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
    user, pw = _gmail_cfg()
    if user and pw:
        try:
            return _send_gmail(to, subject, html_body)
        except Exception as e:
            return False, str(e)
    return False, "email not configured (no Resend or Gmail credentials)"


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
    """Mobile-first HTML email wrapper for Telegram-markdown text."""
    body = html.escape(brief_text)
    body = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", body)
    body = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", body)
    note = (f'<p style="color:#888;font-size:12px">{html.escape(footer_note)}</p>'
            if footer_note else "")
    return f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:12px;background:#f6f7f9">
<div style="font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;
     max-width:600px;margin:0 auto;background:#ffffff;border-radius:10px;
     padding:18px 16px;font-size:16px;line-height:1.55;color:#1a1a1a">
<div style="white-space:pre-wrap;word-wrap:break-word">{body}</div>
<hr style="border:none;border-top:1px solid #e5e5e5;margin:16px 0">
{note}
<p style="color:#999;font-size:11px;line-height:1.4">NFL Edge Finder — for entertainment &amp;
informational purposes only. Not betting advice. 21+. If gambling stops being fun:
1-800-GAMBLER. Reply to this email to stop the daily brief.</p>
</div></body></html>"""
