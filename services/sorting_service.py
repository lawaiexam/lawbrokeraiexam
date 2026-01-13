import pandas as pd
import os
import re
import time
import difflib  # 用於模糊比對
from io import BytesIO
from collections import Counter
from google import genai
from google.genai import types
import streamlit as st
from utils import github_handler as gh  # 引入 GitHub 工具

# ==========================================
# 設定區
# ==========================================

# 筆記路徑：假設筆記放在 bank/{folder}/ 下
BASE_BANK_DIR = "bank"

# API Key
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "AIzaSyCiNkDK8pfn305ZSlHmWbVj89_sXBl2eqo")

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
        for attempt in range(3):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name, contents=prompt,
                    config=types.GenerateContentConfig(temperature=temperature)
                )
                return response.text.strip()
            except Exception:
                time.sleep((attempt + 1) * 2)
        return ""

import pdfplumber

class ChapterManager:
    def __init__(self, folder_name, pdf_filename, all_chapters, ai_client):
        # 雲端版：嘗試從 GitHub 下載筆記內容
        self.pdf_path = f"{BASE_BANK_DIR}/{folder_name}/{pdf_filename}"
        self.all_chapters = all_chapters
        self.ai = ai_client
        self.full_note_text = ""
        self.chapter_keywords = {} 
        self._read_pdf_from_github()
        self._gen_keywords()

    def _read_pdf_from_github(self):
        # 使用 gh_download_bytes 讀取筆記
        data = gh.gh_download_bytes(self.pdf_path)
        if not data:
            return
        
        try:
            with pdfplumber.open(BytesIO(data)) as pdf:
                content = []
                for page in pdf.pages:
                    txt = page.extract_text()
                    if txt: content.append(txt)
                self.full_note_text = "\n".join(content)
        except Exception:
            pass

    def _get_context(self, chapter):
        if not self.full_note_text: return ""
        terms = re.split(r'[、\s\-\(\)辦法注意事項]', chapter)
        terms = [t for t in terms if len(t) >= 2]
        terms.append(chapter) 
        snippets = []
        for t in terms:
            indices = [m.start() for m in re.finditer(re.escape(t), self.full_note_text)]
            for idx in indices[:2]:
                snippets.append(self.full_note_text[max(0, idx-200):min(len(self.full_note_text), idx+500)])
        return "\n...\n".join(snippets)

    def _gen_keywords(self):
        if not self.full_note_text:
            for ch in self.all_chapters:
                self.chapter_keywords[ch] = [ch]
            return

        progress_text = "正在分析筆記與建立關鍵字..."
        my_bar = st.progress(0, text=progress_text)
        
        total = len(self.all_chapters)
        for i, ch in enumerate(self.all_chapters):
            ctx = self._get_context(ch)
            prompt = (
                f"你是保險考題分類專家。請針對章節『{ch}』，列出 5-10 個核心「專有名詞」或「關鍵字」。\n"
                f"參考筆記：\n{ctx}\n只輸出關鍵字，用逗號分隔。"
            )
            res = self.ai.generate(prompt)
            if res:
                kws = [k.strip() for k in res.replace("、", ",").replace("\n", ",").split(",") if len(k.strip())>1]
                self.chapter_keywords[ch] = kws[:15]
            else:
                self.chapter_keywords[ch] = [ch]
            
            my_bar.progress((i + 1) / total, text=f"分析章節：{ch}")
            time.sleep(0.2)
        
        my_bar.empty()

class SmartClassifier:
    def __init__(self, mgr, default_ch):
        self.mgr = mgr
        self.default_ch = default_ch
        # 建立一個乾淨的章節清單字串，讓 AI 好讀
        self.chapters_str = "\n".join([f"- {c}" for c in mgr.all_chapters])

    def classify(self, q, opts):
        full_text = f"{q} {opts}"
        
        # 1. 關鍵字規則比對 (Rule-Based) - 先搶快
        scores = Counter()
        for ch, kws in self.mgr.chapter_keywords.items():
            for kw in kws:
                if kw in full_text: 
                    # 若關鍵字跟章節名完全一樣，權重加重
                    weight = 5 if kw == ch else 1
                    scores[ch] += weight
        
        if scores:
            best_chapter, score = scores.most_common(1)[0]
            # 門檻值：至少要有 2 分才算數
            if score >= 2: 
                return best_chapter, "關鍵字"

        # 2. AI 語意判斷 (AI-Based) - 處理難題
        prompt = (
            f"你是一個保險考題分類員。請根據題目與選項，從下方『標準章節清單』中，選出最相關的一個章節。\n"
            f"題目：{q}\n"
            f"選項：{opts}\n\n"
            f"【標準章節清單】：\n{self.chapters_str}\n\n"
            f"注意：你只能輸出清單中的名稱，不要輸出任何其他文字或解釋。"
        )
        
        ai_response = self.mgr.ai.generate(prompt)
        ai_response = ai_response.strip().replace("\n", "").replace(" ", "") # 清理 AI 回答

        # 3. 模糊比對 (Fuzzy Match) - 解決 "AI 多嘴" 的問題
        # 方法 A: 直接包含檢查
        for ch in self.mgr.all_chapters:
            if ch in ai_response: 
                return ch, "AI判斷"
        
        # 方法 B: 相似度比對 (Similarity) - 針對 AI 寫錯字或多字的狀況
        # 找出與 AI 回答最像的章節
        matches = difflib.get_close_matches(ai_response, self.mgr.all_chapters, n=1, cutoff=0.4)
        if matches:
            return matches[0], "AI(模糊)"

        # 4. 真的沒救了，回傳預設值
        return self.default_ch, "預設"

# ==========================================
# 對外介面函數
# ==========================================

# 👇【快取核心】這個函式負責建立並「記住」Manager，避免每次重跑
@st.cache_resource(show_spinner=False)
def get_cached_manager(folder_name, note_filename, all_chapters_tuple):
    # 這裡必須把 list 轉成 tuple 才能被 cache，裡面再轉回 list
    client = GeminiClient(GEMINI_API_KEY)
    return ChapterManager(folder_name, note_filename, list(all_chapters_tuple), client)

def process_uploaded_file(exam_type, uploaded_file):
    config = EXAM_CONFIGS.get(exam_type)
    if not config: return None

    all_chapters = []
    for output_conf in config['outputs']:
        all_chapters.extend(output_conf['chapters'])

    # 👇【修改】使用快取機制取得 Manager
    # 注意：我們把 all_chapters (list) 轉成 tuple 傳進去，因為 list 不能被 Streamlit cache hash
    mgr = get_cached_manager(config['folder'], config['note_file'], tuple(all_chapters))
    
    classifier = SmartClassifier(mgr, config['default_chapter'])

    try:
        dfs = pd.read_excel(uploaded_file, sheet_name=None)
    except Exception as e:
        st.error(f"Excel 讀取失敗: {e}")
        return None

    results = []
    curr_sheet = 0
    progress_bar = st.progress(0, text="開始分類題目...")

    for name, df in dfs.items():
        curr_sheet += 1
        if df.empty or COL_Q not in df.columns: 
            continue
        
        valid_opts = [c for c in config['col_opts'] if c in df.columns]
        total_rows = len(df)
        
        for idx, row in df.iterrows():
            q = str(row.get(COL_Q, "")).strip()
            if not q or q.lower() == "nan": continue
            
            opts_txt = " ".join([str(row.get(c, "")) for c in valid_opts])
            ch, src = classifier.classify(q, opts_txt)
            
            r = row.to_dict()
            r["AI分類章節"] = ch
            r["分類來源"] = src
            results.append(r)
            
            # 每 5 題更新一次進度，避免 UI 卡頓
            if idx % 5 == 0:
                progress = (idx + 1) / total_rows
                progress_bar.progress(progress, text=f"正在處理分頁 '{name}'：第 {idx+1}/{total_rows} 題")

    progress_bar.empty()
    return pd.DataFrame(results)

def save_merged_results(exam_type, new_classified_df):
    """
    將分類好的 DF 合併回 GitHub 上的題庫
    """
    config = EXAM_CONFIGS.get(exam_type)
    # GitHub 上的資料夾路徑 (例如 bank/人身)
    base_gh_path = f"{BASE_BANK_DIR}/{config['folder']}"
    
    logs = []

    for out_conf in config['outputs']:
        filename = out_conf['filename']
        target_chs = out_conf['chapters']
        # GitHub 完整檔案路徑
        target_gh_path = f"{base_gh_path}/{filename}"

        # 篩選新題目
        sub_new = new_classified_df[new_classified_df["AI分類章節"].isin(target_chs)].copy()
        if sub_new.empty:
            continue

        # 1. 嘗試從 GitHub 下載舊檔
        existing_df = pd.DataFrame()
        old_file_bytes = gh.gh_download_bytes(target_gh_path)
        
        if old_file_bytes:
            try:
                xls = pd.read_excel(BytesIO(old_file_bytes), sheet_name=None)
                for sname, sdf in xls.items():
                    if "AI分類章節" not in sdf.columns:
                        sdf["AI分類章節"] = sname
                    existing_df = pd.concat([existing_df, sdf], ignore_index=True)
            except Exception:
                pass

        # 2. 合併與去重
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
        removed = before - after
        
        logs.append(f"📄 **{filename}**：新增 {len(sub_new)} 題，合併後共 {after} 題 (已自動移除 {removed} 題重複)。")

        # 3. 轉存為 Excel Bytes
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
        
        # 4. 上傳回 GitHub (覆蓋舊檔)
        file_bytes = output.getvalue()
        gh.gh_put_file(
            target_gh_path, 
            file_bytes, 
            f"Auto-Merge: Updated {filename} via Admin Panel"
        )

    return logs