"""Notification senders for the morning brief fan-out.

- send_telegram: direct Bot API call using the Hermes gateway's bot token
  (read from ~/.hermes/.env at runtime; never stored in the repo).
- send_email: Gmail SMTP with an app password (GMAIL_USER / GMAIL_APP_PASSWORD
  from env or .streamlit/secrets.toml).
"""

import html as _html
import os
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

SECRETS = "/Users/jeff/nfl-edge/.streamlit/secrets.toml"
HERMES_ENV = os.path.expanduser("~/.hermes/.env")


def _env(name):
    v = os.environ.get(name)
    if v:
        return v
    try:
        for line in open(HERMES_ENV):
            line = line.strip()
            if line.startswith(name + "=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    try:
        import tomllib
        if os.path.exists(SECRETS):
            with open(SECRETS, "rb") as f:
                return tomllib.load(f).get(name)
    except Exception:
        pass
    return None


def send_telegram(chat_id, text):
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": str(chat_id), "text": text,
                            "parse_mode": "Markdown"}, timeout=20)
    return r.ok


def _md_to_html(md):
    out = _html.escape(md)
    out = re.sub(r"\*([^*]+)\*", r"<b>\1</b>", out)
    return out.replace("\n", "<br>\n")


def send_email(to_addr, subject, text):
    user, pw = _env("GMAIL_USER"), _env("GMAIL_APP_PASSWORD")
    if not (user and pw):
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to_addr
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(
        f"<html><body style=\"font-family:Arial,sans-serif;font-size:14px\">"
        f"{_md_to_html(text)}</body></html>", "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                          context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.sendmail(user, to_addr, msg.as_string())
    return True
