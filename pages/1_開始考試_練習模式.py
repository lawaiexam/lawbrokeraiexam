import time
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

st.session_state.df = df

# 顯示用名稱（練習模式保留你原本邏輯）
if settings["merge_all"]:
    bank_label = f"{settings['bank_type']}（全部題庫）"
elif settings["bank_source"]:
    bank_label = settings["bank_source"]
else:
    bank_label = settings["bank_type"]

st.session_state.current_bank_name = bank_label

# ========= 章節複選（只存在於練習模式） =========
all_tags = get_all_tags(df)
picked_tags = st.multiselect("過濾章節", options=all_tags)

filtered = filter_by_tags(df, picked_tags)
if filtered is None or filtered.empty:
    st.warning("此條件下沒有題目。")
    st.stop()

# ========= 生成練習題 =========
if st.button("生成練習題", type="primary"):
    st.session_state.paper = build_paper(
        filtered,
        settings["n_questions"],
        random_order=True,
        shuffle_options=settings["shuffle_options"],
    )
    st.session_state.practice_idx = 0
    st.session_state.practice_correct = 0
    st.session_state.practice_answers = {}
    st.session_state.hints = {}   # ✅ 確保存在
    st.rerun()

paper = st.session_state.get("paper")
if not paper:
    st.info("請先按「生成練習題」。")
    st.stop()

# ========= 題目顯示 =========
i = st.session_state.practice_idx
q = paper[i]

st.markdown(f"### 第 {i+1} / {len(paper)} 題")
st.markdown(q["Question"])

# ========= AI 提示（維持原本行為） =========
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
    if st.button("➡️ 下一題", key=f"practice_next_{i}"):
        if i < len(paper) - 1:
            st.session_state.practice_idx += 1
            st.rerun()
        else:
            st.success(f"🎉 完成練習：{st.session_state.practice_correct}/{len(paper)}")

with cols[1]:
    if st.button("🔁 重新練習"):
        st.session_state.practice_idx = 0
        st.session_state.practice_correct = 0
        st.session_state.practice_answers = {}
        st.session_state.hints = {}
        st.rerun()
