import streamlit as st
from utils import github_handler as gh
from services.exam_rules import CERT_CATALOG, MOCK_SPECS

def render_exam_settings(mode: str = "practice"):
    """
    Sidebar 設定元件：
    - practice (練習模式)：只負責「選擇題庫檔案」。
      (注意：題數、標籤篩選、亂序等設定，改由 pages/1_...py 載入資料後自行在 sidebar 渲染，以實現動態 Tag 篩選)
      
    - mock (模擬考模式)：負責完整的模擬考規格設定。
    """
    st.subheader("題庫設定")

    mode = (mode or "practice").lower().strip()
    if mode not in ("practice", "mock"):
        mode = "practice"

    # 通用設定
    show_image = st.checkbox("顯示圖片", value=True, key=f"sb_showimg_{mode}")

    # =========================
    # 練習模式：只回傳「檔案來源」，其餘設定交給頁面控制
    # =========================================
    if mode == "practice":
        bank_type = st.selectbox("1. 選擇證照類型", options=gh.BANK_TYPES, key="sb_bank_type_practice")

        merge_all = st.checkbox("合併該類型所有題庫", value=False, key="sb_merge_all_practice")

        bank_source = None
        if not merge_all:
            default_path = gh.get_current_bank_path(bank_type)
            files = gh.list_bank_files(bank_type) or []
            options = []
            if default_path and default_path in files:
                options.append(default_path)
            options += [p for p in files if p != default_path]

            if options:
                bank_source = st.selectbox("2. 選擇題庫檔案", options=options, key="sb_bank_source_practice")
            else:
                st.warning("⚠️ 此類型尚無題庫檔案")

        # 回傳基礎設定，剩下的 (Tag/題數/開始按鈕) 由頁面層處理
        return {
            "mode": "practice",
            "bank_type": bank_type,
            "merge_all": merge_all,
            "bank_source": bank_source,
            "show_image": show_image,
        }

    # =========================
    # 模擬考模式：維持原樣 (包含完整規格)
    # =========================
    # 模擬考也移除「選項洗牌」，避免詳解衝突
    # shuffle_options = st.checkbox("選項洗牌", value=False, key=f"sb_shuffle_{mode}") 
    
    # 模擬考通常強制亂序，這裡我們給個顯示即可
    st.caption("ℹ️ 模擬考模式預設為：題目亂序、選項不洗牌")

    cert_type = st.selectbox(
        "證照類別",
        options=list(CERT_CATALOG.keys()),
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

    # 鎖定模擬考規格
    spec = MOCK_SPECS.get(cert_type)
    mock_sections = spec["sections"] if spec else []
    total_time_min = sum(s.get("time_min", 0) for s in mock_sections) if mock_sections else 0
    mock_time_limit_sec = int(total_time_min * 60)

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

    return {
        "mode": "mock",
        "cert_type": cert_type,
        "subject": subject,
        "bank_path": bank_path,
        "mock_spec": spec,
        "mock_sections": mock_sections,
        "mock_time_limit_sec": mock_time_limit_sec,
        "random_order": True,   # 模擬考強制亂序
        "shuffle_options": False, # 強制不洗牌
        "show_image": show_image,
        
        # 兼容欄位
        "bank_type": None,
        "merge_all": False,
        "bank_source": None,
        "n_questions": None,
    }
