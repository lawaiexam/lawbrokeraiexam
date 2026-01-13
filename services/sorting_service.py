import pandas as pd
import os
import re
import time
import json
import difflib
import pdfplumber
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
        # 增加重試次數與等待時間，避免 API 429 錯誤
        for attempt in range(5):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=prompt,
                    config=types.GenerateContentConfig(temperature=temperature, response_mime_type="application/json")
                )
                return response.text.strip()
            except Exception as e:
                wait = (attempt + 1) * 5
                print(f"API Busy, retrying in {wait}s... Error: {e}")
                time.sleep(wait)
        return ""

class ChapterManager:
    def __init__(self, folder_name, pdf_filename, all_chapters, ai_client):
        self.pdf_path = f"{BASE_BANK_DIR}/{folder_name}/{pdf_filename}"
        self.all_chapters = all_chapters
        self.ai = ai_client
        self.full_note_text = ""
        self.chapter_keywords = {} 
        self._read_pdf_from_github()
        self._gen_keywords()

    def _read_pdf_from_github(self):
        data = gh.gh_download_bytes(self.pdf_path)
        if not data: return
        try:
            with pdfplumber.open(BytesIO(data)) as pdf:
                content = [p.extract_text() for p in pdf.pages if p.extract_text()]
                self.full_note_text = "\n".join(content)
        except: pass

    def _get_context(self, chapter):
        # 簡化版 Context 抓取，只抓最相關的一小段以節省 Token
        if not self.full_note_text: return ""
        idx = self.full_note_text.find(chapter)
        if idx != -1:
            return self.full_note_text[idx:idx+800]
        return ""

    def _gen_keywords(self):
        if not self.full_note_text:
            for ch in self.all_chapters: self.chapter_keywords[ch] = [ch]
            return

        progress_text = "AI 正在閱讀筆記建立索引 (只需執行一次)..."
        my_bar = st.progress(0, text=progress_text)
        
        # 批次處理關鍵字生成，不要一章一章問
        prompt = (
            f"你是保險考題分類專家。請閱讀筆記後，針對下列章節，各列出 5 個最關鍵的專有名詞。\n"
            f"章節列表：{self.all_chapters}\n"
            f"筆記內容摘要：{self.full_note_text[:5000]}...\n\n"
            f"請回傳 JSON 格式：{{ \"章節名\": [\"關鍵字1\", \"關鍵字2\"...] }}"
        )
        try:
            res = self.ai.generate(prompt)
            data = json.loads(res)
            # 確保所有章節都有 key
            for ch in self.all_chapters:
                self.chapter_keywords[ch] = data.get(ch, [ch])
        except:
            # 失敗回退機制
            for ch in self.all_chapters: self.chapter_keywords[ch] = [ch]
            
        my_bar.progress(1.0, text="索引建立完成！")
        time.sleep(1)
        my_bar.empty()

class SmartClassifier:
    def __init__(self, mgr, default_ch):
        self.mgr = mgr
        self.default_ch = default_ch
        self.chapters_str = "\n".join([f"- {c}" for c in mgr.all_chapters])

    def classify_batch(self, batch_data):
        """
        批次分類核心邏輯
        batch_data: list of dict [{'id': 0, 'q': '...', 'opts': '...'}, ...]
        """
        results = {}
        ai_queue = []

        # 1. 先用關鍵字快速篩選 (本地運算，極快)
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

        # 2. 剩下的打包問 AI (減少 API 呼叫次數)
        if ai_queue:
            # 限制一次問 10 題，避免 Token 爆掉
            prompt_items = []
            for item in ai_queue:
                prompt_items.append(f"ID {item['id']}:\n題目: {item['q']}\n選項: {item['opts']}")
            
            prompt_str = "\n\n".join(prompt_items)
            prompt = (
                f"請將下列題目分類到最合適的章節。可選章節：\n{self.mgr.all_chapters}\n\n"
                f"{prompt_str}\n\n"
                f"請直接回傳 JSON 格式，不要有Markdown標記：\n"
                f"[{{ \"id\": 題號, \"chapter\": \"章節名稱\" }}, ...]"
            )
            
            try:
                # 呼叫 AI
                res_text = self.mgr.ai.generate(prompt)
                # 清理可能的回傳雜訊
                res_text = res_text.replace("```json", "").replace("```", "")
                ai_results = json.loads(res_text)
                
                # 解析回傳
                for res in ai_results:
                    res_id = res.get('id')
                    raw_ch = res.get('chapter', self.default_ch)
                    
                    # 模糊比對章節名稱 (防止 AI 寫錯字)
                    matches = difflib.get_close_matches(raw_ch, self.mgr.all_chapters, n=1, cutoff=0.4)
                    final_ch = matches[0] if matches else self.default_ch
                    
                    results[res_id] = (final_ch, "AI判斷")
                    
            except Exception as e:
                print(f"Batch AI Failed: {e}")
                # 失敗時全部歸為預設
                for item in ai_queue:
                    results[item['id']] = (self.default_ch, "預設(API失敗)")

        return results

# ==========================================
# 對外介面函數
# ==========================================

@st.cache_resource(show_spinner=False)
def get_cached_manager(folder_name, note_filename, all_chapters_tuple):
    client = GeminiClient(GEMINI_API_KEY)
    return ChapterManager(folder_name, note_filename, list(all_chapters_tuple), client)

def process_uploaded_file(exam_type, uploaded_file):
    config = EXAM_CONFIGS.get(exam_type)
    if not config: return None

    all_chapters = []
    for output_conf in config['outputs']:
        all_chapters.extend(output_conf['chapters'])

    mgr = get_cached_manager(config['folder'], config['note_file'], tuple(all_chapters))
    classifier = SmartClassifier(mgr, config['default_chapter'])

    try:
        dfs = pd.read_excel(uploaded_file, sheet_name=None)
    except Exception as e:
        st.error(f"Excel 讀取失敗: {e}")
        return None

    final_results = []
    progress_bar = st.progress(0, text="準備開始分類...")
    
    # 預先計算總題數以顯示進度
    total_rows = sum(len(df) for df in dfs.values() if not df.empty and COL_Q in df.columns)
    processed_count = 0
    
    BATCH_SIZE = 10  # 每 10 題問一次 AI

    for name, df in dfs.items():
        if df.empty or COL_Q not in df.columns: continue
        
        valid_opts = [c for c in config['col_opts'] if c in df.columns]
        
        # 準備批次資料容器
        batch_buffer = [] 
        rows_map = {} # 用 id 對應 row 資料
        
        for idx, row in df.iterrows():
            q = str(row.get(COL_Q, "")).strip()
            if not q or q.lower() == "nan": continue
            
            opts_txt = " ".join([str(row.get(c, "")) for c in valid_opts])
            
            # 給每個題目一個唯一 ID (Sheet名_Index)
            unique_id = f"{name}_{idx}"
            item = {'id': unique_id, 'q': q, 'opts': opts_txt}
            
            batch_buffer.append(item)
            rows_map[unique_id] = row.to_dict()
            
            # 當 Buffer 滿了，或是最後一題，就執行批次分類
            if len(batch_buffer) >= BATCH_SIZE or idx == len(df) - 1:
                # 執行分類！
                batch_results = classifier.classify_batch(batch_buffer)
                
                # 將結果寫回 row
                for item in batch_buffer:
                    res = batch_results.get(item['id'], (config['default_chapter'], "預設"))
                    r = rows_map[item['id']]
                    r["AI分類章節"] = res[0]
                    r["分類來源"] = res[1]
                    final_results.append(r)
                
                # 更新進度條
                processed_count += len(batch_buffer)
                progress = min(processed_count / total_rows, 1.0)
                progress_bar.progress(progress, text=f"🔥 高速分類中：{processed_count}/{total_rows} 題")
                
                # 清空 Buffer
                batch_buffer = []
                
                # 微小休息，避免太過頻繁
                time.sleep(2) # 批次模式下，這裡休息 2 秒非常安全

    progress_bar.empty()
    return pd.DataFrame(final_results)

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
        
        before = len(combined)
        combined.drop_duplicates(subset=[COL_Q], keep='last', inplace=True)
        after = len(combined)
        
        logs.append(f"📄 **{filename}**：新增 {len(sub_new)} 題，合併後共 {after} 題 (已去重)。")

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
        
        gh.gh_put_file(target_gh_path, output.getvalue(), f"Auto-Merge: {filename}")

    return logs