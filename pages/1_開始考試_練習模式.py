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
from utils import data_loader as dl  # 記得確保您的 utils/data_loader.py 已包含我剛才提供的 clean_and_normalize_df

ensure_state()

# ========= Sidebar =========
with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("開始考試 - 練習模式")

with st.sidebar:
    settings = render_exam_settings(mode="practice")

# ========= 載入題庫 =========
df = load_bank_df(
    settings["bank_type"],
    settings["merge_all"],
    settings["bank_source"],
)

if df is None or df.empty:
    st.warning("尚未載入題庫，請在左側選擇題庫。")
    st.stop()

# ==========================================
# 資料清洗 (呼叫 utils.data_loader 的新函式)
# ==========================================
try:
    # 這裡假設您已經按照上一輪建議更新了 data_loader.py
    # 如果還沒更新 data_loader，請暫時保留您原本那段長長的 HOTFIX V4
    if hasattr(dl, 'clean_and_normalize_df'):
        df = dl.clean_and_normalize_df(df)
    else:
        # Fallback: 如果還沒更新 utils，這裡做一個極簡處理以免報錯
        df.columns = df.columns.str.strip()
        if "ID" not in df.columns: df["ID"] = range(1, len(df)+1)
        if "Choices" not in df.columns: st.error("請先更新 utils/data_loader.py 以支援自動清洗功能。"); st.stop()
        
except Exception as e:
    st.error(f"資料格式轉換失敗：{e}")
    st.stop()

if df.empty:
    st.error("資料清洗後為空，請檢查檔案格式。")
    st.stop()

st.session_state.df = df

if settings["merge_all"]:
    bank_label = f"{settings['bank_type']}（全部題庫）"
elif settings["bank_source"]:
    bank_label = settings["bank_source"]
else:
    bank_label = settings["bank_type"]

st.session_state.current_bank_name = bank_label

# ========= 篩選器 =========
all_tags = get_all_tags(df)
selected_tags = []
if all_tags:
    with st.expander("進階篩選（依標籤）"):
        selected_tags = st.multiselect("過濾特定主題：", options=all_tags)

filtered = filter_by_tags(df, selected_tags)
if filtered.empty:
    st.warning("篩選後沒有題目。")
    st.stop()

# 顯示目前題庫資訊
st.caption(f"目前題庫：{bank_label}｜篩選後共 {len(filtered)} 題")

# ========= State 初始化 =========
if "practice_idx" not in st.session_state:
    st.session_state.practice_idx = 0
if "practice_shuffled" not in st.session_state:
    st.session_state.practice_shuffled = []
if "practice_answers" not in st.session_state:
    st.session_state.practice_answers = {}
if "practice_correct" not in st.session_state:
    st.session_state.practice_correct = 0
if "hints" not in st.session_state:
    st.session_state.hints = {}

# 🟢【修正 1】: last_bank_sig 加入 settings["n_questions"]
# 這樣當您拉動側邊欄題數時，才會觸發重新組卷
current_sig = (bank_label, len(filtered), tuple(selected_tags), settings["n_questions"])

if st.session_state.get("last_bank_sig") != current_sig:
    # 🟢【修正 2】: 使用 settings["n_questions"] 而不是 len(filtered)
    paper = build_paper(
        filtered,
        n_questions=settings["n_questions"], 
        random_order=settings["random_order"],
        shuffle_options=settings["shuffle_options"]
    )
    st.session_state.practice_shuffled = paper
    st.session_state.practice_idx = 0
    st.session_state.practice_answers = {}
    st.session_state.practice_correct = 0
    st.session_state.hints = {} # 重置 AI 提示快取
    st.session_state.last_bank_sig = current_sig
    
    # 強制重整以更新 UI
    st.rerun()

paper = st.session_state.practice_shuffled
if not paper:
    st.info("沒有題目。")
    st.stop()

# ========= 顯示題目 =========
total = len(paper)
i = st.session_state.practice_idx
q = paper[i]

progress = (i + 1) / total
st.progress(progress, text=f"第 {i+1} / {total} 題 （答對：{st.session_state.practice_correct}）")

st.divider()

# 1. AI 提示功能 (作答前)
if ai.gemini_ready():
    # 使用 columns 讓按鈕不要佔滿整行
    c_hint, _ = st.columns([1, 4])
    with c_hint:
        if st.button(f"💡 AI 提示", key=f"ai_hint_practice_{i}"):
            ck, sys, usr = ai.build_hint_prompt(q)
            with st.spinner("AI 正在思考提示..."):
                hint = ai.gemini_generate_cached(ck, sys, usr)
            st.session_state.hints[q["ID"]] = hint

    if q["ID"] in st.session_state.hints:
        st.info(st.session_state.hints[q["ID"]])

# 2. 題目渲染
picked_labels = render_question(
    q,
    show_image=settings["show_image"],
    answer_key=f"practice_pick_{i}",
)

# 3. 判斷是否已作答
is_answered = q["ID"] in st.session_state.practice_answers

# ========= 提交作答按鈕 =========
if not is_answered:
    if st.button("提交這題", key=f"practice_submit_{i}", type="primary"):
        # 記錄答案
        st.session_state.practice_answers[q["ID"]] = picked_labels
        
        # 判斷對錯
        raw_ans = q.get("Answer")
        if isinstance(raw_ans, str):
            gold = {raw_ans}
        elif isinstance(raw_ans, (list, tuple)):
            gold = set(raw_ans)
        else:
            gold = set()

        if picked_labels == gold:
            st.session_state.practice_correct += 1
        
        st.rerun()

# ========= 顯示作答結果與詳解 =========
if is_answered:
    user_ans = st.session_state.practice_answers[q["ID"]]
    
    # 準備正確答案
    raw_ans = q.get("Answer")
    if isinstance(raw_ans, str): gold = {raw_ans}
    elif isinstance(raw_ans, (list, tuple)): gold = set(raw_ans)
    else: gold = set()

    # 顯示結果
    if user_ans == gold:
        st.success("✅ 答對了！")
    else:
        st.error(f"❌ 答錯了。正確答案：{', '.join(sorted(list(gold))) or '(未知)'}")
        
    # 顯示原本的靜態詳解
    if str(q.get("Explanation", "")).strip():
        st.caption(f"📖 題庫詳解：{q['Explanation']}")

    # 🟢【修正 3】: 加回 AI 詳解功能 (作答後)
    if ai.gemini_ready():
        st.write("") # 空行
        if st.button(f"🧠 生成 AI 詳解", key=f"ai_explain_practice_{i}"):
            # 準備 prompt
            q_data = {
                "ID": q["ID"],
                "Question": q["Question"],
                "Choices": q["Choices"],
                "Answer": list(gold),
                "Explanation": q.get("Explanation", "")
            }
            ck, sys, usr = ai.build_explain_prompt(q_data)
            
            with st.spinner("AI 正在分析題目與選項..."):
                explain = ai.gemini_generate_cached(ck, sys, usr)
                
            # 這裡我們用 session_state 暫存該題詳解，避免重整後消失
            # 為了簡單，這裡直接顯示出來，若需持久化可擴充 session_state
            st.markdown("### 🤖 AI 解析")
            st.info(explain)

# ========= 翻頁按鈕 =========
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
