import time
import streamlit as st

from utils import db_handler as db
from utils import github_handler as gh

from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from components.auth_ui import render_user_panel


st.set_page_config(page_title="錠嵂AI考照系統", layout="wide")


@st.cache_resource
def _init_once():
    # DB init（只做一次）
    db.init_db()
    # 指標前綴修正（只做一次）
    gh.migrate_pointer_prefix_if_needed()
    return True


def main():
    ensure_state()

    # 初始化（DB 建表 / pointer 前綴）
    try:
        _init_once()
    except Exception as e:
        st.error(f"⚠️ 初始化失敗：{e}")
        st.stop()

    # Sidebar：登入資訊 + 登出
    with st.sidebar:
        render_user_panel()

    # 未登入：顯示登入頁並 stop
    user = require_login_or_render()
    if user is None:
        st.stop()

    # 已登入：顯示首頁說明（多頁入口）
    st.title("錠嵂 AI 考照系統")
    st.info(
        "請從左側頁面選單進入：\n"
        "- 開始考試（練習模式 / 模擬考）\n"
        "- 歷史成績\n"
        "- 管理員後台（僅管理員）"
    )


if __name__ == "__main__":
    main()
