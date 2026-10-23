"""
User management page (admin only).
"""
import streamlit as st
import secrets
import bcrypt
import db
import emailer

def users_page(ctx):
    if not ctx.IS_ADMIN:
        st.error("Admins only.")
        st.stop()
    st.header("👥 User Management")
    with st.expander("➕ Add user", expanded=True):
        c1, c2 = st.columns(2)
        fname = c1.text_input("First name", key="new_fname")
        email = c2.text_input("Email", key="new_email")
        level = st.selectbox("Level", list(db.LEVELS), index=1, key="new_level",
                             help="user = free tier · paid = full features · admin = full + this page")
        if st.button("Create user"):
            uname = fname.strip().lower()
            if not uname:
                st.error("First name is required.")
            elif uname in [u["username"] for u in db.list_users()]:
                st.error(f"'{uname}' already exists.")
            else:
                pw = "edge-" + secrets.token_urlsafe(5)
                db.add_user(uname, fname.strip().title(), email.strip(), level,
                            bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
                st.success(f"✅ User **{uname}** created. Temp password — share it now, "
                           f"it won't be shown again:")
                st.code(pw)
    st.subheader("Accounts")
    _lvl_label = {"user": "free", "paid": "⭐ pro", "admin": "🛠️ admin"}
    for u in db.list_users():
        cols = st.columns([2, 3, 1.8, 2, 1.5])
        cols[0].markdown(f"**{u['name']}** (`{u['username']}`)")
        cols[1].markdown(u["email"] or "—")
        if u["username"] != ctx.USER:
            new_lvl = cols[2].selectbox("Level", list(db.LEVELS), key=f"lvl_{u['username']}",
                                        index=list(db.LEVELS).index(u["level"]),
                                        format_func=lambda l: _lvl_label[l],
                                        label_visibility="collapsed")
            if new_lvl != u["level"]:
                if u["level"] == "admin" and db.admin_count() <= 1:
                    st.error("Can't demote the last admin.")
                else:
                    db.set_level(u["username"], new_lvl)
                    st.success(f"**{u['username']}** → {_lvl_label[new_lvl]}")
                    st.rerun()
        else:
            cols[2].markdown(_lvl_label[u["level"]])
        if u["username"] != ctx.USER:
            if cols[3].button("🔑 Reset password", key=f"rst_{u['username']}"):
                pw = "edge-" + secrets.token_urlsafe(5)
                db.set_password(u["username"],
                                bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
                st.success(f"New temp password for **{u['username']}** (shown once):")
                st.code(pw)
            if cols[4].button("🗑️", key=f"del_{u['username']}", help="Delete user"):
                db.delete_user(u["username"])
                st.rerun()
        else:
            cols[3].caption("(that's you)")

    st.subheader("📣 Email all users")
    if not emailer.configured():
        st.caption("⚠️ Email not configured yet — needs Gmail or Resend credentials "
                   "(see docs/BUSINESS.md §email).")
    else:
        st.caption(f"Transport: **{emailer.transport()}**"
                   + (" — upgrade to Resend for better deliverability at scale "
                      "(docs/BUSINESS.md §email)" if emailer.transport() == "gmail" else ""))
        with st.form("broadcast_form"):
            b_subj = st.text_input("Subject")
            b_body = st.text_area("Message (plain text)")
            if st.form_submit_button("Send to all users with emails"):
                recips = [u["email"] for u in db.list_users() if u["email"]]
                if not (b_subj.strip() and b_body.strip()):
                    st.error("Subject and message are both required.")
                elif not recips:
                    st.warning("No users have email addresses saved.")
                else:
                    sent, errors = emailer.broadcast(
                        recips, b_subj.strip(),
                        emailer.brief_html(b_body.strip(),
                                           footer_note="Announcement from NFL Edge Finder."))
                    if errors:
                        st.warning(f"Sent to {sent}/{len(recips)}. Errors: {'; '.join(errors)}")
                    else:
                        st.success(f"✅ Sent to all {sent} users.")