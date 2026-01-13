import streamlit as st
from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from components.auth_ui import render_user_panel
# from components.admin_render import render_upload_bank  <-- 移除：不再需要舊的上傳元件
from utils import db_handler as db

ensure_state()

with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("📊 管理員後台：成績總覽")

# 權限檢查
if user.get("emp_id") != "admin":
    st.error("⛔ 此頁面權限不足，僅限管理員使用。")
    st.stop()

# ==========================================
# 修改重點 1：加入導引提示
# ==========================================
st.info("💡 提示：如需 **上傳、更新或整合題庫**，請前往左側選單的 **「6_題庫自動分類與整合」** 頁面進行操作。")

st.divider()

# ==========================================
# 修改重點 2：移除 Tabs，直接顯示報表
# ==========================================
st.subheader("全體員工成績報表")

try:
    # 直接讀取並顯示資料，不需要再切換 Tab
    all_hist = db.get_all_history()
    
    if not all_hist.empty:
        # 可以加上簡單的篩選器或排序功能（選配）
        st.dataframe(
            all_hist, 
            use_container_width=True,
            hide_index=True  # 隱藏 pandas 的 index 讓表格更乾淨
        )
        
        # 額外功能：讓管理員可以下載報表 (Excel)
        # 這是一個很實用的加分功能
        csv = all_hist.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "📥 下載成績報表 (CSV)",
            csv,
            "exam_history_report.csv",
            "text/csv",
            key='download-csv'
        )
    else:
        st.warning("目前尚無任何考試紀錄。")

except Exception as e:
    st.error(f"讀取全體成績失敗：{e}")