import streamlit as st
from utils import github_handler as gh

def render_exam_settings():
    st.subheader("題庫與考試設定")

    bank_type = st.selectbox("題庫類型", options=gh.BANK_TYPES, key="sb_bank_type")

    merge_all = st.checkbox("合併載入此類型下所有題庫檔", value=False, key="sb_merge_all")

    bank_source = None
    if not merge_all:
        # 預設題庫
        default_path = gh.get_current_bank_path(bank_type)
        files = gh.list_bank_files(bank_type) or []
        options = []
        if default_path and default_path in files:
            options.append(default_path)
        options += [p for p in files if p != default_path]

        bank_source = st.selectbox("選擇題庫檔案", options=options, key="sb_bank_source") if options else None

    n_questions = st.slider("題數", min_value=1, max_value=100, value=20, step=1, key="sb_nq")
    shuffle_options = st.checkbox("選項洗牌", value=True, key="sb_shuffle")
    show_image = st.checkbox("顯示圖片", value=True, key="sb_showimg")

    return {
        "bank_type": bank_type,
        "merge_all": merge_all,
        "bank_source": bank_source,
        "n_questions": n_questions,
        "shuffle_options": shuffle_options,
        "show_image": show_image,
    }
