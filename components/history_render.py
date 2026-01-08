import json
import re
import streamlit as st
import pandas as pd


def _format_bank_type(s: str) -> str:
    """
    目標：
    - "人身 - bank/人身/人身.xlsx[範圍: ...]" -> "人身[範圍: ...]"
    - "人身 - bank/人身/人身.xlsx" -> "人身"
    - "人身" -> "人身"
    """
    if not isinstance(s, str) or not s.strip():
        return ""

    s = s.strip()

    # 拆出範圍（若有）
    range_part = ""
    m = re.search(r"(\[範圍:.*\])", s)
    if m:
        range_part = m.group(1)

    # 主類型（取最前面，遇到 " - " 就截斷）
    main = s.split(" - ", 1)[0].strip()

    return f"{main}{range_part}"


def _parse_wrong_log(wrong_log):
    """
    wrong_log 可能是：
    - list[dict]
    - JSON string
    - None
    """
    if not wrong_log:
        return []

    if isinstance(wrong_log, list):
        return wrong_log

    if isinstance(wrong_log, str):
        try:
            return json.loads(wrong_log)
        except Exception:
            return []

    return []


def _ensure_list(v):
    """把可能的 JSON 字串轉回 list；不是就原樣回傳或回傳空 list。"""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        s = v.strip()
        if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
            try:
                parsed = json.loads(s)
                return parsed if isinstance(parsed, list) else [parsed]
            except Exception:
                return []
    return []


def _get_item_field(item: dict, keys: list, default=None):
    """依序找 key，找到就回傳（支援舊/新欄位名）。"""
    for k in keys:
        if k in item and item.get(k) is not None:
            return item.get(k)
    return default


def _render_one_wrong_question(item: dict):
    qid = _get_item_field(item, ["ID"], "")
    qtext = _get_item_field(item, ["Question"], "")
    qtype = _get_item_field(item, ["Type"], "")
    tag = _get_item_field(item, ["Tag"], "")

    st.markdown(f"### {qid}  {f'({tag})' if tag else ''}")
    if qtype:
        st.caption(f"題型：{qtype}")

    if qtext:
        st.write(qtext)

    # 選項（兼容 list/JSON 字串）
    choices = _get_item_field(item, ["Choices"], [])
    choices = _ensure_list(choices)

    if choices:
        st.markdown("**所有選項**")
        # choices 可能是 [("A","xxx"), ("B","yyy")] 或 ["A. xxx", "B. yyy"]
        if isinstance(choices, list) and len(choices) > 0 and isinstance(choices[0], (list, tuple)) and len(choices[0]) >= 2:
            for lab, txt in choices:
                st.write(f"- {lab}. {txt}")
        else:
            for c in choices:
                st.write(f"- {c}")

    # ✅ 你的作答 / 正確答案：同時兼容舊欄位與新欄位
    your_ans = _get_item_field(item, ["YourAnswer", "Your Answer", "your_answer"], [])
    correct_ans = _get_item_field(item, ["CorrectAnswer", "Correct", "correct_answer"], [])

    # 有些情況會以字串存，例如 "['A','B']" 或 '["A","B"]'，做保底
    if isinstance(your_ans, str):
        try:
            your_ans = json.loads(your_ans)
        except Exception:
            your_ans = [your_ans]

    if isinstance(correct_ans, str):
        try:
            correct_ans = json.loads(correct_ans)
        except Exception:
            correct_ans = [correct_ans]

    st.markdown("**你的作答**")
    st.write(", ".join(map(str, your_ans)) if your_ans else "（未作答）")

    st.markdown("**正確答案**")
    st.write(", ".join(map(str, correct_ans)) if correct_ans else "（無）")

    exp = _get_item_field(item, ["Explanation"], "")
    if isinstance(exp, str) and exp.strip():
        st.markdown("**題庫解析**")
        st.info(exp)


def render_history(history_df: pd.DataFrame):
    if history_df is None or history_df.empty:
        st.info("尚無歷史成績。")
        return

    # 先做排序（新到舊）
    df = history_df.copy()
    if "exam_date" in df.columns:
        try:
            df = df.sort_values("exam_date", ascending=False)
        except Exception:
            pass
    df = df.reset_index(drop=True)

    # 顯示用欄位：不顯示 id、不顯示 wrong_log，也不顯示左側 index
    show_cols = []
    for c in ["bank_type", "score", "duration_seconds", "exam_date"]:
        if c in df.columns:
            show_cols.append(c)

    view_df = df[show_cols].copy()

    # bank_type：去掉路徑、保留範圍
    if "bank_type" in view_df.columns:
        view_df["bank_type"] = view_df["bank_type"].astype(str).apply(_format_bank_type)

    # exam_date：保留到「年月日 時:分」
    if "exam_date" in view_df.columns:
        dt = pd.to_datetime(view_df["exam_date"], errors="coerce")
        view_df["exam_date"] = dt.dt.strftime("%Y-%m-%d %H:%M")

    st.subheader("歷史成績")

    # 可點選單列（Streamlit 1.32+ 支援 selection）
    event = st.dataframe(
        view_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="history_table",
    )

    # 取得選取的那一列
    selected_rows = getattr(event, "selection", None)
    selected_idx = None
    if selected_rows and selected_rows.rows:
        selected_idx = selected_rows.rows[0]

    st.divider()
    st.subheader("錯題檢討")

    if selected_idx is None:
        st.info("請先在上方表格點選一筆作答紀錄。")
        return

    row = df.iloc[selected_idx]
    wrong_items = _parse_wrong_log(row.get("wrong_log"))

    # 若本次沒有錯題
    if not wrong_items:
        st.success("本次作答沒有錯題。")
        return

    header = f"{_format_bank_type(str(row.get('bank_type','')))}｜{row.get('exam_date','')}"
    st.caption(f"已選取：{header}")

    for i, item in enumerate(wrong_items, start=1):
        qid = item.get("ID", f"Q{i}")
        with st.expander(f"第 {i} 題｜{qid}", expanded=(i == 1)):
            _render_one_wrong_question(item)
