# -*- coding: utf-8 -*-
"""
AI 智能保險題庫分類系統 (V9: 投資型保險 - 雙科目拆分版)
更新說明：
1. 輸出邏輯變更：依據考試節次，將結果拆分為兩個獨立 Excel 檔案。
   - 檔案 A: 投資型_法令規章.xlsx (第一節：第1~4章)
   - 檔案 B: 投資型_投資實務.xlsx (第二節：第5~10章)
2. 內部分頁維持：每個檔案內仍依照細項章節 (如「債券評價」) 區分 Sheet。
"""

import pandas as pd
import os
import re
import time
import pdfplumber
from tqdm import tqdm
from collections import Counter

# 🆕 新版 SDK 導入方式
from google import genai
from google.genai import types

# ==========================================
# 1. 全局設定 (Configuration)
# ==========================================

# 🔑 請在此填入您的 Google Gemini API Key
GEMINI_API_KEY = "AIzaSyCiNkDK8pfn305ZSlHmWbVj89_sXBl2eqo"  # <--- 請務必填回您的 API Key

# 檔案路徑設定
NOTE_PATH = "筆記_投資型.pdf"      
EXCEL_PATH = "原始題庫_投資型.xlsx" 

# 輸出檔名設定 (拆分為兩節)
OUTPUT_FILE_LAW = "投資型_法令規章.xlsx"
OUTPUT_FILE_PRACTICE = "投資型_投資實務.xlsx"

# 欄位設定 (投資型題庫通常是用阿拉伯數字選項)
COL_Q = "題目"
COL_OPTS = ["選項1", "選項2", "選項3", "選項4"]

# ==========================================
# 2. 定義科目與章節結構 (Subject Mapping)
# ==========================================

# 第一節：法令規章 (Chapters 1-4)
LAW_CHAPTERS = [
    "投資型保險概論",
    "投資型保險法令介紹",
    "金融體系概述",
    "證券投資信託及顧問之規範與制度"
]

# 第二節：投資實務 (Chapters 5-10)
PRACTICE_CHAPTERS = [
    "貨幣時間價值",
    "債券評價",
    "證券評價",
    "風險、報酬與投資組合",
    "資本資產訂價模式、績效",
    "投資工具簡介"
]

# 合併為總章節列表供 AI 使用
FIXED_CHAPTERS = LAW_CHAPTERS + PRACTICE_CHAPTERS

# ==========================================
# 3. Gemini Client 封裝
# ==========================================
class GeminiClient:
    def __init__(self, api_key):
        if not api_key or "YOUR_API_KEY" in api_key:
            raise ValueError("❌ 請先在程式碼中填入有效的 GEMINI_API_KEY")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash"
        
    def generate(self, prompt, temperature=0.1):
        retries = 3
        for attempt in range(retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                    )
                )
                return response.text.strip()
            except Exception as e:
                error_msg = str(e).lower()
                if "429" in error_msg or "quota" in error_msg:
                    time.sleep((attempt + 1) * 5)
                else:
                    print(f"   ⚠️ Gemini Error: {e}")
                    return ""
        return ""

# ==========================================
# 4. 筆記管理與關鍵字生成
# ==========================================
class ChapterManager:
    def __init__(self, pdf_path, ai_client):
        self.pdf_path = pdf_path
        self.ai = ai_client
        self.full_note_text = ""
        self.chapter_keywords = {} 
        
        print(f"📖 正在讀取 PDF 筆記：{pdf_path}")
        self._read_pdf_content()
        
        print(f"🧠 正在呼叫 Gemini 生成章節關鍵字 (每章 5-10 個)...")
        self._generate_keywords_deep()

    def _read_pdf_content(self):
        if not os.path.exists(self.pdf_path):
            print(f"⚠️ 警告：找不到檔案 {self.pdf_path}，將僅依賴 AI 內建知識。")
            return
        text_content = []
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text: text_content.append(text)
            self.full_note_text = "\n".join(text_content)
            print(f"   ✅ 已提取 PDF 內容，共 {len(self.full_note_text)} 字。")
        except Exception as e:
            print(f"❌ PDF 讀取失敗：{e}")

    def _get_relevant_context(self, chapter_name):
        if not self.full_note_text: return ""
        
        # 針對投資型特有名詞增加搜尋權重
        search_terms = [chapter_name]
        if "、" in chapter_name: search_terms.extend(chapter_name.split("、"))
        if "債券" in chapter_name: search_terms.append("債券")
        if "證券" in chapter_name: search_terms.append("股票")
        if "法令" in chapter_name: search_terms.append("法規")

        snippets = []
        for term in search_terms:
            if len(term) < 2: continue
            indices = [m.start() for m in re.finditer(re.escape(term), self.full_note_text)]
            for idx in indices[:2]:
                start = max(0, idx - 200)
                end = min(len(self.full_note_text), idx + 500)
                snippets.append(self.full_note_text[start:end])
        return "\n...\n".join(snippets)

    def _generate_keywords_deep(self):
        for chapter in tqdm(FIXED_CHAPTERS, desc="建立關鍵字庫"):
            context = self._get_relevant_context(chapter)
            prompt = (
                f"你是一位投資型保險與金融市場專家。請根據以下筆記內容與你的專業知識，"
                f"針對章節『{chapter}』，列出 5 到 10 個最具代表性的「專有名詞」或「關鍵字」。\n"
                f"這些關鍵字將用於將考題自動分類至此章節。\n\n"
                f"【參考筆記】：\n{context}\n\n"
                f"【要求】：\n"
                f"1. 只輸出關鍵字，用逗號分隔。\n"
                f"2. 數量控制在 5~10 個。\n"
                f"3. 不要輸出解釋或其他廢話。\n"
                f"範例：分離帳戶,資產配置,標準差,貝他係數,存續期間"
            )
            result = self.ai.generate(prompt)
            if result:
                clean_text = result.replace("、", ",").replace("，", ",").replace("\n", ",")
                keywords = [k.strip() for k in clean_text.split(",") if len(k.strip()) > 1]
                self.chapter_keywords[chapter] = keywords[:15]
            else:
                self.chapter_keywords[chapter] = [chapter]
            time.sleep(1.0) 

# ==========================================
# 5. 核心分類器
# ==========================================
class SmartClassifier:
    def __init__(self, chapter_mgr):
        self.mgr = chapter_mgr
        self.ai = chapter_mgr.ai

    def classify(self, q_text, opts_text):
        full_text = f"{q_text} {opts_text}"
        
        # Rule-Based
        scores = Counter()
        for chapter, kws in self.mgr.chapter_keywords.items():
            for kw in kws:
                if kw in full_text:
                    weight = 5 if kw == chapter else 1
                    scores[chapter] += weight
        
        if scores:
            best_chapter, best_score = scores.most_common(1)[0]
            if best_score >= 2:
                return best_chapter, "關鍵字命中"
        
        # AI-Based Fallback
        return self._ask_gemini_final(q_text, opts_text)

    def _ask_gemini_final(self, q, opts):
        chapter_list = "\n".join([f"- {c}" for c in FIXED_CHAPTERS])
        prompt = (
            f"題目：{q}\n選項：{opts}\n"
            f"請判斷這題最屬於下列哪個章節：\n{chapter_list}\n"
            "只輸出一個章節名稱，不要解釋。如果不確定，請輸出「投資型保險概論」。"
        )
        ans = self.ai.generate(prompt)
        for ch in FIXED_CHAPTERS:
            if ch in ans:
                return ch, "Gemini語意判斷"
        return "投資型保險概論", "AI歸類失敗(預設)"

# ==========================================
# 6. 主程式 (含自動拆分檔案功能)
# ==========================================
def main():
    if not os.path.exists(EXCEL_PATH):
        print(f"❌ 找不到題庫：{EXCEL_PATH}")
        return

    try:
        print("🚀 初始化 Gemini Client...")
        gemini_client = GeminiClient(GEMINI_API_KEY)
        chapter_mgr = ChapterManager(NOTE_PATH, gemini_client)
        classifier = SmartClassifier(chapter_mgr)
        
        print(f"\n📂 讀取題庫：{EXCEL_PATH}")
        all_sheets = pd.read_excel(EXCEL_PATH, sheet_name=None)
        
        all_results = []
        total_sheets = len(all_sheets)
        print(f"📊 開始處理 {total_sheets} 個分頁...")

        # 暫存備份
        TEMP_SAVE_PATH = "temp_invest_backup.xlsx"

        for sheet_name, df in all_sheets.items():
            # 檢查欄位是否存在
            if df.empty or COL_Q not in df.columns:
                continue
            
            print(f"  👉 分頁：{sheet_name} ({len(df)} 題)")
            
            batch_results = []
            for _, row in tqdm(df.iterrows(), total=len(df), leave=False):
                q_text = str(row.get(COL_Q, "")).strip()
                if not q_text or q_text.lower() == "nan":
                    continue
                
                # 動態抓取存在的選項欄位
                opts = " ".join([str(row.get(c, "")) for c in COL_OPTS if c in df.columns])
                
                ch, src = classifier.classify(q_text, opts)
                
                row_data = row.to_dict()
                row_data["AI分類章節"] = ch
                row_data["分類來源"] = src
                batch_results.append(row_data)
            
            all_results.extend(batch_results)
            
            try:
                pd.DataFrame(all_results).to_excel(TEMP_SAVE_PATH, index=False)
            except: pass
            
            time.sleep(1)

        print("\n💾 正在進行資料拆分與匯出...")
        final_df = pd.DataFrame(all_results)

        # 定義匯出函式
        def export_category_file(target_chapters, filename):
            category_df = final_df[final_df["AI分類章節"].isin(target_chapters)].copy()
            
            if category_df.empty:
                print(f"⚠️ {filename} 無資料可匯出")
                return

            # 排序
            cat_map = {name: i for i, name in enumerate(target_chapters)}
            category_df["SortKey"] = category_df["AI分類章節"].map(cat_map).fillna(999)
            category_df = category_df.sort_values("SortKey")

            print(f"  ➡ 正在寫入：{filename} (共 {len(category_df)} 題)")
            
            with pd.ExcelWriter(filename, engine="xlsxwriter") as writer:
                for ch in target_chapters:
                    sub_df = category_df[category_df["AI分類章節"] == ch]
                    if not sub_df.empty:
                        safe_name = ch.replace("/", "_")[:30]
                        sub_df.drop(columns=["SortKey"], errors='ignore').to_excel(writer, sheet_name=safe_name, index=False)
            
            print(f"  ✅ 完成：{filename}")

        # 執行兩次匯出 (法令 & 實務)
        export_category_file(LAW_CHAPTERS, OUTPUT_FILE_LAW)
        export_category_file(PRACTICE_CHAPTERS, OUTPUT_FILE_PRACTICE)

        # 處理未分類
        others_df = final_df[~final_df["AI分類章節"].isin(FIXED_CHAPTERS)]
        if not others_df.empty:
            others_df.to_excel("投資型_未分類題目.xlsx", index=False)
            print("⚠️ 發現未分類題目，已存為：投資型_未分類題目.xlsx")
        
        # 刪除暫存
        if os.path.exists(TEMP_SAVE_PATH):
            os.remove(TEMP_SAVE_PATH)

        print("\n🎉 所有分類任務執行完畢！")
        
    except Exception as e:
        print(f"\n❌ 發生錯誤：{e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()