import streamlit as st
from utils import github_handler as gh
from services.exam_rules import CERT_CATALOG, MOCK_SPECS

def render_exam_settings(mode: str = "practice"):
    """
    折衷版 Sidebar：
    - practice(練習模式)：保留你原本的「bank_type + 選檔 + merge_all」
    - mock(模擬考模式)：改成「證照類別(人身/投資型/外幣) + 科目」，並鎖定題數/時間（由 MOCK_SPECS 套用）
    
    回傳的 dict 會同時包含：
    - practice：bank_type / merge_all / bank_source / n_questions / random_order
    - mock：cert_type / subject / bank_path / mock_sections / mock_time_limit_sec / random_order
    頁面端用 mode 決定讀哪一套欄位即可。
    """
    st.subheader("題庫與考試設定")

    mode = (mode or "practice").lower().strip()
    if mode not in ("practice", "mock"):
        mode = "practice"

    # 🟢【修正】：新增「題目亂序」選項，並確保回傳此 Key
    random_order = st.checkbox("題目亂序", value=True, key=f"sb_random_{mode}")
    shuffle_options = st.checkbox("選項洗牌", value=True, key=f"sb_shuffle_{mode}")
    show_image = st.checkbox("顯示圖片", value=True, key=f"sb_showimg_{mode}")

    # =========================
    # 練習模式：沿用原本選檔邏輯
    # =========================
    if mode == "practice":
        bank_type = st.selectbox("題庫類型", options=gh.BANK_TYPES, key="sb_bank_type_practice")

        merge_all = st.checkbox("合併載入此類型下所有題庫檔", value=False, key="sb_merge_all_practice")

        bank_source = None
        if not merge_all:
            default_path = gh.get_current_bank_path(bank_type)
            files = gh.list_bank_files(bank_type) or []
            options = []
            if default_path and default_path in files:
                options.append(default_path)
            options += [p for p in files if p != default_path]

            bank_source = st.selectbox("選擇題庫檔案", options=options, key="sb_bank_source_practice") if options else None

        n_questions = st.slider("題數", min_value=1, max_value=200, value=20, step=1, key="sb_nq_practice")

        return {
            "mode": "practice",
            "bank_type": bank_type,
            "merge_all": merge_all,
            "bank_source": bank_source,
            "n_questions": n_questions,
            "random_order": random_order,    # ✅ 補上這個 Key
            "shuffle_options": shuffle_options,
            "show_image": show_image,
        }

    # =========================
    # 模擬考模式：證照/科目映射 + 鎖定題數/時間
    # =========================
    cert_type = st.selectbox(
        "證照類別",
        options=list(CERT_CATALOG.keys()),  # 人身/投資型/外幣
        key="sb_cert_type_mock"
    )

    subjects = list(CERT_CATALOG[cert_type]["subjects"].keys())
    subject = st.selectbox(
        "考科 / 節次",
        options=subjects,
        key="sb_subject_mock"
    )

    bank_path = CERT_CATALOG[cert_type]["subjects"][subject]
    st.caption(f"題庫檔案：{bank_path}")

    # 鎖定模擬考規格（題數/時間/及格規則由 MOCK_SPECS 決定）
    spec = MOCK_SPECS.get(cert_type)
    mock_sections = spec["sections"] if spec else []
    # 模擬考頁面如果目前只做單科/單節，也能用這個先顯示規格讓你核對
    total_time_min = sum(s.get("time_min", 0) for s in mock_sections) if mock_sections else 0
    mock_time_limit_sec = int(total_time_min * 60)

    # 顯示規則給你確認（不可改）
    with st.expander("模擬考規格（固定）", expanded=True):
        if not mock_sections:
            st.warning("找不到此證照類別的模擬考規格。")
        else:
            for s in mock_sections:
                st.write(f"- {s['name']}：{s['n_questions']} 題 / {s['time_min']} 分鐘")
            st.write(f"⏱️ 總時間：{total_time_min} 分鐘")

        if spec:
            if spec.get("mode") == "single":
                st.write(f"✅ 及格：{spec.get('pass_score')} 分")
            else:
                st.write(f"✅ 及格：合計 {spec.get('pass_total')} 分，且單科不低於 {spec.get('pass_min_each')} 分")

    # 模擬考不讓你改題數：回傳 None 或 0，頁面直接改用 mock_sections
    return {
        "mode": "mock",
        "cert_type": cert_type,
        "subject": subject,
        "bank_path": bank_path,
        "mock_spec": spec,
        "mock_sections": mock_sections,
        "mock_time_limit_sec": mock_time_limit_sec,
        "random_order": random_order,   # ✅ 補上這個 Key (雖然模擬考通常強制亂序，但補上可避免報錯)
        "shuffle_options": shuffle_options,
        "show_image": show_image,

        # 兼容欄位（避免舊頁面直接讀到 KeyError）
        "bank_type": None,
        "merge_all": False,
        "bank_source": None,
        "n_questions": None,
    }
