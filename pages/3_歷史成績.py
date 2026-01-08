import streamlit as st
from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from components.auth_ui import render_user_panel
from components.history_render import render_history
from utils import db_handler as db

ensure_state()

with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("歷史成績")

try:
    hist = db.get_user_history(user["emp_id"])
except Exception as e:
    st.error(f"讀取歷史成績失敗：{e}")
    st.stop()

render_history(hist)
