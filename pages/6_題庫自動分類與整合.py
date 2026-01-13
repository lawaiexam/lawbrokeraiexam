import streamlit as st
import pandas as pd
from services.auth_service import require_login_or_render
from components.auth_ui import render_user_panel
from services.sorting_service import process_uploaded_file, save_merged_results, EXAM_CONFIGS

st.set_page_config(page_title="AI 題庫整合系統", layout="wide")

# 1. 權限檢查
with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None:
    st.stop()

# 僅限管理員
if user.get("emp_id") != "admin":
    st.error("⛔ 此頁面權限不足，僅限管理員使用。")
    st.stop()

st.title("🤖 AI 題庫自動分類與整合系統")
st.markdown("""
此工具使用 **Google Gemini AI** 自動分析新上傳的題庫，
並將其**自動歸類**合併至現有的題庫系統中。
""")

# 2. 選擇考科
exam_type = st.selectbox("請選擇要處理的證照類別", options=list(EXAM_CONFIGS.keys()))

# 3. 檔案上傳區
uploaded_file = st.file_uploader("請上傳新題庫 Excel (支援拖曳)", type=["xlsx"])

if uploaded_file:
    st.info(f"已讀取檔案：{uploaded_file.name}")
    
    # 用 session_state 保存處理後的資料，避免重新整理後消失
    if "classified_df" not in st.session_state:
        st.session_state.classified_df = None

    col1, col2 = st.columns([1, 3])
    with col1:
        start_btn = st.button("🚀 開始 AI 分析與分類", type="primary", use_container_width=True)

    # 4. 執行分類
    if start_btn:
        with st.spinner("正在喚醒 AI 進行語意分析，請稍候...（約需數分鐘）"):
            df_result = process_uploaded_file(exam_type, uploaded_file)
            
            if df_result is not None and not df_result.empty:
                st.session_state.classified_df = df_result
                st.success(f"✅ 分析完成！共處理 {len(df_result)} 題。")
            else:
                st.error("分析失敗，請檢查檔案格式是否正確。")

    # 5. 預覽與確認合併
    if st.session_state.classified_df is not None:
        st.divider()
        st.subheader("📊 分類結果預覽")
        
        # 顯示前 5 筆與分類分佈
        st.dataframe(st.session_state.classified_df.head(), use_container_width=True)
        
        # 統計圖表
        if "AI分類章節" in st.session_state.classified_df.columns:
            chart_data = st.session_state.classified_df["AI分類章節"].value_counts()
            st.bar_chart(chart_data)

        st.warning("⚠️ 確認無誤後，請點擊下方按鈕將新題目合併至系統題庫。")
        
        if st.button("💾 確認合併並寫入資料庫", type="primary"):
            with st.spinner("正在合併舊檔、去除重複題目並寫入硬碟..."):
                logs = save_merged_results(exam_type, st.session_state.classified_df)
                
                for log in logs:
                    st.success(log)
                
                st.balloons()
                # 清除暫存
                st.session_state.classified_df = None