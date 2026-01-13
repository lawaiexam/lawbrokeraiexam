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
KEYWORDS_FILE = "keywords_db.json"  # 👈 核心：指定讀取靜態關鍵字檔
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

EXAM_CONFIGS = {
    "人身保險": {
        "folder": "人身",
        # 這裡的 note_file 雖然留著，但程式實際上已經改讀 JSON 了
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
        # 自動重試機制，對抗 503/429 錯誤
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
        """
        讀取本地生成的 keywords_db.json
        """
        if os.path.exists(KEYWORDS_FILE):
            try:
                with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 取得該考科的關鍵字
                    if self.exam_type in data:
                        self.chapter_keywords = data[self.exam_type]
                        # 補齊可能缺失的章節
                        for ch in self.all_chapters:
                            if ch not in self.chapter_keywords:
                                self.chapter_keywords[ch] = [ch]
                        print(f"✅ 成功載入 {self.exam_type} 關鍵字庫")
                        return
            except Exception as e:
                print(f"❌ 讀取關鍵字檔失敗: {e}")
        
        print(f"⚠️ 警告：無法讀取 JSON，使用預設章節名作為關鍵字。")
        for ch in self.all_chapters:
            self.chapter_keywords[ch] = [ch]

class SmartClassifier:
    def __init__(self, mgr, default_ch):
        self.mgr = mgr
        self.default_ch = default_ch

    def classify_batch(self, batch_data):
        results = {}
        ai_queue = []

        # 1. 關鍵字快速篩選 (本地運算，極快)
        for item in batch_data:
            full_text = f"{item['q']} {item['opts']}"
            scores = Counter()
            for ch, kws in self.mgr.chapter_keywords.items():
                for kw in kws:
                    if kw in full_text: 
                        weight = 5 if kw == ch else 1
                        scores[ch] += weight
            
            best, val = scores.most_common(1)[0] if scores else (None, 0)
            
            # 門檻值：命中 2 個關鍵字以上才算數
            if val >= 2:
                results[item['id']] = (best, "關鍵字")
            else:
                ai_queue.append(item)

        # 2. AI 批次判斷 (剩下的難題交給 AI)
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
# 對外介面函數
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

    mgr = get_cached_manager