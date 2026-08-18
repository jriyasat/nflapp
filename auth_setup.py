"""Auth config: builds streamlit-authenticator from st.secrets (cloud) or
local auth.yaml (gitignored)."""

import os

import streamlit as st
import streamlit_authenticator as stauth
import yaml

AUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.yaml")


def get_authenticator():
    cfg = None
    try:
        if "credentials" in st.secrets:
            cfg = {"credentials": dict(st.secrets["credentials"]),
                   "cookie": dict(st.secrets["cookie"]) if "cookie" in st.secrets else {}}
    except Exception:
        cfg = None
    if cfg is None:
        with open(AUTH_PATH) as f:
            cfg = yaml.safe_load(f)
    cookie = cfg.get("cookie", {})
    return stauth.Authenticate(
        cfg["credentials"],
        cookie.get("name", "nfl_edge_auth"),
        cookie.get("key", "dev-key-change-me"),
        cookie.get("expiry_days", 30),
    )
