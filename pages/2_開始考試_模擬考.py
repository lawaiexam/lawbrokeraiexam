import time
import pandas as pd
import streamlit as st
import random
import re

from services.state_service import ensure_state
from services.auth_service import require_login_or_render
from services.bank_service import load_bank_df
from services.exam_service import grade_paper, persist_exam_record
from services.exam_rules import CERT_CATALOG
from components.auth_ui import render_user_panel
from components.sidebar_exam_settings import render_exam_settings
from components.question_render import render_question

# ==========================================
# 🟢 設定區：新版出題權重與章節映射 (源自 percentage.json)
# ==========================================

# 1. 考題結構定義 (NEW_EXAM_WEIGHTS)
# 這裡定義了：證照 -> 科目 (Subject) -> 章節 (Chapter) 的權重
NEW_EXAM_WEIGHTS = {
    "人身保險業務員資格測驗": {
        # 第一節：保險法規
        "life_regulation": {
            "insurance_law_core": 40,   # 保險法（總則／契約／基本規範）
            "solicitation_rules": 40,   # 招攬行為與業務員管理規範
            "liability_penalties": 20   # 責任歸屬與罰則
        },
        # 第二節：保險實務
        "life_practice": {
            "insurance_principles": 30, # 保險學原理與風險概念
            "life_products": 50,        # 人身保險商品
            "sales_practice_ethics": 20 # 招攬實務與倫理
        }
    },
    "外幣收付非投資型保險商品測驗": {
        # 單一科目
        "fx_exam": {
            "fx_basics": 28,                # 外匯與匯率基礎
            "fx_products": 28,              # 外幣非投資型商品與交易流程
            "fx_regulation_compliance": 22, # 法令規範與遵循
            "fx_risk_disclosure_practice": 22 # 風險揭露與銷售實務
        }
    },
    "投資型保險商品業務員測驗": {
        # 第一節：法令規章 (注意：實際考試順序可能不同，這裡以 Subject ID 為準)
        "il_regulations": {
            "sales_regulations": 50,    # 銷售規範與資訊揭露
            "suitability_rules": 30,    # 適合度規範
            "dispute_liability": 20     # 責任與爭議處理
        },
        # 第二節：投資實務
        "il_investment_practice": {
            "investment_basics": 45,        # 投資工具與風險報酬
            "il_product_mechanics": 45,     # 投資型商品機制
            "customer_suitability_practice": 10 # 客戶適合度與銷售流程實務
        }
    }
}

# 2. 科目識別映射 (Subject Mapping)
# 透過模擬考設定的「節次名稱」來尋找對應的「Subject ID」
# 關鍵字比對：只要節次名稱包含 key 中的文字，就視為該科目
SUBJECT_IDENTIFIER = {
    "人身保險業務員資格測驗": {
        "法規": "life_regulation",
        "實務": "life_practice"
    },
    "外幣收付非投資型保險商品測驗": {
        "外幣": "fx_exam",
        "非投資": "fx_exam"
    },
    "投資型保險商品業務員測驗": {
        "法令": "il_regulations",
        "規章": "il_regulations",
        "第一節": "il_regulations", # 假設第一節是考法規
        "實務": "il_investment_practice",
        "第二節": "il_investment_practice" # 假設第二節是考實務
    }
}

# 3. 章節歸類映射 (Chapter Mapping)
# 將 AI 分類的「中文章節名稱」歸類到 JSON 定義的「Chapter ID」
CHAPTER_MAPPING = {
    # === 人身保險 ===
    "保險法規": { # 對應 Subject ID: life_regulation
        "保險契約": "insurance_law_core",
        "保險契約六大原則": "insurance_law_core",
        "契約解除、無效、失效、停效、復效": "insurance_law_core",
        "保險金與解約金": "insurance_law_core",
        "遺產稅、贈與稅": "insurance_law_core",
        "所得稅": "insurance_law_core",
        "金融消費者保護法": "insurance_law_core",
        "個人資料保護法": "insurance_law_core",
        "洗錢防制法": "liability_penalties", 
        "保險業務員相關法規及規定": "solicitation_rules"
    },
    "保險實務": { # 對應 Subject ID: life_practice
        "風險與風險管理": "insurance_principles",
        "人身保險歷史及生命表": "insurance_principles",
        "保險費架構、解約金、準備金、保單紅利": "insurance_principles",
        "保險中重要的角色": "insurance_principles",
        "人身保險意義、功能、分類": "life_products",
        "人身保險－人壽保險": "life_products",
        "人身保險－年金保險": "life_products",
        "人身保險－健康保險": "life_products",
        "人身保險－傷害保險": "life_products",
        "人身保險－其他人身保險": "life_products",
        "投保實務與行銷": "sales_practice_ethics",
        "繼承相關": "sales_practice_ethics"
    },

    # === 外幣保單 ===
    "外幣非投資型": { # 對應 Subject ID: fx_exam
        "壽險基本概念": "fx_basics",
        "人身保險業辦理以外幣收付之非投資型人身保險業務應具備資格條件及注意事項": "fx_products",
        "保險業辦理外匯業務管理辦法": "fx_regulation_compliance",
        "管理外匯條例": "fx_regulation_compliance",
        "外匯收支或交易申報辦法": "fx_regulation_compliance",
        "保險業辦理國外投資管理辦法": "fx_regulation_compliance",
        "保險業各類監控措施": "fx_regulation_compliance",
        "銷售應注意事項": "fx_risk_disclosure_practice",
        "新型態人身保險商品審查": "fx_risk_disclosure_practice",
        "投資型保險專設帳簿保管機構及投資標的應注意事項": "fx_risk_disclosure_practice",
        "投資型保險觀念": "fx_products" # 歸類到產品
    },

    # === 投資型保險 ===
    "投資型法規": { # 對應 Subject ID: il_regulations
        "投資型保險法令介紹": "sales_regulations",
        "證券投資信託及顧問之規範與制度": "sales_regulations",
        "銷售應注意事項": "sales_regulations",
        # 若有 AI 分類到這類，映射到適合度
        "適合度": "suitability_rules",
        "爭議處理": "dispute_liability"
    },
    "投資型實務": { # 對應 Subject ID: il_investment_practice
        "貨幣時間價值": "investment_basics",
        "債券評價": "investment_basics",
        "證券評價": "investment_basics",
        "風險、報酬與投資組合": "investment_basics",
        "資本資產訂價模式、績效": "investment_basics",
        "投資工具簡介": "investment_basics",
        "金融體系概述": "investment_basics",
        "投資型保險概論": "il_product_mechanics",
        "投資型保險觀念": "il_product_mechanics",
        "投資型保險專設帳簿保管機構及投資標的應注意事項": "il_product_mechanics",
        # 實務上的銷售流程
        "客戶適合度": "customer_suitability_practice"
    }
}

# ==========================================
# 🟢 核心函式：權重化抽題 (Advanced)
# ==========================================
def build_weighted_paper_v2(full_df, cert_type, section_name, total_questions, shuffle_options=False):
    """
    根據新版 JSON 邏輯進行抽題。
    1. 識別當前考科 (Subject)。
    2. 取得該考科的章節權重。
    3. 將 AI 分類映射到 JSON 章節 ID。
    4. 執行加權抽樣。
    """
    target_col = "AI分類章節"
    if full_df.empty or target_col not in full_df.columns:
        return full_df.sample(n=min(len(full_df), total_questions)).to_dict('records')

    # 1. 識別 Subject ID
    subject_id = None
    cert_identifiers = SUBJECT_IDENTIFIER.get(cert_type, {})
    
    # 嘗試用節次名稱來匹配 (例如 "第一節：保險法規" -> 匹配 "法規" -> "life_regulation")
    for keyword, sid in cert_identifiers.items():
        if keyword in section_name:
            subject_id = sid
            break
            
    # 如果找不到對應的 Subject，退回自然分佈抽樣
    if not subject_id:
        print(f"Warning: Could not identify subject for section '{section_name}' in cert '{cert_type}'. Using standard distribution.")
        return _build_paper_by_natural_distribution(full_df, total_questions)

    # 2. 取得該 Subject 的權重設定
    cert_weights = NEW_EXAM_WEIGHTS.get(cert_type, {})
    chapter_weights = cert_weights.get(subject_id, {})
    
    if not chapter_weights:
        return _build_paper_by_natural_distribution(full_df, total_questions)

    # 3. 建立映射表 (AI Chapter -> JSON Chapter ID)
    # 為了簡化，我們將 CHAPTER_MAPPING 扁平化搜尋，或建立一個臨時的大表
    # 這裡採用簡單策略：根據 subject_id 找對應的 mapping key
    mapping_key_map = {
        "life_regulation": "保險法規",
        "life_practice": "保險實務",
        "fx_exam": "外幣非投資型",
        "il_regulations": "投資型法規",
        "il_investment_practice": "投資型實務"
    }
    mapping_category = mapping_key_map.get(subject_id)
    current_mapping = CHAPTER_MAPPING.get(mapping_category, {})

    # 4. 為 DataFrame 標記 JSON Chapter ID
    # 如果找不到映射，標記為 "others"
    df_temp = full_df.copy()
    df_temp["JsonChapterID"] = df_temp[target_col].map(current_mapping).fillna("others")

    # 5. 計算各章節目標題數
    exam_pool = []
    
    # 遍歷權重設定 (例如 insurance_law_core: 40%)
    for ch_id, weight_pct in chapter_weights.items():
        target_count = int(round(total_questions * (weight_pct / 100)))
        
        # 從 df_temp 中找出屬於這個 ch_id 的題目
        # 注意：多個 AI 章節可能對應到同一個 ch_id
        chapter_pool = df_temp[df_temp["JsonChapterID"] == ch_id]
        
        available = len(chapter_pool)
        take_n = min(available, target_count)
        
        if take_n > 0:
            selected = chapter_pool.sample(n=take_n)
            exam_pool.append(selected)

    # 6. 補題機制 (處理 "others" 或 四捨五入造成的不足)
    current_selected = pd.concat(exam_pool) if exam_pool else pd.DataFrame()
    needed = total_questions - len(current_selected)
    
    if needed > 0:
        # 優先從 "others" (未歸類但屬於本檔的題目) 抽
        others_pool = df_temp[~df_temp.index.isin(current_selected.index)]
        if not others_pool.empty:
            extra = others_pool.sample(n=min(len(others_pool), needed))
            exam_pool.append(extra)
            
    # 合併
    if exam_pool:
        final_df = pd.concat(exam_pool)
    else:
        final_df = pd.DataFrame()

    # 7. 總數控制
    if len(final_df) > total_questions:
        final_df = final_df.sample(n=total_questions)

    # 8. 打亂
    final_df = final_df.sample(frac=1).reset_index(drop=True)
    return final_df.to_dict('records')

def _build_paper_by_natural_distribution(full_df, total_questions):
    """備用：依題庫自然分佈抽樣"""
    target_col = "AI分類章節"
    if target_col not in full_df.columns:
        return full_df.sample(n=min(len(full_df), total_questions)).to_dict('records')
        
    valid_df = full_df[full_df[target_col].notna()]
    if valid_df.empty: 
        return full_df.sample(n=min(len(full_df), total_questions)).to_dict('records')

    chapter_counts = valid_df[target_col].value_counts()
    total_bank_size = len(valid_df)
    exam_pool = []
    
    for chapter, count in chapter_counts.items():
        ratio = count / total_bank_size
        n_for_chapter = int(round(total_questions * ratio))
        if n_for_chapter == 0 and count > 0: n_for_chapter = 1
        chapter_df = valid_df[valid_df[target_col] == chapter]
        exam_pool.append(chapter_df.sample(n=min(len(chapter_df), n_for_chapter)))

    exam_df = pd.concat(exam_pool) if exam_pool else pd.DataFrame()
    
    if len(exam_df) < total_questions:
        rem = valid_df[~valid_df.index.isin(exam_df.index)]
        if not rem.empty:
            exam_df = pd.concat([exam_df, rem.sample(n=min(len(rem), total_questions - len(exam_df)))])
            
    if len(exam_df) > total_questions:
        exam_df = exam_df.sample(n=total_questions)
        
    return exam_df.sample(frac=1).reset_index(drop=True).to_dict('records')

# ==========================================
# 主程式開始
# ==========================================

ensure_state()

with st.sidebar:
    render_user_panel()

user = require_login_or_render()
if user is None: st.stop()

st.title("開始考試 - 模擬考")

with st.sidebar:
    settings = render_exam_settings(mode="mock")

spec = settings.get("mock_spec") or {}
sections = spec.get("sections") or []
if not sections:
    st.error("此證照類別沒有設定模擬考規則（MOCK_SPECS）。")
    st.stop()

# ========= 初始化狀態 =========
if "mock_section_idx" not in st.session_state: st.session_state.mock_section_idx = 0
if "mock_section_results" not in st.session_state: st.session_state.mock_section_results = []
if "mock_exam_start_ts" not in st.session_state: st.session_state.mock_exam_start_ts = None

# ========= 取得目前節次 =========
sec_idx = int(st.session_state.mock_section_idx)
if sec_idx >= len(sections):
    st.session_state.mock_section_idx = 0
    st.session_state.mock_section_results = []
    st.session_state.mock_exam_start_ts = None
    sec_idx = 0

section = sections[sec_idx]
section_name = section.get("name", f"Section{sec_idx+1}")
n_questions = int(section.get("n_questions", 0))
time_limit_sec = int(section.get("time_min", 0) * 60)

if n_questions <= 0:
    st.error("模擬考規則設定不完整，請檢查 MOCK_SPECS。")
    st.stop()

# ========= 載入本節題庫 =========
try:
    bank_path = CERT_CATALOG[settings["cert_type"]]["subjects"][section_name]
except Exception:
    st.error(f"找不到題庫映射：{settings['cert_type']} → {section_name}")
    st.stop()

df = load_bank_df(settings.get("cert_type", ""), merge_all=False, bank_source_path=bank_path)

if df is None or df.empty:
    st.warning("尚未載入題庫，請確認題庫檔案是否存在。")
    st.stop()

st.session_state.df = df
filtered = df
exam_label = f"{settings['cert_type']}｜模擬考"
st.session_state.current_bank_name = exam_label

# ========= 顯示規格 =========
with st.expander("本次模擬考規格", expanded=True):
    st.write(f"- 類別：{settings['cert_type']}")
    st.write(f"- 模式：{'兩節連考' if len(sections) > 1 else '單節'}")
    
    # 識別當前權重設定
    subject_id = None
    for kw, sid in SUBJECT_IDENTIFIER.get(settings["cert_type"], {}).items():
        if kw in section_name:
            subject_id = sid
            break
            
    if subject_id:
        weights = NEW_EXAM_WEIGHTS[settings["cert_type"]].get(subject_id, {})
        st.info(f"💡 本節 ({section_name}) 採用權重抽樣：\n" + ", ".join([f"{k}:{v}%" for k,v in weights.items()]))
    else:
        st.write("💡 本節採用自然分佈抽樣")

    st.write("")
    for i, s in enumerate(sections, start=1):
        st.write(f"- 第 {i} 節：{s['name']}｜{s['n_questions']} 題｜{s['time_min']} 分鐘")

st.divider()
st.subheader(f"第 {sec_idx+1} 節：{section_name}")

# ========= 控制按鈕 =========
colA, colB = st.columns([1, 1])

def _reset_whole_mock_exam():
    for k in ["paper", "answers", "started", "show_results", "saved_to_db", "start_ts", "time_limit"]:
        if k in st.session_state: del st.session_state[k]
    st.session_state.mock_section_idx = 0
    st.session_state.mock_section_results = []
    st.session_state.mock_exam_start_ts = None
    for k in ["mock_summary", "score_tuple", "wrong_df", "results_df", "section_scores", "total_score", "passed", "fail_reason"]:
        if k in st.session_state: del st.session_state[k]

with colA:
    if st.button("開始本節", type="primary"):
        # 🟢 呼叫 V2 版權重抽題
        st.session_state.paper = build_weighted_paper_v2(
            filtered,
            settings["cert_type"],
            section_name, # 傳入節次名稱以識別 Subject
            n_questions,
            shuffle_options=settings["shuffle_options"]
        )
        
        st.session_state.answers = {}
        st.session_state.started = True
        st.session_state.show_results = False
        st.session_state.saved_to_db = False
        st.session_state.start_ts = time.time()
        if st.session_state.mock_exam_start_ts is None:
            st.session_state.mock_exam_start_ts = st.session_state.start_ts
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

# ========= Timer =========
if st.session_state.get("time_limit") and st.session_state.get("start_ts"):
    elapsed = int(time.time() - st.session_state.start_ts)
    remain = max(0, st.session_state.time_limit - elapsed)
    mins, secs = divmod(remain, 60)
    st.metric("本節剩餘時間", f"{mins} 分 {secs:02d} 秒")

    if remain == 0 and not st.session_state.get("show_results"):
        st.warning("時間到，自動交卷。")
        st.session_state.show_results = True
        st.rerun()

# ========= 作答區 =========
if not st.session_state.get("show_results"):
    st.subheader("作答區")
    for idx, q in enumerate(paper, start=1):
        with st.expander(f"第 {idx} 題", expanded=(idx == 1)):
            picked = render_question(q, show_image=settings["show_image"], answer_key=f"mock_s{sec_idx}_ans_{q['ID']}")
            st.session_state.answers[q["ID"]] = picked

    if st.button("交卷（本節）", type="primary"):
        st.session_state.show_results = True
        st.rerun()

# ========= 交卷後處理 =========
if not st.session_state.get("show_results"): st.stop()

results_df, score_tuple, wrong_df = grade_paper(paper, st.session_state.answers)
correct, total, score = score_tuple

st.session_state.mock_section_results.append({
    "section": section_name,
    "score": int(score),
    "correct": int(correct),
    "total": int(total),
    "results_df": results_df,
    "wrong_df": wrong_df,
})

st.session_state.mock_section_idx += 1

if st.session_state.mock_section_idx < len(sections):
    st.success(f"已完成第 {sec_idx+1} 節：{section_name}（{score} 分）。")
    st.session_state.paper = None
    st.session_state.answers = {}
    st.session_state.started = False
    st.session_state.show_results = False
    st.session_state.saved_to_db = False
    st.session_state.start_ts = None
    st.session_state.time_limit = None
    if st.button("前往下一節", type="primary"): st.rerun()
    st.stop()

# ========= 結算 =========
section_results = st.session_state.mock_section_results
section_scores = {s["section"]: int(s["score"]) for s in section_results}
total_score = int(sum(s["score"] for s in section_results))
min_each = int(min(s["score"] for s in section_results)) if section_results else 0

passed = True
fail_reason = None
if spec.get("mode") == "single":
    pass_score = int(spec.get("pass_score", 0))
    passed = total_score >= pass_score
    if not passed: fail_reason = "分數未達及格標準"
else:
    pass_total = int(spec.get("pass_total", 0))
    pass_min_each = int(spec.get("pass_min_each", 0))
    passed = (total_score >= pass_total) and (min_each >= pass_min_each)
    if not passed:
        if total_score < pass_total: fail_reason = "總分不足"
        elif min_each < pass_min_each: fail_reason = "單科未達最低標準"

passed_db = 1 if passed else 0
all_wrong_df = pd.concat([s["wrong_df"] for s in section_results], ignore_index=True) if section_results else pd.DataFrame()
all_results_df = pd.concat([s["results_df"] for s in section_results], ignore_index=True) if section_results else pd.DataFrame()

st.session_state.mock_summary = {
    "cert_type": settings["cert_type"],
    "sections": [{"name": s["section"], "score": s["score"], "correct": s["correct"], "total": s["total"]} for s in section_results],
    "section_scores": section_scores,
    "total_score": total_score,
    "passed": passed,
    "fail_reason": fail_reason,
}
st.session_state.section_scores = section_scores
st.session_state.total_score = total_score
st.session_state.passed = passed_db
st.session_state.fail_reason = fail_reason
st.session_state.score_tuple = (int(sum(s["correct"] for s in section_results)), int(sum(s["total"] for s in section_results)), total_score)
st.session_state.wrong_df = all_wrong_df
st.session_state.results_df = all_results_df

if not st.session_state.get("saved_to_db") and st.session_state.get("mock_exam_start_ts"):
    duration_sec = int(time.time() - st.session_state.mock_exam_start_ts)
    try:
        persist_exam_record(
            user, exam_label, st.session_state.score_tuple, duration_sec, all_wrong_df,
            section_scores=section_scores, total_score=total_score, passed=passed_db, fail_reason=fail_reason
        )
        st.session_state.saved_to_db = True
    except Exception as e:
        st.error(f"寫入成績失敗：{e}")
        st.stop()

st.session_state.paper = None
st.session_state.answers = {}
st.session_state.started = False
st.session_state.show_results = False
st.session_state.start_ts = None
st.session_state.time_limit = None
st.switch_page("pages/5_模擬考_成績與錯題解析.py")