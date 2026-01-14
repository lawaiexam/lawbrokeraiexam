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
# 🟢 設定區：權重與章節映射
# ==========================================
NEW_EXAM_WEIGHTS = {
    "人身保險業務員資格測驗": {
        "life_regulation": {"insurance_law_core": 40,"solicitation_rules": 40,"liability_penalties": 20},
        "life_practice": {"insurance_principles": 30,"life_products": 50,"sales_practice_ethics": 20}
    },
    "外幣收付非投資型保險商品測驗": {
        "fx_exam": {"fx_basics": 28,"fx_products": 28,"fx_regulation_compliance": 22,"fx_risk_disclosure_practice": 22}
    },
    "投資型保險商品業務員測驗": {
        "il_regulations": {"sales_regulations": 50,"suitability_rules": 30,"dispute_liability": 20},
        "il_investment_practice": {"investment_basics": 45,"il_product_mechanics": 45,"customer_suitability_practice": 10}
    }
}

SUBJECT_IDENTIFIER = {
    "人身保險業務員資格測驗": {"法規": "life_regulation", "實務": "life_practice"},
    "外幣收付非投資型保險商品測驗": {"外幣": "fx_exam", "非投資": "fx_exam"},
    "投資型保險商品業務員測驗": {"法令": "il_regulations", "規章": "il_regulations", "第一節": "il_regulations", "實務": "il_investment_practice", "第二節": "il_investment_practice"}
}

CHAPTER_MAPPING = {
    "保險法規": {
        "保險契約": "insurance_law_core","保險契約六大原則": "insurance_law_core","契約解除、無效、失效、停效、復效": "insurance_law_core",
        "保險金與解約金": "insurance_law_core","遺產稅、贈與稅": "insurance_law_core","所得稅": "insurance_law_core",
        "金融消費者保護法": "insurance_law_core","個人資料保護法": "insurance_law_core","洗錢防制法": "liability_penalties", 
        "保險業務員相關法規及規定": "solicitation_rules"
    },
    "保險實務": {
        "風險與風險管理": "insurance_principles","人身保險歷史及生命表": "insurance_principles","保險費架構、解約金、準備金、保單紅利": "insurance_principles",
        "保險中重要的角色": "insurance_principles","人身保險意義、功能、分類": "life_products","人身保險－人壽保險": "life_products",
        "人身保險－年金保險": "life_products","人身保險－健康保險": "life_products","人身保險－傷害保險": "life_products",
        "人身保險－其他人身保險": "life_products","投保實務與行銷": "sales_practice_ethics","繼承相關": "sales_practice_ethics"
    },
    "外幣非投資型": {
        "壽險基本概念": "fx_basics","人身保險業辦理以外幣收付之非投資型人身保險業務應具備資格條件及注意事項": "fx_products",
        "保險業辦理外匯業務管理辦法": "fx_regulation_compliance","管理外匯條例": "fx_regulation_compliance","外匯收支或交易申報辦法": "fx_regulation_compliance",
        "保險業辦理國外投資管理辦法": "fx_regulation_compliance","保險業各類監控措施": "fx_regulation_compliance","銷售應注意事項": "fx_risk_disclosure_practice",
        "新型態人身保險商品審查": "fx_risk_disclosure_practice","投資型保險專設帳簿保管機構及投資標的應注意事項": "fx_risk_disclosure_practice","投資型保險觀念": "fx_products"
    },
    "投資型法規": {
        "投資型保險法令介紹": "sales_regulations","證券投資信託及顧問之規範與制度": "sales_regulations","銷售應注意事項": "sales_regulations",
        "適合度": "suitability_rules","爭議處理": "dispute_liability"
    },
    "投資型實務": {
        "貨幣時間價值": "investment_basics","債券評價": "investment_basics","證券評價": "investment_basics","風險、報酬與投資組合": "investment_basics",
        "資本資產訂價模式、績效": "investment_basics","投資工具簡介": "investment_basics","金融體系概述": "investment_basics",
        "投資型保險概論": "il_product_mechanics","投資型保險觀念": "il_product_mechanics","投資型保險專設帳簿保管機構及投資標的應注意事項": "il_product_mechanics",
        "客戶適合度": "customer_suitability_practice"
    }
}

# ==========================================
# 🟢 核心函式
# ==========================================
def build_weighted_paper_v2(full_df, cert_type, section_name, total_questions, shuffle_options=False):
    target_col = "AI分類章節"
    if full_df.empty or target_col not in full_df.columns:
        return full_df.sample(n=min(len(full_df), total_questions)).to_dict('records')

    subject_id = None
    cert_identifiers = SUBJECT_IDENTIFIER.get(cert_type, {})
    for keyword, sid in cert_identifiers.items():
        if keyword in section_name:
            subject_id = sid
            break
            
    if not subject_id:
        return _build_paper_by_natural_distribution(full_df, total_questions)

    cert_weights = NEW_EXAM_WEIGHTS.get(cert_type, {})
    chapter_weights = cert_weights.get(subject_id, {})
    if not chapter_weights:
        return _build_paper_by_natural_distribution(full_df, total_questions)

    mapping_key_map = {
        "life_regulation": "保險法規", "life_practice": "保險實務",
        "fx_exam": "外幣非投資型",
        "il_regulations": "投資型法規", "il_investment_practice": "投資型實務"
    }
    mapping_category = mapping_key_map.get(subject_id)
    current_mapping = CHAPTER_MAPPING.get(mapping_category, {})

    df_temp = full_df.copy()
    df_temp["JsonChapterID"] = df_temp[target_col].map(current_mapping).fillna("others")

    exam_pool = []
    for ch_id, weight_pct in chapter_weights.items():
        target_count = int(round(total_questions * (weight_pct / 100)))
        chapter_pool = df_temp[df_temp["JsonChapterID"] == ch_id]
        take_n = min(len(chapter_pool), target_count)
        if take_n > 0:
            exam_pool.append(chapter_pool.sample(n=take_n))

    current_selected = pd.concat(exam_pool) if exam_pool else pd.DataFrame()
    needed = total_questions - len(current_selected)
    
    if needed > 0:
        others_pool = df_temp[~df_temp.index.isin(current_selected.index)]
        if not others_pool.empty:
            extra = others_pool.sample(n=min(len(others_pool), needed))
            exam_pool.append(extra)
            
    if exam_pool:
        final_df = pd.concat(exam_pool)
    else:
        final_df = pd.DataFrame()

    if len(final_df) > total_questions:
        final_df = final_df.sample(n=total_questions)

    final_df = final_df.sample(frac=1).reset_index(drop=True)
    return final_df.to_dict('records')

def _build_paper_by_natural_distribution(full_df, total_questions):
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

if "mock_section_idx" not in st.session_state: st.session_state.mock_section_idx = 0
if "mock_section_results" not in st.session_state: st.session_state.mock_section_results = []
if "mock_exam_start_ts" not in st.session_state: st.session_state.mock_exam_start_ts = None

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

try:
    bank_path = CERT_CATALOG[settings["cert_type"]]["subjects"][section_name]
except Exception:
    st.error(f"找不到題庫映射：{settings['cert_type']} → {section_name}")
    st.stop()

df = load_bank_df(settings.get("cert_type", ""), merge_all=False, bank_source_path=bank_path)

if df is None or df.empty:
    st.warning("尚未載入題庫，請確認題庫檔案是否存在。")
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

    # 定義映射: 支援中文(人身)與數字(投資型)
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

            # 洗掉星號
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

except Exception as e:
    st.error(f"資料格式轉換失敗：{e}")
    st.stop()
# ==========================================
# 🚑 補丁結束
# ==========================================

st.session_state.df = df
filtered = df
exam_label = f"{settings['cert_type']}｜模擬考"
st.session_state.current_bank_name = exam_label

with st.expander("本次模擬考規格", expanded=True):
    st.write(f"- 類別：{settings['cert_type']}")
    st.write(f"- 模式：{'兩節連考' if len(sections) > 1 else '單節'}")
    
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
        st.session_state.paper = build_weighted_paper_v2(
            filtered,
            settings["cert_type"],
            section_name,
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

if st.session_state.get("time_limit") and st.session_state.get("start_ts"):
    elapsed = int(time.time() - st.session_state.start_ts)
    remain = max(0, st.session_state.time_limit - elapsed)
    mins, secs = divmod(remain, 60)
    st.metric("本節剩餘時間", f"{mins} 分 {secs:02d} 秒")

    if remain == 0 and not st.session_state.get("show_results"):
        st.warning("時間到，自動交卷。")
        st.session_state.show_results = True
        st.rerun()

if not st.session_state.get("show_results"):
    st.subheader("作答區")
    for idx, q in enumerate(paper, start=1):
        with st.expander(f"第 {idx} 題", expanded=(idx == 1)):
            picked = render_question(q, show_image=settings["show_image"], answer_key=f"mock_s{sec_idx}_ans_{q['ID']}")
            st.session_state.answers[q["ID"]] = picked

    if st.button("交卷（本節）", type="primary"):
        st.session_state.show_results = True
        st.rerun()

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
