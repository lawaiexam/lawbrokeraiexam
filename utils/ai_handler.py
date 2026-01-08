import hashlib
import google.generativeai as genai
import streamlit as st
import pandas as pd

def gemini_ready():
    return bool(st.secrets.get("GEMINI_API_KEY"))

def _gemini_model():
    return st.secrets.get("GEMINI_MODEL", "gemini-1.5-flash")

def _gemini_client():
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    return genai.GenerativeModel(_gemini_model())

@st.cache_data(show_spinner=False)
def gemini_generate_cached(cache_key: str, system_msg: str, user_msg: str) -> str:
    """以 cache_key 做為快取 key（交由 Streamlit 管理），避免重複呼叫"""
    try:
        model = _gemini_client()
        prompt = f"[系統指示]\n{system_msg}\n\n[使用者需求]\n{user_msg}".strip()
        resp = model.generate_content(prompt)
        return (resp.text or "").strip()
    except Exception as e:
        return f"AI 回應生成失敗: {str(e)}"

def make_hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

# -----------------------------
# AI 提示/詳解/總結 Prompt Builders
# -----------------------------
def build_hint_prompt(q: dict):
    sys = (
        "你是考試助教，只能提供方向提示，嚴禁輸出答案代號或逐字答案。"
        "優先參考題庫的解答說明；不足再補充概念或排除法。"
    )
    expl = (q.get("Explanation") or "").strip()
    user = f"""
題目: {q['Question']}
選項:
{chr(10).join([f"{lab}. {txt}" for lab,txt in q['Choices']])}
題庫解答說明（僅供參考、不可爆雷）：{expl if expl else "（無）"}
請用 1-2 句提示重點，不要爆雷。
"""
    ck = make_hash("HINT|" + q["Question"] + "|" + expl)
    return ck, sys, user

def build_explain_prompt(q: dict):
    sys = "你是解題老師，優先引用題庫解答說明，逐項說明正確與錯誤，保持精簡。"
    expl = (q.get("Explanation") or "").strip()
    ans_letters = "".join(sorted(list(q.get("Answer", set()))))
    user = f"""
題目: {q['Question']}
選項:
{chr(10).join([f"{lab}. {txt}" for lab,txt in q['Choices']])}
正解: {ans_letters or "（無）"}
題庫解答說明：{expl if expl else "（無）"}
"""
    ck = make_hash("EXPL|" + q["Question"] + "|" + ans_letters)
    return ck, sys, user

def build_summary_prompt(result_df: pd.DataFrame):
    sys = "你是考後診斷教練，請分析弱點與建議。"
    mini = result_df[["ID","Tag","Question","Your Answer","Correct","Result"]].head(200)
    user = f"""
以下是作答結果（最多 200 題）：
{mini.to_csv(index=False)}
請輸出：整體表現、弱項主題、3-5點練習建議（條列）。
"""
    ck = make_hash("SUMM|" + mini.to_csv(index=False))
    return ck, sys, user

def build_weak_wrong_prompt(result_df_wrong: pd.DataFrame):
    sys = "你是考後復盤教練，聚焦錯題的主題與知識點，指出易錯原因與改進建議。"
    mini = result_df_wrong[["ID","Tag","Question","Your Answer","Correct"]].head(200)
    user = f"""
以下為本次錯題（最多 200 題）：
{mini.to_csv(index=False)}
請輸出：1) 錯題主題聚類 2) 容易混淆/易錯點 3) 必背觀念 4) 接下來復習建議（條列）。
"""
    ck = make_hash("WRONG|" + mini.to_csv(index=False))
    return ck, sys, user