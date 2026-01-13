import pandas as pd
import os
import time
import json
import difflib
from io import BytesIO
from collections import Counter
from google import genai
from google.genai import types
import streamlit as st
from utils import github_handler as gh

# ==========================================
# 設定區
# ==========================================
BASE_BANK_DIR = "bank"
KEYWORDS_FILE = "keywords_db.json"
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

EXAM_CONFIGS = {
    "人身保險": {
        "folder": "人身",
        "note_file": "筆記_人身.pdf",
        "col_opts": ["選項一", "選項二", "選項三", "選項四"], 
        "outputs": [
            {
                "filename": "人身_保險法規.xlsx",
                "chapters": [
                    "保險中重要的角色", "保險契約", "保險契約六大原則", "契約解除、無效、失效、停效、復效",
                    "保險金與解約金", "繼承相關", "遺產稅、贈與稅", "所得稅",
                    "保險業務員相關法規及規定", "金融消費者保護法", "個人資料保護法", "洗錢防制法"
                ]
            },
            {
                "filename": "人身_保險實務.xlsx",
                "chapters": [
                    "風險與風險管理", "人身保險歷史及生命表", "保險費架構、解約金、準備金、保單紅利",
                    "人身保險意義、功能、分類", "人身保險－人壽保險", "人身保險－年金保險",
                    "人身保險－健康保險", "人身保險－傷害保險", "人身保險－其他人身保險", "投保實務與行銷"
                ]
            }
        ],
        "default_chapter": "投保實務與行銷"
    },
    "投資型保險": {
        "folder": "投資型",
        "note_file": "筆記_投資型.pdf",
        "col_opts": ["選項1", "選項2", "選項3", "選項4"], 
        "outputs": [
            {
                "filename": "投資型_法令規章.xlsx",
                "chapters": [
                    "投資型保險概論", "投資型保險法令介紹", "金融體系概述", "證券投資信託及顧問之規範與制度"
                ]
            },
            {
                "filename": "投資型_投資實務.xlsx",
                "chapters": [
                    "貨幣時間價值", "債券評價", "證券評價", "風險、報酬與投資組合",
                    "資本資產訂價模式、績效", "投資工具簡介"
                ]
            }
        ],
        "default_chapter": "投資型保險概論"
    },
    "外幣保單": {
        "folder": "外幣",
        "note_file": "筆記_外幣.pdf",
        "col_opts": ["選項一", "選項二", "選項三", "選項四"],
        "outputs": [
            {
                "filename": "外幣.xlsx", 
                "chapters": [
                    "壽險基本概念", "保險業辦理外匯業務管理辦法", "管理外匯條例", "外匯收支或交易申報辦法",
                    "保險業辦理國外投資管理辦法", "人身保險業辦理以外幣收付之非投資型人身保險業務應具備資格條件及注意事項",
                    "投資型保險觀念", "投資型保險專設帳簿保管機構及投資標的應注意事項",
                    "銷售應注意事項", "新型態人身保險商品審查", "保險業各類監控措施"
                ]
            }
        ],
        "default_chapter": "壽險基本概念"
    }
}

COL_Q = "題目"

# ==========================================
# 工具類別 (Client & Logic)
# ==========================================

class GeminiClient:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash"
        
    def generate(self, prompt, temperature=0.1):
        for attempt in range(5):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=prompt,
                    config=types.GenerateContentConfig(temperature=temperature, response_mime_type="application/json")
                )
                return response.text.strip()
            except Exception as e:
                wait = (attempt + 1) * 5
                print(f"API Busy (Error: {e}), retrying in {wait}s...")
                time.sleep(wait)
        return ""

class ChapterManager:
    def __init__(self, exam_type, all_chapters, ai_client):
        self.exam_type = exam_type
        self.all_chapters = all_chapters
        self.ai = ai_client
        self.chapter_keywords = {} 
        self._load_static_keywords()

    def _load_static_keywords(self):
        if os.path.exists(KEYWORDS_FILE):
            try:
                with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if self.exam_type in data:
                        self.chapter_keywords = data[self.exam_type]
                        for ch in self.all_chapters:
                            if ch not in self.chapter_keywords:
                                self.chapter_keywords[ch] = [ch]
                        return
            except Exception as e:
                print(f"讀取關鍵字檔失敗: {e}")
        
        # Fallback
        for ch in self.all_chapters:
            self.chapter_keywords[ch] = [ch]

class SmartClassifier:
    def __init__(self, mgr, default_ch):
        self.mgr = mgr
        self.default_ch = default_ch

    def classify_batch(self, batch_data):
        results = {}
        ai_queue = []

        # 1. 關鍵字快速篩選
        for item in batch_data:
            full_text = f"{item['q']} {item['opts']}"
            scores = Counter()
            for ch, kws in self.mgr.chapter_keywords.items():
                for kw in kws:
                    if kw in full_text: 
                        weight = 5 if kw == ch else 1
                        scores[ch] += weight
            
            best, val = scores.most_common(1)[0] if scores else (None, 0)
            
            if val >= 2:
                results[item['id']] = (best, "關鍵字")
            else:
                ai_queue.append(item)

        # 2. AI 批次判斷
        if ai_queue:
            prompt_items = []
            for item in ai_queue:
                prompt_items.append(f"ID {item['id']}:\n題目: {item['q']}\n選項: {item['opts']}")
            
            prompt_str = "\n\n".join(prompt_items)
            prompt = (
                f"請將下列題目分類到最合適的章節。可選章節：\n{self.mgr.all_chapters}\n\n"
                f"{prompt_str}\n\n"
                f"請直接回傳 JSON 格式：\n"
                f"[{{ \"id\": \"ID字串\", \"chapter\": \"章節名稱\" }}, ...]"
            )
            
            try:
                res_text = self.mgr.ai.generate(prompt)
                res_text = res_text.replace("```json", "").replace("```", "")
                ai_results = json.loads(res_text)
                
                for res in ai_results:
                    res_id = res.get('id')
                    raw_ch = res.get('chapter', self.default_ch)
                    matches = difflib.get_close_matches(raw_ch, self.mgr.all_chapters, n=1, cutoff=0.4)
                    final_ch = matches[0] if matches else self.default_ch
                    results[res_id] = (final_ch, "AI判斷")
            except Exception as e:
                print(f"Batch AI Failed: {e}")
                for item in ai_queue:
                    results[item['id']] = (self.default_ch, "預設(API失敗)")

        return results

# ==========================================
# 對外介面函數 (Process & Save)
# ==========================================

@st.cache_resource(show_spinner=False)
def get_cached_manager(exam_type, all_chapters_tuple):
    client = GeminiClient(GEMINI_API_KEY)
    return ChapterManager(exam_type, list(all_chapters_tuple), client)

def process_uploaded_file(exam_type, uploaded_file):
    config = EXAM_CONFIGS.get(exam_type)
    if not config: return None

    all_chapters = []
    for output_conf in config['outputs']:
        all_chapters.extend(output_conf['chapters'])

    mgr = get_cached_manager(exam_type, tuple(all_chapters))
    classifier = SmartClassifier(mgr, config['default_chapter'])

    try:
        dfs = pd.read_excel(uploaded_file, sheet_name=None)
    except Exception as e:
        st.error(f"Excel 讀取失敗: {e}")
        return None

    final_results = []
    progress_bar = st.progress(0, text="準備開始分類...")
    
    total_rows = sum(len(df) for df in dfs.values() if not df.empty and COL_Q in df.columns)
    processed_count = 0
    BATCH_SIZE = 10 

    for name, df in dfs.items():
        if df.empty or COL_Q not in df.columns: continue
        
        valid_opts = [c for c in config['col_opts'] if c in df.columns]
        
        batch_buffer = [] 
        rows_map = {}
        
        for idx, row in df.iterrows():
            q = str(row.get(COL_Q, "")).strip()
            if not q or q.lower() == "nan": continue
            
            opts_txt = " ".join([str(row.get(c, "")) for c in valid_opts])
            
            unique_id = f"{name}_{idx}"
            item = {'id': unique_id, 'q': q, 'opts': opts_txt}
            
            batch_buffer.append(item)
            rows_map[unique_id] = row.to_dict()
            
            if len(batch_buffer) >= BATCH_SIZE or idx == len(df) - 1:
                batch_results = classifier.classify_batch(batch_buffer)
                for item in batch_buffer:
                    res = batch_results.get(item['id'], (config['default_chapter'], "預設"))
                    r = rows_map[item['id']]
                    r["AI分類章節"] = res[0]
                    r["分類來源"] = res[1]
                    final_results.append(r)
                
                processed_count += len(batch_buffer)
                progress = min(processed_count / total_rows, 1.0)
                progress_bar.progress(progress, text=f"🔥 高速分類中：{processed_count}/{total_rows} 題")
                
                batch_buffer = []
                time.sleep(2)

    progress_bar.empty()
    return pd.DataFrame(final_results)

# 👇 【核心修正】：加入上傳狀態檢查與錯誤攔截
def save_merged_results(exam_type, new_classified_df):
    config = EXAM_CONFIGS.get(exam_type)
    base_gh_path = f"{BASE_BANK_DIR}/{config['folder']}"
    logs = []

    for out_conf in config['outputs']:
        filename = out_conf['filename']
        target_chs = out_conf['chapters']
        target_gh_path = f"{base_gh_path}/{filename}"

        sub_new = new_classified_df[new_classified_df["AI分類章節"].isin(target_chs)].copy()
        if sub_new.empty: continue

        existing_df = pd.DataFrame()
        old_file_bytes = gh.gh_download_bytes(target_gh_path)
        if old_file_bytes:
            try:
                xls = pd.read_excel(BytesIO(old_file_bytes), sheet_name=None)
                for sname, sdf in xls.items():
                    if "AI分類章節" not in sdf.columns: sdf["AI分類章節"] = sname
                    existing_df = pd.concat([existing_df, sdf], ignore_index=True)
            except: pass

        if not existing_df.empty:
            common = list(set(existing_df.columns) & set(sub_new.columns))
            if COL_Q in common:
                combined = pd.concat([existing_df, sub_new], ignore_index=True)
            else:
                combined = sub_new
        else:
            combined = sub_new
        
        combined.drop_duplicates(subset=[COL_Q], keep='last', inplace=True)
        after = len(combined)
        
        mapper = {name: i for i, name in enumerate(target_chs)}
        combined["Sort"] = combined["AI分類章節"].map(mapper).fillna(999)
        combined = combined.sort_values("Sort")

        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            for ch in target_chs:
                ch_df = combined[combined["AI分類章節"] == ch]
                if not ch_df.empty:
                    safe = ch.replace("/", "_")[:30]
                    ch_df.drop(columns=["Sort"], errors="ignore").to_excel(writer, sheet_name=safe, index=False)
        
        # 👇 這裡改了：嘗試上傳，並根據結果寫 log
        try:
            result = gh.gh_put_file(target_gh_path, output.getvalue(), f"Auto-Merge: {filename}")
            
            # 如果上傳成功 (result 不是 False)
            if result is not False:
                logs.append(f"✅ **{filename}**：成功上傳！更新後共 {after} 題。")
            else:
                logs.append(f"❌ **{filename}**：上傳失敗 (GitHub Token 權限不足或無效)。")
        except Exception as e:
            logs.append(f"❌ **{filename}**：上傳發生嚴重錯誤！原因：{str(e)}")

    return logs