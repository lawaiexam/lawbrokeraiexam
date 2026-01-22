import streamlit as st

def render_login_form():
    st.markdown("## 🔐 錠嵂 AI 考照系統 - 員工登入")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.info("**系統資訊**\n\n請輸入您的員工業代與密碼進行登入")
    with col2:
        with st.form("login_form"):
            emp_id = st.text_input("員工編號 / 業務代碼")
            password = st.text_input("密碼", type="password")
            ok = st.form_submit_button("登入", type="primary")

    if ok:
        return emp_id.strip(), password
    return None


def render_user_panel():
    u = st.session_state.get("user_info")
    if not u:
        st.caption("尚未登入")
        return

    st.write(f"👤 **{u['name']}** ({u.get('department','')})")

    if st.button("登出"):
        st.session_state.user_info = None
        st.rerun()
