import time
import pandas as pd
import streamlit as st

from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from services.bank_service import load_bank_df, get_all_tags, filter_by_tags
from services.exam_service import build_paper
from components.auth_ui import render_user_panel
from components.sidebar_exam_settings import render_exam_settings
from components.question_render import render_question
from utils import ai_handler as ai
from utils import data_loader as dl

ensure_state()

# ========= 狀態管理初始化 =========
if "practice_started" not in st.session_state:
    st.session_state.practice_started = False
if "practice_settings" not in st.session_state:
    st.session_state.practice_settings = {}

# ========= Sidebar 佈局 =========
with st.sidebar:
    render_user_panel()
    st.divider()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("📝 開始考試 - 練習模式")

# ==========================================
# 1. 側邊欄：題庫選擇與參數設定
# ==========================================
with st.sidebar:
    base_settings = render_exam_settings(mode="practice")
    
    # 載入原始資料 (Raw Data)
    raw_df = load_bank_df(
        base_settings["bank_type"],
        base_settings["merge_all"],
        base_settings["bank_source"],
    )
    
    # 資料清洗
    try:
        if raw_df is not None and not raw_df.empty:
            # 強制重新清洗，確保邏輯應用
            raw_df = dl.clean_and_normalize_df(raw_df)
    except Exception as e:
        st.error(f"資料清洗發生錯誤: {e}")

    # ======================================
    # 🛠️ 資料診斷室 (Debug Tool)
    # ======================================
    with st.expander("🛠️ 資料診斷室 (若答案未知請點此)", expanded=False):
        if st.button("🔄 強制清除快取並重整", type="primary"):
            st.cache_data.clear()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

        if raw_df is not None and not raw_df.empty:
            st.write(f"**偵測到的欄位名稱：**")
            st.code(list(raw_df.columns))
            
            st.write("**清洗後資料預覽 (前 3 筆)：**")
            # 檢查關鍵欄位
            debug_cols = ["ID", "Question", "Answer", "Choices"]
            existing_cols = [c for c in debug_cols if c in raw_df.columns]
            st.dataframe(raw_df[existing_cols].head(3))
            
            # 檢查 Answer 狀況
            empty_ans = raw_df["Answer"].isna() | (raw_df["Answer"] == "")
            st.write(f"❌ 答案空白的題數：{empty_ans.sum()} / {len(raw_df)}")
            if empty_ans.sum() > 0:
                st.error("警告：系統無法偵測到部分題目的答案，請檢查上方欄位名稱是否正確。")
        else:
            st.warning("尚未載入資料")

    # B. 進階篩選與參數
    if raw_df is not None and not raw_df.empty:
        st.divider()
        st.subheader("3. 進階篩選與設定")
        
        all_tags = get_all_tags(raw_df)
        selected_tags = []
        if all_tags:
            selected_tags = st.multiselect(
                "過濾特定章節/主題：", 
                options=all_tags,
                key="sb_tags_practice"
            )
            if not selected_tags:
                st.caption("（未選擇則預設為全部範圍）")
        
        max_q = len(raw_df)
        if selected_tags:
            approx_count = len(filter_by_tags(raw_df, selected_tags))
            st.caption(f"篩選後約有 {approx_count} 題")
        else:
            approx_count = max_q
            st.caption(f"總題庫共 {max_q} 題")

        n_questions = st.slider(
            "練習題數", 
            min_value=5, 
            max_value=min(200, approx_count) if approx_count > 5 else 5, 
            value=min(20, approx_count), 
            step=5, 
            key="sb_nq_practice"
        )
        
        random_order = st.checkbox("題目隨機亂序", value=True, key="sb_random_practice")
        
        st.divider()
        
        start_btn = st.button("🚀 開始/重置 練習", type="primary", use_container_width=True)
        
        if start_btn:
            st.session_state.practice_started = True
            
            final_df = filter_by_tags(raw_df, selected_tags)
            
            if final_df.empty:
                st.error("篩選後無題目，請調整篩選條件。")
                st.session_state.practice_started = False
            else:
                paper = build_paper(
                    final_df,
                    n_questions=n_questions,
                    random_order=random_order,
                    shuffle_options=False # 練習模式不洗牌選項
                )
                
                st.session_state.df = final_df
                st.session_state.practice_shuffled = paper
                st.session_state.practice_idx = 0
                st.session_state.practice_answers = {}
                st.session_state.practice_correct = 0
                st.session_state.hints = {}
                
                st.session_state.practice_settings = {
                    "bank_label": base_settings["bank_source"] or base_settings["bank_type"],
                    "tags": selected_tags,
                    "count": len(paper),
                    "show_image": base_settings["show_image"]
                }
                
                st.rerun()

    else:
        st.warning("請先選擇有效的題庫檔案。")

# ==========================================
# 2. 主畫面渲染
# ==========================================

if not st.session_state.practice_started:
    st.info("👈 請在左側側邊欄選擇題庫、設定篩選條件，並點擊「開始練習」按鈕。")
    if raw_df is not None and not raw_df.empty:
        st.write("---")
        st.subheader("📊 題庫預覽")
        st.write(f"目前載入題庫：共 {len(raw_df)} 題")
        st.dataframe(raw_df.head(5), use_container_width=True)
    st.stop()

paper = st.session_state.practice_shuffled
if not paper:
    st.warning("題庫中沒有題目，請重新設定。")
    if st.button("重置"):
        st.session_state.practice_started = False
        st.rerun()
    st.stop()

p_set = st.session_state.practice_settings
st.caption(f"📚 題庫：{p_set.get('bank_label')} ｜ 🔖 範圍：{', '.join(p_set.get('tags')) if p_set.get('tags') else '全部'} ｜ 📝 總題數：{p_set.get('count')}")

total = len(paper)
i = st.session_state.practice_idx
q = paper[i]

progress = (i + 1) / total
st.progress(progress, text=f"第 {i+1} / {total} 題 （答對：{st.session_state.practice_correct}）")

st.divider()

# AI 提示
if ai.gemini_ready():
    c_hint, _ = st.columns([1, 4])
    with c_hint:
        if st.button(f"💡 AI 提示", key=f"ai_hint_practice_{i}"):
            ck, sys, usr = ai.build_hint_prompt(q)
            with st.spinner("AI 正在思考提示..."):
                hint = ai.gemini_generate_cached(ck, sys, usr)
            st.session_state.hints[q["ID"]] = hint

    if q["ID"] in st.session_state.hints:
        st.info(st.session_state.hints[q["ID"]])

# 題目
picked_labels = render_question(
    q,
    show_image=p_set.get("show_image", True),
    answer_key=f"practice_pick_{i}",
)

is_answered = q["ID"] in st.session_state.practice_answers

# 提交按鈕
if not is_answered:
    if st.button("提交這題", key=f"practice_submit_{i}", type="primary"):
        st.session_state.practice_answers[q["ID"]] = picked_labels
        
        raw_ans = q.get("Answer")
        if isinstance(raw_ans, str): gold = {raw_ans}
        elif isinstance(raw_ans, (list, tuple)): gold = set(raw_ans)
        else: gold = set()

        if picked_labels == gold:
            st.session_state.practice_correct += 1
        
        st.rerun()

# 結果與詳解
if is_answered:
    user_ans = st.session_state.practice_answers[q["ID"]]
    
    raw_ans = q.get("Answer")
    if isinstance(raw_ans, str): gold = {raw_ans}
    elif isinstance(raw_ans, (list, tuple)): gold = set(raw_ans)
    else: gold = set()

    if user_ans == gold:
        st.success("✅ 答對了！")
    else:
        st.error(f"❌ 答錯了。正確答案：{', '.join(sorted(list(gold))) or '(未知)'}")
        
    if str(q.get("Explanation", "")).strip():
        st.caption(f"📖 題庫詳解：{q['Explanation']}")

    if ai.gemini_ready():
        st.write("")
        if st.button(f"🧠 生成 AI 詳解", key=f"ai_explain_practice_{i}"):
            q_data = {
                "ID": q["ID"],
                "Question": q["Question"],
                "Choices": q["Choices"],
                "Answer": list(gold),
                "Explanation": q.get("Explanation", "")
            }
            ck, sys, usr = ai.build_explain_prompt(q_data)
            with st.spinner("AI 正在分析..."):
                explain = ai.gemini_generate_cached(ck, sys, usr)
            st.markdown("### 🤖 AI 解析")
            st.info(explain)

st.divider()
cols = st.columns([1, 1])
with cols[0]:
    if st.button("⬅️ 上一題", disabled=(i == 0), use_container_width=True):
        st.session_state.practice_idx = max(0, i - 1)
        st.rerun()
with cols[1]:
    if st.button("下一題 ➡️", disabled=(i == total - 1), use_container_width=True):
        st.session_state.practice_idx = min(total - 1, i + 1)
        st.rerun()
