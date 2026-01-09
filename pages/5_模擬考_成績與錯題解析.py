import json
import pandas as pd
import streamlit as st

from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from utils import ai_handler as ai

ensure_state()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("模擬考成績與錯題解析")

# ✅ 防呆：如果使用者直接開這頁但沒有考試結果
if "results_df" not in st.session_state or "score_tuple" not in st.session_state:
    st.info("尚無可顯示的考試結果，請先完成一次模擬考。")
    st.switch_page("pages/2_開始考試_模擬考.py")

results_df = st.session_state.results_df
score_tuple = st.session_state.score_tuple
wrong_df = st.session_state.get("wrong_df")
summary = st.session_state.get("mock_summary")  # ✅ 兩節連考資訊（若有）

# ========= 小工具：兼容欄位名稱（避免舊資料/舊DB wrong_log 造成 KeyError） =========
def _get_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, (tuple, set)):
        return list(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        # 可能是 JSON string
        try:
            j = json.loads(s)
            if isinstance(j, list):
                return j
        except Exception:
            pass
        # 可能是 "A, B" 這種
        if "," in s:
            return [x.strip() for x in s.split(",") if x.strip()]
        return [s]
    return [str(v)]

def _normalize_choices(choices):
    """
    choices 可能型態：
    - [("A","xxx"), ("B","yyy")]
    - [["A","xxx"], ["B","yyy"]]
    - ["A.xxx", "B.yyy"]
    - JSON string
    """
    if choices is None:
        return []

    if isinstance(choices, str):
        s = choices.strip()
        if not s:
            return []
        try:
            j = json.loads(s)
            choices = j
        except Exception:
            return [s]

    if not isinstance(choices, list):
        return [str(choices)]

    # list of pairs
    if len(choices) > 0 and isinstance(choices[0], (list, tuple)) and len(choices[0]) >= 2:
        out = []
        for it in choices:
            try:
                out.append((str(it[0]), str(it[1])))
            except Exception:
                out.append((str(it), ""))
        return out

    # list of strings
    return [str(x) for x in choices]

def _pick_answers(row):
    """
    兼容不同版本欄位：
    - 新版：YourAnswer / CorrectAnswer
    - 舊版：Your Answer / Correct
    - 其他：Answer
    """
    # 你的作答
    ya = row.get("YourAnswer", None)
    if ya is None:
        ya = row.get("Your Answer", None)

    # 正確答案
    ca = row.get("CorrectAnswer", None)
    if ca is None:
        ca = row.get("Correct", None)
    if ca is None:
        ca = row.get("Answer", None)

    return _get_list(ya), _get_list(ca)

def _render_one_wrong(row):
    qid = row.get("ID", "")
    st.write(row.get("Question", ""))

    # 選項
    choices = _normalize_choices(row.get("Choices", []))
    if choices:
        st.markdown("**所有選項**")
        if len(choices) > 0 and isinstance(choices[0], tuple):
            for lab, txt in choices:
                st.write(f"- {lab}. {txt}")
        else:
            for c in choices:
                st.write(f"- {c}")

    ya, ca = _pick_answers(row)

    # 你的作答
    st.markdown("**你的作答**")
    st.write(", ".join(map(str, ya)) if ya else "（未作答）")

    # 正確答案
    st.markdown("**正確答案**")
    st.write(", ".join(map(str, ca)) if ca else "（無）")

    exp = row.get("Explanation", "")
    if isinstance(exp, str) and exp.strip():
        st.markdown("**題庫解析**")
        st.info(exp)

    # AI 詳解（保留原功能）
    if ai.gemini_ready():
        if st.button(f"🧠 生成詳解（{qid}）", key=f"ai_explain_{qid}"):
            q = {
                "ID": qid,
                "Question": row.get("Question", ""),
                "Choices": choices if choices else [],
                "Answer": ca if ca else [],
                "Type": row.get("Type", ""),
                "Explanation": row.get("Explanation", ""),
            }
            ck, sys, usr = ai.build_explain_prompt(q)
            with st.spinner("AI 生成詳解中…"):
                explain = ai.gemini_generate_cached(ck, sys, usr)
            st.info(explain)

# ========= 成績區（優先用 mock_summary；其次用 session_state 四欄；最後用 score_tuple） =========
if summary:
    total_score = summary.get("total_score", score_tuple[2] if score_tuple else 0)
    passed = summary.get("passed", st.session_state.get("passed", None))
    fail_reason = summary.get("fail_reason", st.session_state.get("fail_reason", None))
    sections = summary.get("sections", [])

    # passed 可能是 True/False 或 1/0
    if passed in (True, 1):
        st.success(f"總分：{total_score} 分 ✅ 合格")
    elif passed in (False, 0):
        msg = f"總分：{total_score} 分 ❌ 不合格"
        if fail_reason:
            msg += f"（原因：{fail_reason}）"
        st.error(msg)
    else:
        st.success(f"總分：{total_score} 分")

    # 分節成績（保留原功能，改成用 DataFrame 顯示更穩）
    if sections:
        st.subheader("分節成績")
        view = []
        for i, s in enumerate(sections, start=1):
            view.append({
                "節次": f"第 {i} 節",
                "科目": s.get("name", ""),
                "分數": s.get("score", ""),
                "答對/題數": f"{s.get('correct','')}/{s.get('total','')}",
            })
        st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)

else:
    correct, total, score = score_tuple
    st.success(f"成績：{score} 分（答對 {correct}/{total}）")

# ========= 作答總表 =========
st.subheader("作答總表")
st.dataframe(results_df, use_container_width=True, hide_index=True)

# ========= 錯題解析 =========
st.divider()
st.subheader("錯題解析")

if wrong_df is None or wrong_df.empty:
    st.success("本次作答沒有錯題。")
else:
    # 每題一個 expander（保留原功能）
    for _, r in wrong_df.iterrows():
        qid = r.get("ID", "")
        with st.expander(f"{qid}", expanded=False):
            _render_one_wrong(r)

# ========= 底部：結束考試 → 回首頁 =========
st.divider()

def _reset_exam_state():
    # 只清「模擬考流程」相關 state，避免影響登入狀態等
    keys = [
        "paper", "answers", "started", "show_results", "saved_to_db", "start_ts",
        "time_limit",
        "results_df", "score_tuple", "wrong_df",
        "df", "current_bank_name",
        # ✅ 兩節連考新增 keys
        "mock_section_idx", "mock_section_results", "mock_exam_start_ts", "mock_summary",
        # ✅ 四欄（若你有另存）
        "section_scores", "total_score", "passed", "fail_reason",
    ]
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]

# ✅ 回首頁
if st.button("結束考試，回到首頁", type="primary"):
    _reset_exam_state()
    st.switch_page("app.py")
