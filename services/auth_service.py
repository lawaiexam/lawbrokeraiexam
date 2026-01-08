import time
import streamlit as st
from utils import db_handler as db
from components.auth_ui import render_login_form

def login(emp_id: str, password: str):
    return db.login_user(emp_id, password)

def require_login_or_render():
    """
    未登入：顯示登入 UI，並在成功後寫入 session_state.user_info
    已登入：回傳 user dict
    """
    if st.session_state.get("user_info") is not None:
        return st.session_state.user_info

    result = render_login_form()
    if result is None:
        return None

    emp_id, password = result
    user = login(emp_id, password)
    if user:
        st.session_state.user_info = user
        st.toast(f"歡迎回來，{user['name']}！")
        time.sleep(0.2)
        st.rerun()
    else:
        st.error("帳號或密碼錯誤")
    return None
