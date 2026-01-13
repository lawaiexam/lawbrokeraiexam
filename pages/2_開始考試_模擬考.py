import time
import pandas as pd
import streamlit as st

from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from services.bank_service import load_bank_df
from services.exam_service import build_paper, grade_paper, persist_exam_record
from services.exam_rules import CERT_CATALOG  # ✅ 用 section name 對應題庫路徑
from components.auth_ui import render_user_panel
from components.sidebar_exam_settings import render_exam_settings
from components.question_render import render_question

ensure_state()

# ========= Sidebar =========
with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None:
    st.stop()

st.title("開始考試 - 模擬考")

with st.sidebar:
    # ✅ 模擬考走 mock 模式（證照/科目映射 + 規則鎖定）
    settings = render_exam_settings(mode="mock")

spec = settings.get("mock_spec") or {}
sections = spec.get("sections") or []
if not sections:
    st.error("此證照類別沒有設定模擬考規則（MOCK_SPECS）。")
    st.stop()

# ========= 初始化「兩節連考」state =========
if "mock_section_idx" not in st.session_state:
    st.session_state.mock_section_idx = 0

if "mock_section_results" not in st.session_state:
    st.session_state.mock_section_results = []

# 用於整場模擬考的起始時間（總耗時）
if "mock_exam_start_ts" not in st.session_state:
    st.session_state.mock_exam_start_ts = None

# ========= 取得目前節次 =========
sec_idx = int(st.session_state.mock_section_idx)
if sec_idx >= len(sections):
    # 保險：超界就重置
    st.session_state.mock_section_idx = 0
    st.session_state.mock_section_results = []
    st.session_state.mock_exam_start_ts = None
    sec_idx = 0

section = sections[sec_idx]
section_name = section.get("name", f"Section{sec_idx+1}")
n_questions = int(section.get("n_questions", 0))
time_limit_sec = int(section.get("time_min", 0) * 60)

if n_questions <= 0 or time_limit_sec <= 0:
    st.error("模擬考規則設定不完整（題數或時間為 0），請檢查 MOCK_SPECS。")
    st.stop()

# ========= 載入本節題庫（依 section name 對應固定 Excel） =========
try:
    bank_path = CERT_CATALOG[settings["cert_type"]]["subjects"][section_name]
except Exception:
    st.error(f"找不到題庫映射：{settings['cert_type']} → {section_name}。請檢查 CERT_CATALOG 的 subjects key 是否一致。")
    st.stop()

# 🛠️ 修正點：將 bank_source 改為 bank_source_path
df = load_bank_df(
    settings.get("cert_type", ""),  
    merge_all=False,
    bank_source_path=bank_path  # ✅ 改成正確的參數名稱
)

if df is None or df.empty:
    st.warning("尚未載入題庫，請確認題庫檔案是否存在且可讀取。")
    st.stop()

st.session_state.df = df

# ✅ 模擬考不選章節：直接全選
filtered = df

# ✅ 歷史紀錄用名稱：統一為「證照｜模擬考」
exam_label = f"{settings['cert_type']}｜模擬考"
st.session_state.current_bank_name = exam_label

# ========= 顯示目前節次與總規格 =========
with st.expander("本次模擬考規格（固定）", expanded=True):
    st.write(f"- 類別：{settings['cert_type']}")
    st.write(f"- 模式：兩節連考" if len(sections) > 1 else "- 模式：單節")
    st.write("")

    for i, s in enumerate(sections, start=1):
        st.write(f"- 第 {i} 節：{s['name']}｜{s['n_questions']} 題｜{s['time_min']} 分鐘")

    if spec.get("mode") == "single":
        st.write(f"✅ 及格：{spec.get('pass_score')} 分")
    else:
        st.write(f"✅ 及格：合計 {spec.get('pass_total')} 分，且單科不低於 {spec.get('pass_min_each')} 分")

st.divider()
st.subheader(f"第 {sec_idx+1} 節：{section_name}")

# ========= 本節開始/重置 =========
colA, colB = st.columns([1, 1])

def _reset_whole_mock_exam():
    # 本節狀態
    for k in ["paper", "answers", "started", "show_results", "saved_to_db", "start_ts", "time_limit"]:
        if k in st.session_state:
            del st.session_state[k]

    # 整場狀態
    st.session_state.mock_section_idx = 0
    st.session_state.mock_section_results = []
    st.session_state.mock_exam_start_ts = None

    # 成績顯示用（避免舊資料殘留）
    for k in ["mock_summary", "score_tuple", "wrong_df", "results_df",
              "section_scores", "total_score", "passed", "fail_reason"]:
        if k in st.session_state:
            del st.session_state[k]

with colA:
    if st.button("開始本節", type="primary"):
        st.session_state.paper = build_paper(
            filtered,
            n_questions,
            random_order=True,
            shuffle_options=settings["shuffle_options"]
        )
        st.session_state.answers = {}
        st.session_state.started = True
        st.session_state.show_results = False
        st.session_state.saved_to_db = False

        # 本節開始時間（節次倒數）
        st.session_state.start_ts = time.time()

        # 整場開始時間（總耗時）
        if st.session_state.mock_exam_start_ts is None:
            st.session_state.mock_exam_start_ts = st.session_state.start_ts

        # ✅ 本節時間鎖定
        st.session_state.time_limit = time_limit_sec
        st.rerun()

with colB:
    if st.button("重置整場模擬考", type="secondary"):
        _reset_whole_mock_exam()
        st.rerun()

paper = st.session_state.get("paper")
if not paper:
    st.info("請先按「開始本節」。")
    st.stop()

# ========= Timer（本節倒數） =========
if st.session_state.get("time_limit") and st.session_state.get("start_ts"):
    elapsed = int(time.time() - st.session_state.start_ts)
    remain = max(0, st.session_state.time_limit - elapsed)
    
    # 🟢 修改開始：計算分與秒，並格式化顯示
    mins, secs = divmod(remain, 60)
    time_str = f"{mins} 分 {secs:02d} 秒"
    st.metric("本節剩餘時間", time_str)
    # 🟢 修改結束

    if remain == 0 and not st.session_state.get("show_results"):
        st.warning("本節時間到，自動交卷。")
        st.session_state.show_results = True
        st.rerun()

# ========= 作答區（未交卷才顯示） =========
if not st.session_state.get("show_results"):
    st.subheader("作答區")
    for idx, q in enumerate(paper, start=1):
        with st.expander(f"第 {idx} 題", expanded=(idx == 1)):
            picked = render_question(
                q,
                show_image=settings["show_image"],
                answer_key=f"mock_s{sec_idx}_ans_{q['ID']}"
            )
            st.session_state.answers[q["ID"]] = picked

    if st.button("交卷（本節）", type="primary"):
        st.session_state.show_results = True
        st.rerun()

# ========= 交卷後：本節計分 → 存入 section_results → 進下一節或結束 =========
if not st.session_state.get("show_results"):
    st.stop()

results_df, score_tuple, wrong_df = grade_paper(paper, st.session_state.answers)
correct, total, score = score_tuple

# 存本節結果（供最後合併、也供 page5 顯示）
st.session_state.mock_section_results.append({
    "section": section_name,
    "score": int(score),
    "correct": int(correct),
    "total": int(total),
    "results_df": results_df,
    "wrong_df": wrong_df,
})

# ========= 若還有下一節：切換到下一節 =========
st.session_state.mock_section_idx += 1

if st.session_state.mock_section_idx < len(sections):
    st.success(f"已完成第 {sec_idx+1} 節：{section_name}（{score} 分）。")

    # 清掉本節狀態，準備下一節
    st.session_state.paper = None
    st.session_state.answers = {}
    st.session_state.started = False
    st.session_state.show_results = False
    st.session_state.saved_to_db = False
    st.session_state.start_ts = None
    st.session_state.time_limit = None

    if st.button("前往下一節", type="primary"):
        st.rerun()
    st.stop()

# ========= 最後一節完成：合併判分 → 寫 DB → 跳結果頁 =========
section_results = st.session_state.mock_section_results

# ✅ 四欄：section_scores / total_score / passed / fail_reason
section_scores = {s["section"]: int(s["score"]) for s in section_results}
total_score = int(sum(s["score"] for s in section_results))
min_each = int(min(s["score"] for s in section_results)) if section_results else 0

passed = True
fail_reason = None

if spec.get("mode") == "single":
    pass_score = int(spec.get("pass_score", 0))
    passed = total_score >= pass_score
    if not passed:
        fail_reason = "分數未達及格標準"
else:
    pass_total = int(spec.get("pass_total", 0))
    pass_min_each = int(spec.get("pass_min_each", 0))
    passed = (total_score >= pass_total) and (min_each >= pass_min_each)
    if not passed:
        if total_score < pass_total:
            fail_reason = "總分不足"
        elif min_each < pass_min_each:
            fail_reason = "單科未達最低標準"

passed_db = 1 if passed else 0

# 合併錯題（兩節一起）
all_wrong_df = pd.concat([s["wrong_df"] for s in section_results], ignore_index=True) if section_results else pd.DataFrame()

# 合併 results_df（供 page5 顯示全列表）
all_results_df = pd.concat([s["results_df"] for s in section_results], ignore_index=True) if section_results else pd.DataFrame()

# 存給 page5 顯示（新版）
st.session_state.mock_summary = {
    "cert_type": settings["cert_type"],
    "sections": [{"name": s["section"], "score": s["score"], "correct": s["correct"], "total": s["total"]} for s in section_results],
    "section_scores": section_scores,
    "total_score": total_score,
    "passed": passed,
    "fail_reason": fail_reason,
}

# 也把四欄獨立存一份（page5 取用更直覺）
st.session_state.section_scores = section_scores
st.session_state.total_score = total_score
st.session_state.passed = passed_db
st.session_state.fail_reason = fail_reason

# 保留舊欄位（避免你 page5 或其他頁還在用 score_tuple/wrong_df）
total_correct = int(sum(s["correct"] for s in section_results))
total_q = int(sum(s["total"] for s in section_results))
st.session_state.score_tuple = (total_correct, total_q, total_score)
st.session_state.wrong_df = all_wrong_df
st.session_state.results_df = all_results_df

# ========= 寫 DB（只寫一次：整場模擬考） =========
if not st.session_state.get("saved_to_db") and st.session_state.get("mock_exam_start_ts"):
    duration_sec = int(time.time() - st.session_state.mock_exam_start_ts)
    try:
        persist_exam_record(
            user,
            exam_label,
            (total_correct, total_q, total_score),
            duration_sec,
            all_wrong_df,
            section_scores=section_scores,
            total_score=total_score,
            passed=passed_db,
            fail_reason=fail_reason
        )
        st.session_state.saved_to_db = True
    except Exception as e:
        st.error(f"寫入成績失敗：{e}")
        st.stop()

# ========= 清理流程狀態（避免回上一頁再進來亂掉） =========
# 保留：mock_summary/score_tuple/results_df/wrong_df/四欄 供 page5 使用
st.session_state.paper = None
st.session_state.answers = {}
st.session_state.started = False
st.session_state.show_results = False
st.session_state.start_ts = None
st.session_state.time_limit = None

# ✅ 跳到結果頁（請確保檔名一致）
st.switch_page("pages/5_模擬考_成績與錯題解析.py")
