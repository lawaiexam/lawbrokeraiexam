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


def _parse_json_field(v):
    """
    安全解析 JSON 欄位 (section_scores, wrong_log 等)
    """
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return None
    return None


def _format_section_scores_str(v) -> str:
    """
    將 dict 轉為顯示字串：
    {'保險法規': 80, '保險實務': 60} -> '保險法規:80 | 保險實務:60'
    """
    data = _parse_json_field(v)
    if not isinstance(data, dict) or not data:
        return ""
    # 格式化為 "Key: Val | Key: Val"
    return " | ".join([f"{k}:{v}" for k, v in data.items()])


def _parse_wrong_log(wrong_log):
    """
    wrong_log 可能是：list[dict] / JSON string / None
    """
    data = _parse_json_field(wrong_log)
    if isinstance(data, list):
        return data
    return []


def _ensure_list(v):
    """把可能的 JSON 字串轉回 list"""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    parsed = _parse_json_field(v)
    if isinstance(parsed, list):
        return parsed
    return [v] if v is not None else []


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

    # 選項
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

    # ✅ 你的作答 / 正確答案
    your_ans = _get_item_field(item, ["YourAnswer", "Your Answer", "your_answer"], [])
    correct_ans = _get_item_field(item, ["CorrectAnswer", "Correct", "correct_answer"], [])

    # 確保是 List
    your_ans = _ensure_list(your_ans)
    correct_ans = _ensure_list(correct_ans)

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

    # --- 準備顯示用的 View DataFrame ---
    view_df = df.copy()

    # 1. 處理題庫名稱
    if "bank_type" in view_df.columns:
        view_df["bank_type"] = view_df["bank_type"].astype(str).apply(_format_bank_type)

    # 2. 處理日期格式
    if "exam_date" in view_df.columns:
        dt = pd.to_datetime(view_df["exam_date"], errors="coerce")
        view_df["exam_date"] = dt.dt.strftime("%Y-%m-%d %H:%M")

    # 3. 處理分節成績 (New!)
    if "section_scores" in view_df.columns:
        view_df["分節成績"] = view_df["section_scores"].apply(_format_section_scores_str)
    
    # 4. 處理合格狀態 (New!)
    if "passed" in view_df.columns:
        def _fmt_pass(x):
            if x in (1, True, "1", "True"): return "✅"
            if x in (0, False, "0", "False"): return "❌"
            return ""
        view_df["合格"] = view_df["passed"].apply(_fmt_pass)

    # 定義欄位對照
    cols_map = {
        "exam_date": "考試時間",
        "bank_type": "題庫/證照",
        "score": "總分",
        "分節成績": "分節明細",
        "合格": "狀態",
    }
    
    # 篩選存在的欄位並重新命名
    desired_order = ["exam_date", "bank_type", "score", "合格", "分節成績"]
    final_cols = [c for c in desired_order if c in view_df.columns]
    display_df = view_df[final_cols].rename(columns=cols_map)

    st.subheader("歷史成績列表")
    st.caption("💡 點擊列表中的任一列，可於下方查看「詳細成績」與「錯題檢討」。")

    # 顯示互動表格
    event = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="history_table",
    )

    # 取得選取的那一列索引
    selected_rows = getattr(event, "selection", None)
    selected_idx = None
    if selected_rows and selected_rows.rows:
        selected_idx = selected_rows.rows[0]

    st.divider()

    # --- 若未選取 ---
    if selected_idx is None:
        st.info("請在上方表格點選一筆紀錄以查看詳情。")
        return

    # 取得原始資料列 (包含 wrong_log, fail_reason 等原始資料)
    row = df.iloc[selected_idx]
    
    # --- 1. 考試結果詳情 (New!) ---
    st.subheader("📝 考試結果詳情")

    # 解析資料
    s_scores = _parse_json_field(row.get("section_scores"))
    passed_val = row.get("passed")
    is_passed = passed_val in (1, True, "1", "True")
    fail_reason = row.get("fail_reason")
    
    # 優先使用 total_score，若無則用 score
    total_score = row.get("total_score")
    if pd.isna(total_score):
        total_score = row.get("score")
    
    # 顯示 Header：總分與狀態
    c1, c2 = st.columns([1, 2])
    with c1:
        st.metric("總分", f"{int(total_score) if pd.notna(total_score) else 0}")
    with c2:
        if is_passed:
            st.success("🎉 **合格**")
        else:
            reason_str = f"（原因：{fail_reason}）" if fail_reason else ""
            st.error(f"❌ **不合格**{reason_str}")

    # 顯示分節成績細項
    if isinstance(s_scores, dict) and s_scores:
        st.write("**分節得分明細：**")
        # 轉成乾淨的小表格
        sec_items = [{"科目": k, "分數": v} for k, v in s_scores.items()]
        st.dataframe(pd.DataFrame(sec_items), hide_index=True, use_container_width=True)
    elif row.get("bank_type"): 
        # 如果是舊資料或練習模式沒有分節，顯示題庫名稱當作補充
        st.caption(f"考試項目：{_format_bank_type(str(row.get('bank_type')))}")

    st.divider()

    # --- 2. 錯題檢討 (保留原有邏輯) ---
    st.subheader("❌ 錯題檢討")
    wrong_items = _parse_wrong_log(row.get("wrong_log"))

    if not wrong_items:
        st.success("🎉 太棒了！本次作答沒有錯題。")
        return

    st.caption(f"錯題數量：{len(wrong_items)} 題")

    for i, item in enumerate(wrong_items, start=1):
        qid = item.get("ID", f"Q{i}")
        # 預設展開第一題
        with st.expander(f"第 {i} 題｜{qid}", expanded=(i == 1)):
            _render_one_wrong_question(item)