"""Auth config: builds streamlit-authenticator. Users live in SQLite (admin-managed);
auth.yaml only supplies the cookie config + bootstrap fallback."""

import os

import db
import streamlit as st
import streamlit_authenticator as stauth
import yaml

AUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.yaml")


def _cookie_cfg():
    try:
        if "cookie" in st.secrets:
            return dict(st.secrets["cookie"])
    except Exception:
        pass
    try:
        with open(AUTH_PATH) as f:
            return (yaml.safe_load(f).get("cookie") or {})
    except Exception:
        return {}


def get_authenticator():
    creds = db.auth_credentials()
    if not creds["usernames"]:  # bootstrap fallback: auth.yaml users
        try:
            with open(AUTH_PATH) as f:
                creds = yaml.safe_load(f)["credentials"]
        except Exception:
            creds = {"usernames": {}}
    cookie = _cookie_cfg()
    return stauth.Authenticate(
        creds,
        cookie.get("name", "nfl_edge_auth"),
        cookie.get("key", "dev-key-change-me"),
        cookie.get("expiry_days", 30),
    )
