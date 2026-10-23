"""
Settings page view.
"""
import streamlit as st
import bcrypt
import db
import emailer
from shared import gate

def settings_page(ctx):
    st.header("⚙️ Settings")
    me = db.get_user(ctx.USER)

    st.subheader("🔑 Change password")
    with st.form("pw_form"):
        cur = st.text_input("Current password", type="password")
        new1 = st.text_input("New password", type="password")
        new2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Update password"):
            if not bcrypt.checkpw(cur.encode(), me["pw_hash"].encode()):
                st.error("Current password is wrong.")
            elif len(new1) < 6:
                st.error("New password must be at least 6 characters.")
            elif new1 != new2:
                st.error("New passwords don't match.")
            else:
                db.set_password(ctx.USER, bcrypt.hashpw(new1.encode(), bcrypt.gensalt()).decode())
                st.success("Password updated ✅")

    st.subheader("🔔 Notifications")
    st.caption("The morning brief only sends on days something changed — no news, no message.")
    em_col, tg_col = st.columns(2)
    with em_col:
        st.markdown("**📧 Daily email brief**")
        new_email = st.text_input("Your email", value=me["email"] or "", key="set_email")
        if st.button("Save email"):
            db.update_email(ctx.USER, new_email.strip())
            st.success("Email saved ✅")
            st.rerun()
        if gate(ctx, "email_brief"):
            email_on = st.checkbox("Send me the daily email brief",
                                   value=bool(me["email_enabled"]),
                                   disabled=not (me["email"] or new_email.strip()))
            if not (me["email"] or new_email.strip()):
                st.caption("Add your email above to enable this.")
        else:
            email_on = False
            st.caption("🔒 The daily email brief is a **Pro** feature — "
                       "contact us to upgrade.")
    with tg_col:
        st.markdown("**📱 Daily Telegram brief**")
        if me["telegram_chat_id"]:
            st.success("Telegram linked ✅")
        else:
            st.info("To link: open Telegram and send ANY message to the bot you chat with Jeff's agent on, "
                    "then tell Jeff — he'll confirm the link on his side.")
        tg_on = st.checkbox("Send me the daily Telegram brief",
                            value=bool(me["telegram_enabled"]),
                            disabled=not me["telegram_chat_id"])
        if not me["telegram_chat_id"]:
            st.caption("Available once your Telegram is linked.")
    if st.button("💾 Save notification preferences"):
        db.update_prefs(ctx.USER, email_enabled=email_on, telegram_enabled=tg_on)
        st.success("Preferences saved ✅")
        st.rerun()

    st.subheader("🔔 Alert subscriptions")
    st.caption("Choose which alerts you want and where they land. Telegram delivery "
               "needs your Telegram linked (above); email needs your email saved.")
    _ap = db.get_alert_prefs(ctx.USER)
    _ch_disp = {"off": "Off", "telegram": "📱 Telegram", "email": "📧 Email", "both": "📱+📧 Both"}
    _ch_keys = list(_ch_disp)
    _new = {}
    for _ak, _alabel in db.ALERT_TYPES.items():
        _cur = _ap.get(_ak, "off")
        _new[_ak] = st.selectbox(_alabel, _ch_keys, index=_ch_keys.index(_cur),
                                 format_func=lambda k: _ch_disp[k], key=f"ap_{_ak}")
    if st.button("💾 Save alert subscriptions"):
        for _ak, _ch in _new.items():
            db.set_alert_pref(ctx.USER, _ak, _ch)
        st.success("Alert subscriptions saved ✅")
        st.rerun()
    if ctx.IS_ADMIN:
        st.caption("🛠️ You (admin) also get every watchdog alert on Telegram via the bot, "
                   "regardless of these settings.")

    st.subheader("🗑️ Delete account")
    st.warning("This deletes your account AND your private bet journal. Permanent.")
    confirm = st.text_input("Type DELETE to confirm", key="del_confirm")
    del_pw = st.text_input("Re-enter your password", type="password", key="del_pw")
    if st.button("Delete my account", disabled=(confirm != "DELETE" or not del_pw)):
        if ctx.IS_ADMIN and db.admin_count() <= 1:
            st.error("You're the last admin — promote someone else first, or the app locks everyone out.")
        elif not bcrypt.checkpw(del_pw.encode(), db.get_user(ctx.USER)["pw_hash"].encode()):
            st.error("Password doesn't match — account not deleted.")
        else:
            db.delete_user(ctx.USER)
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()