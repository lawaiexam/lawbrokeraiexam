import time
import pandas as pd  # ✅ 確保引入 pandas
import streamlit as st

from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from services.bank_service import load_bank_df, get_all_tags, filter_by_tags
from services.exam_service import build_paper
from components.auth_ui import render_user_panel
from components.sidebar_exam_settings import render_exam_settings
from components.question_render import render_question
from utils import ai_handler as ai

ensure_state()

# ========= Sidebar =========
with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("開始考試 - 練習模式")

with st.sidebar:
    # ✅ 明確指定練習模式
    settings = render_exam_settings(mode="practice")

# ========= 載入題庫（練習模式：選檔 / merge_all） =========
df = load_bank_df(
    settings["bank_type"],
    settings["merge_all"],
    settings["bank_source"],
)

if df is None or df.empty:
    st.warning("尚未載入題庫，請在左側選擇題庫。")
    st.stop()

# ==========================================
# 🚑 HOTFIX: 資料格式救援補丁 (Data Schema Patch)
# ==========================================
# 原因：新上傳的題庫是 Raw Data (選項一, 選項二...)，但 UI 需要 'Choices' 與 'ID' 欄位。

# 1. 確保 ID 欄位存在
if "ID" not in df.columns and "編號" in df.columns:
    df["ID"] = df["編號"] # 將中文編號複製一份給 ID

# 2. 確保 Choices 欄位存在 (打包選項)
if "Choices" not in df.columns:
    def pack_choices(row):
        options = []
        # 定義映射：顯示代號 -> 可能的欄位名稱列表
        mapping = [
            ("A", ["選項一", "Option A", "A"]),
            ("B", ["選項二", "Option B", "B"]),
            ("C", ["選項三", "Option C", "C"]),
            ("D", ["選項四", "Option D", "D"]),
            ("E", ["選項五", "Option E", "E"])
        ]
        
        for label, cols in mapping:
            for col in cols:
                # 如果欄位存在且內容不為空 (NaN)
                if col in row and pd.notna(row[col]):
                    val = str(row[col]).strip()
                    if val: 
                        options.append((label, val))
                    break # 找到對應欄位就跳出，繼續找下一個代號
        return options

    # 套用轉換函數
    df["Choices"] = df.apply(pack_choices, axis=1)

# ==========================================
# 🚑 補丁結束
# ==========================================

st.session_state.df = df

# 顯示用名稱（練習模式保留你原本邏輯）
if settings["merge_all"]:
    bank_label = f"{settings['bank_type']}（全部題庫）"
elif settings["bank_source"]:
    bank_label = settings["bank_source"]
else:
    bank_label = settings["bank_type"]

st.session_state.current_bank_name = bank_label

# ========= 篩選器 (Tags) =========
all_tags = get_all_tags(df)
selected_tags = []
if all_tags:
    with st.expander("進階篩選（依標籤）"):
        selected_tags = st.multiselect("過濾特定主題：", options=all_tags)

filtered = filter_by_tags(df, selected_tags)
if filtered.empty:
    st.warning("篩選後沒有題目。")
    st.stop()

st.caption(f"目前題庫：{bank_label}｜共 {len(filtered)} 題")

# ========= 練習模式 State 初始化 =========
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

# 當題庫變更時重置
if st.session_state.get("last_bank_sig") != (bank_label, len(filtered), tuple(selected_tags)):
    # 重新洗牌
    paper = build_paper(
        filtered,
        n_questions=len(filtered),
        random_order=settings["random_order"],
        shuffle_options=settings["shuffle_options"]
    )
    st.session_state.practice_shuffled = paper
    st.session_state.practice_idx = 0
    st.session_state.practice_answers = {}
    st.session_state.practice_correct = 0
    st.session_state.hints = {}
    st.session_state.last_bank_sig = (bank_label, len(filtered), tuple(selected_tags))

paper = st.session_state.practice_shuffled
if not paper:
    st.info("沒有題目。")
    st.stop()

# ========= 顯示題目 (逐題模式) =========
total = len(paper)
i = st.session_state.practice_idx
q = paper[i]

# 進度條
progress = (i + 1) / total
st.progress(progress, text=f"第 {i+1} / {total} 題 （答對：{st.session_state.practice_correct}）")

st.divider()

# AI Hint
if ai.gemini_ready():
    if st.button(f"💡 AI 提示（Q{i+1}）", key=f"ai_hint_practice_{i}"):
        ck, sys, usr = ai.build_hint_prompt(q)
        with st.spinner("AI 產生提示中…"):
            hint = ai.gemini_generate_cached(ck, sys, usr)
        st.session_state.hints[q["ID"]] = hint

    if q["ID"] in st.session_state.hints:
        st.info(st.session_state.hints[q["ID"]])

picked_labels = render_question(
    q,
    show_image=settings["show_image"],
    answer_key=f"practice_pick_{i}",
)

# ========= 提交作答 =========
if st.button("提交這題", key=f"practice_submit_{i}"):
    gold = set(q["Answer"])
    st.session_state.practice_answers[q["ID"]] = picked_labels

    if picked_labels == gold:
        st.success("✅ 答對了！")
        st.session_state.practice_correct += 1
    else:
        st.error(f"❌ 答錯了。正確：{', '.join(sorted(list(gold))) or '(空)'}")
        if str(q.get("Explanation", "")).strip():
            st.caption(f"📖 題庫詳解：{q['Explanation']}")

# ========= 導航 =========
cols = st.columns([1, 1])
with cols[0]:
    if st.button("上一題", disabled=(i == 0)):
        st.session_state.practice_idx = max(0, i - 1)
        st.rerun()
with cols[1]:
    if st.button("下一題", disabled=(i == total - 1)):
        st.session_state.practice_idx = min(total - 1, i + 1)
        st.rerun()
