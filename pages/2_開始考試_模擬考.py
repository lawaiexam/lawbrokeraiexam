import time
import streamlit as st

from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from services.bank_service import load_bank_df, get_all_tags, filter_by_tags
from services.exam_service import build_paper, grade_paper, persist_exam_record
from components.auth_ui import render_user_panel
from components.sidebar_exam_settings import render_exam_settings
from components.question_render import render_question
from utils import ai_handler as ai


ensure_state()

with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("開始考試 - 模擬考")

with st.sidebar:
    settings = render_exam_settings()
    time_limit = st.number_input("限時（分鐘，0=不限時）", min_value=0, max_value=300, value=0, step=5)
    st.session_state.time_limit = int(time_limit) * 60

df = load_bank_df(settings["bank_type"], settings["merge_all"], settings["bank_source"])
if df is None or df.empty:
    st.warning("尚未載入題庫，請在左側選擇題庫。")
    st.stop()

st.session_state.df = df
st.session_state.current_bank_name = settings["bank_type"]

all_tags = get_all_tags(df)
picked_tags = st.multiselect("過濾章節", options=all_tags)
filtered = filter_by_tags(df, picked_tags)
# 用於寫入歷史紀錄的 bank_type（不含路徑、但含範圍）
if picked_tags:
    bank_label = f"{settings['bank_type']}[範圍: {'、'.join(picked_tags)}]"
else:
    bank_label = settings["bank_type"]

st.session_state.current_bank_name = bank_label

if filtered is None or filtered.empty:
    st.warning("此條件下沒有題目。")
    st.stop()

colA, colB = st.columns([1, 1])
with colA:
    if st.button("開始模擬考", type="primary"):
        st.session_state.paper = build_paper(filtered, settings["n_questions"], random_order=True, shuffle_options=settings["shuffle_options"])
        st.session_state.answers = {}
        st.session_state.started = True
        st.session_state.show_results = False
        st.session_state.saved_to_db = False
        st.session_state.start_ts = time.time()
        st.rerun()

with colB:
    if st.button("重置", type="secondary"):
        st.session_state.paper = None
        st.session_state.answers = {}
        st.session_state.started = False
        st.session_state.show_results = False
        st.session_state.saved_to_db = False
        st.session_state.start_ts = None
        st.rerun()

paper = st.session_state.paper
if not paper:
    st.info("請先按「開始模擬考」。")
    st.stop()

# Timer
if st.session_state.time_limit and st.session_state.start_ts:
    elapsed = int(time.time() - st.session_state.start_ts)
    remain = max(0, st.session_state.time_limit - elapsed)
    st.metric("剩餘時間（秒）", remain)
    if remain == 0 and not st.session_state.show_results:
        st.warning("時間到，自動交卷。")
        st.session_state.show_results = True

# 作答
st.subheader("作答區")
for idx, q in enumerate(paper, start=1):
    with st.expander(f"第 {idx} 題", expanded=(idx == 1)):
        picked = render_question(q, show_image=settings["show_image"], answer_key=f"mock_ans_{q['ID']}")
        st.session_state.answers[q["ID"]] = picked

# 交卷
if st.button("交卷", type="primary"):
    st.session_state.show_results = True

if not st.session_state.show_results:
    st.stop()

# 成績
results_df, score_tuple, wrong_df = grade_paper(paper, st.session_state.answers)
st.session_state.results_df = results_df
st.session_state.score_tuple = score_tuple

correct, total, score = score_tuple
st.success(f"成績：{score} 分（答對 {correct}/{total}）")

# 存 DB（只做一次）
if not st.session_state.saved_to_db and st.session_state.start_ts:
    duration_sec = int(time.time() - st.session_state.start_ts)
    try:
        persist_exam_record(user, st.session_state.current_bank_name, score_tuple, duration_sec, wrong_df)
        st.session_state.saved_to_db = True
    except Exception as e:
        st.error(f"寫入成績失敗：{e}")

st.dataframe(results_df, use_container_width=True)

# AI 詳解（錯題）
if ai.gemini_ready() and not wrong_df.empty:
    st.subheader("AI 老師詳解（錯題）")
    for _, r in wrong_df.iterrows():
        # ✅ 兼容舊欄位/新欄位
        correct_ans = r.get("CorrectAnswer", r.get("Correct", []))
        your_ans = r.get("YourAnswer", r.get("Your Answer", []))

        q = {
            "ID": r.get("ID", ""),
            "Question": r.get("Question", ""),
            "Choices": r.get("Choices", []),

            # ✅ ai_handler 內部通常用 Answer 表示正解
            "Answer": correct_ans,
            "Type": r.get("Type", ""),
            "Explanation": r.get("Explanation", ""),

            # （可選）如果你的 ai prompt 用得到，也一起帶上
            "YourAnswer": your_ans,
        }

        qid = r.get("ID", "")
        if st.button(f"🧠 生成詳解（{qid}）", key=f"ai_explain_{qid}"):
            ck, sys, usr = ai.build_explain_prompt(q)
            with st.spinner("AI 生成詳解中…"):
                explain = ai.gemini_generate_cached(ck, sys, usr)
            st.info(explain)