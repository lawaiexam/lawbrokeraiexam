import streamlit as st
from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from components.auth_ui import render_user_panel
from components.admin_render import render_upload_bank
from utils import db_handler as db

ensure_state()

with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("管理員後台")

# 你原本的簡單規則：emp_id == "admin"
if user.get("emp_id") != "admin":
    st.error("此頁面僅限管理員。")
    st.stop()

tab1, tab2 = st.tabs(["全體成績報表", "題庫上傳管理"])

with tab1:
    st.subheader("全體成績報表")
    try:
        all_hist = db.get_all_history()
        st.dataframe(all_hist, use_container_width=True)
    except Exception as e:
        st.error(f"讀取全體成績失敗：{e}")

with tab2:
    render_upload_bank()
