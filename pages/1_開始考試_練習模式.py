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
# ⚠️ 防呆：使用 .get() 避免 KeyError
df = load_bank_df(
    settings.get("bank_type", ""),
    settings.get("merge_all", False),
    settings.get("bank_source", ""),
)

if df is None or df.empty:
    st.warning("尚未載入題庫，請在左側選擇題庫。")
    st.stop()

# ==========================================
# 🚑 HOTFIX V4: 終極全能資料清洗補丁 (The Universal Cleaner)
# ==========================================
try:
    df.columns = df.columns.str.strip()

    # 1. 統一 ID
    if "ID" not in df.columns:
        if "編號" in df.columns: df["ID"] = df["編號"]
        elif "題目編號" in df.columns: df["ID"] = df["題目編號"]
        else: df["ID"] = range(1, len(df) + 1)

    option_map_config = [
        ('A', ['選項一', '選項1', 'Option A', 'A']),
        ('B', ['選項二', '選項2', 'Option B', 'B']),
        ('C', ['選項三', '選項3', 'Option C', 'C']),
        ('D', ['選項四', '選項4', 'Option D', 'D']),
        ('E', ['選項五', '選項5', 'Option E', 'E'])
    ]

    # 2. 處理 Answer
    if "Answer" not in df.columns:
        if "正確選項" in df.columns:
            def normalize_answer(val):
                val_str = str(val).strip()
                mapping = {'1': 'A', '2': 'B', '3': 'C', '4': 'D', '5': 'E'}
                return mapping.get(val_str, val_str)
            df["Answer"] = df["正確選項"].apply(normalize_answer)
        else:
            def extract_star_answer(row):
                for label, possible_cols in option_map_config:
                    for col in possible_cols:
                        if col in row and pd.notna(row[col]):
                            if str(row[col]).strip().startswith("*"):
                                return label
                return ""
            df["Answer"] = df.apply(extract_star_answer, axis=1)

            all_opt_cols = [col for _, cols in option_map_config for col in cols]
            for c in all_opt_cols:
                if c in df.columns:
                    df[c] = df[c].apply(lambda x: str(x).lstrip('*') if pd.notna(x) else x)

    # 3. 打包 Choices
    if "Choices" not in df.columns:
        def universal_pack(row):
            choices = []
            for label, possible_cols in option_map_config:
                found_text = None
                for col in possible_cols:
                    if col in row and pd.notna(row[col]):
                        val = str(row[col]).strip()
                        if val and val.lower() != "nan":
                            found_text = val
                            break
                if found_text: choices.append((label, found_text))
            return choices
        df["Choices"] = df.apply(universal_pack, axis=1)

    # 4. 處理詳解
    if "Explanation" not in df.columns and "解答說明" in df.columns:
        df["Explanation"] = df["解答說明"]

except Exception as e:
    st.error(f"資料格式轉換失敗：{e}")
    st.stop()
# ==========================================
# 🚑 補丁結束
# ==========================================

st.session_state.df = df

if settings.get("merge_all"):
    bank_label = f"{settings.get('bank_type')}（全部題庫）"
elif settings.get("bank_source"):
    bank_label = settings.get("bank_source")
else:
    bank_label = settings.get("bank_type", "未選擇")

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

st.caption(f"目前題庫：{bank_label}｜共 {len(filtered)} 題")

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

# 當題庫變更時重置
if st.session_state.get("last_bank_sig") != (bank_label, len(filtered), tuple(selected_tags)):
    # 🛠️ 這裡做了關鍵修正：使用 .get() 並給予預設值 False
    paper = build_paper(
        filtered,
        n_questions=len(filtered),
        random_order=settings.get("random_order", False),  # ✅ 防呆修正
        shuffle_options=settings.get("shuffle_options", False) # ✅ 防呆修正
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

# ========= 顯示題目 =========
total = len(paper)
i = st.session_state.practice_idx
q = paper[i]

progress = (i + 1) / total
st.progress(progress, text=f"第 {i+1} / {total} 題 （答對：{st.session_state.practice_correct}）")

st.divider()

if ai.gemini_ready():
    if st.button(f"💡 AI 提示（Q{i+1}）", key=f"ai_hint_practice_{i}"):
        ck, sys, usr = ai.build_hint_prompt(q)
        with st.spinner("AI 產生提示中…"):
            hint = ai.gemini_generate_cached(ck, sys, usr)
        st.session_state.hints[q["ID"]] = hint

    if q["ID"] in st.session_state.hints:
        st.info(st.session_state.hints[q["ID"]])

# 顯示題目，也加上 .get() 防呆
picked_labels = render_question(
    q,
    show_image=settings.get("show_image", False),
    answer_key=f"practice_pick_{i}",
)

# ========= 提交作答 =========
if st.button("提交這題", key=f"practice_submit_{i}"):
    raw_ans = q.get("Answer")
    if isinstance(raw_ans, str):
        gold = {raw_ans}
    elif isinstance(raw_ans, (list, tuple)):
        gold = set(raw_ans)
    else:
        gold = set()

    st.session_state.practice_answers[q["ID"]] = picked_labels

    if picked_labels == gold:
        st.success("✅ 答對了！")
        st.session_state.practice_correct += 1
    else:
        st.error(f"❌ 答錯了。正確：{', '.join(sorted(list(gold))) or '(未知)'}")
        if str(q.get("Explanation", "")).strip():
            st.caption(f"📖 題庫詳解：{q['Explanation']}")

cols = st.columns([1, 1])
with cols[0]:
    if st.button("上一題", disabled=(i == 0)):
        st.session_state.practice_idx = max(0, i - 1)
        st.rerun()
with cols[1]:
    if st.button("下一題", disabled=(i == total - 1)):
        st.session_state.practice_idx = min(total - 1, i + 1)
        st.rerun()
