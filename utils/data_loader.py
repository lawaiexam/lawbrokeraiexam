import pandas as pd
import random
import streamlit as st
import re
from io import BytesIO
from .github_handler import gh_download_bytes

def normalize_bank_df(df: pd.DataFrame, sheet_name: str | None = None, source_file: str | None = None) -> pd.DataFrame:
    """
    標準化題庫 DataFrame，處理不同 Excel 的欄位名稱差異與答案格式。
    """
    # 複製一份以免影響原始資料
    df = df.copy()
    
    # --- 1. 強力清洗欄位名稱 ---
    # 去除前後空白、換行符號、空格
    df.columns = [str(c).strip().replace("\n", "").replace(" ", "") for c in df.columns]

    # --- 2. 欄位翻譯對照表 ---
    col_map = {
        # ID
        "編號": "ID", "題號": "ID", "題目編號": "ID", "qp_id": "ID",
        
        # 題目
        "題目": "Question", "題幹": "Question", "題目內容": "Question", "qp_title": "Question", "問題": "Question",
        
        # 解析 (移除 '備註' 以免與解答說明衝突)
        "解答說明": "Explanation", "解釋說明": "Explanation", "詳解": "Explanation", 
        "qp_explain": "Explanation", "解析": "Explanation",
        
        # 標籤/章節
        "標籤": "Tag", "章節": "Tag", "科目": "Tag", 
        "分區": "Tag", "題庫分類": "Tag", "qp_ch": "Tag", "分類": "Tag", 
        "AI分類章節": "Tag", # 針對人身保險檔案
        
        # 圖片
        "圖片": "Image", "圖檔": "Image",
        
        # 選項 (標準化處理)
        "選項一": "OptionA", "選項二": "OptionB", "選項三": "OptionC", "選項四": "OptionD", "選項五": "OptionE",
        "選項1": "OptionA", "選項2": "OptionB", "選項3": "OptionC", "選項4": "OptionD", "選項5": "OptionE",
        "答案選項1": "OptionA", "答案選項2": "OptionB", "答案選項3": "OptionC", "答案選項4": "OptionD", "答案選項5": "OptionE",
        "qp_a1": "OptionA", "qp_a2": "OptionB", "qp_a3": "OptionC", "qp_a4": "OptionD",
        "A": "OptionA", "B": "OptionB", "C": "OptionC", "D": "OptionD", "E": "OptionE",
        
        # 答案 (外幣檔案有這欄，人身/投資型可能沒有)
        "答案": "Answer", 
        "正確選項": "Answer", 
        "正確答案": "Answer",
        "標準答案": "Answer",
        "qp_right": "Answer",
        
        # 題型
        "題型": "Type",
    }
    
    # 套用翻譯
    df = df.rename(columns={c: col_map.get(c, c) for c in df.columns})

    # --- 3. 解決重複欄位問題 ---
    # 確保不會有多個 Explanation 或 Tag 欄位 (例如同時有 '備註' 和 '解答說明')
    df = df.loc[:, ~df.columns.duplicated()]

    # --- 4. 自動辨識選項欄位 (補救措施) ---
    option_cols = sorted([c for c in df.columns if c.startswith("Option")])
    
    # 如果找不到 OptionA... 嘗試暴力搜尋未被 map 到的欄位
    if not option_cols:
        for col in df.columns:
            col_str = str(col)
            if "選項" in col_str or "Option" in col_str:
                if "1" in col_str or "一" in col_str or "A" in col_str: df.rename(columns={col: "OptionA"}, inplace=True)
                elif "2" in col_str or "二" in col_str or "B" in col_str: df.rename(columns={col: "OptionB"}, inplace=True)
                elif "3" in col_str or "三" in col_str or "C" in col_str: df.rename(columns={col: "OptionC"}, inplace=True)
                elif "4" in col_str or "四" in col_str or "D" in col_str: df.rename(columns={col: "OptionD"}, inplace=True)
                elif "5" in col_str or "五" in col_str or "E" in col_str: df.rename(columns={col: "OptionE"}, inplace=True)
        option_cols = sorted([c for c in df.columns if c.startswith("Option")])

    # 若連兩個選項都找不到，這份資料視為無效
    if len(option_cols) < 2:
        return pd.DataFrame()

    # 補齊必要欄位
    if "ID" not in df.columns:
        df["ID"] = range(1, len(df) + 1)
    
    if "Question" not in df.columns:
        return pd.DataFrame()

    for col in ["Explanation", "Tag", "Image", "Answer"]:
        if col not in df.columns: df[col] = ""

    # 確保選項內容是字串
    for oc in option_cols:
        df[oc] = df[oc].fillna("").astype(str)

    # --- 5. 答案處理核心邏輯 (支援數字欄位 與 星號標記) ---
    # 你的檔案有兩種情況：
    # A. 投資型/人身：沒有 Answer 欄位，答案標在選項裡 (例如 "*選項內容")
    # B. 外幣：有 Answer 欄位 (1, 2, 3, 4)，但選項裡也有星號
    
    num_map = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}
    cleaned_answers = []

    for idx, row in df.iterrows():
        # 1. 先嘗試讀取 Answer 欄位 (外幣檔案)
        raw_ans = str(row.get("Answer", "")).strip()
        
        # 處理 Excel 浮點數 (如 1.0 -> 1 -> A)
        if raw_ans.endswith(".0"): 
            raw_ans = raw_ans[:-2]
        if raw_ans in num_map:
            raw_ans = num_map[raw_ans] # 轉成 A, B, C...
        
        # 2. 掃描選項中的星號 (人身/投資型/外幣都有)
        stars = []
        for i, oc in enumerate(option_cols):
            opt_text = str(row[oc]).strip()
            # 檢查是否以 * 或 ＊ 開頭
            if opt_text.startswith("*") or opt_text.startswith("＊"):
                # 記錄星號對應的選項 (A, B, C...)
                letter = chr(ord('A') + i)
                stars.append(letter)
                # 重要：移除選項文字中的星號，更新 DataFrame
                clean_text = opt_text.lstrip("*＊ ").strip()
                df.at[idx, oc] = clean_text
        
        # 3. 決定最終答案
        # 如果選項裡有星號，優先權最高 (因為是直接標在文字旁，最準)
        if stars:
            final_ans = "".join(stars)
        # 如果沒星號，但 Answer 欄位有值，就用 Answer 欄位
        elif raw_ans and raw_ans.upper() != "NAN":
            final_ans = raw_ans
        else:
            final_ans = "" # 真的沒答案
            
        cleaned_answers.append(final_ans)

    df["Answer"] = cleaned_answers

    # --- 6. 格式化與過濾 ---
    # 判斷單選/複選
    if "Type" not in df.columns or df["Type"].all() == "":
        df["Type"] = df["Answer"].apply(lambda x: "MC" if len(str(x)) > 1 else "SC")

    df["Type"] = df["Type"].astype(str).str.upper().str.strip()
    df["Answer"] = df["Answer"].astype(str).str.upper().str.replace(" ", "", regex=False)

    # 刪除選項全空的廢題
    def has_two_options(row):
        cnt = sum(1 for oc in option_cols if str(row.get(oc, "")).strip())
        return cnt >= 2
    df = df[df.apply(has_two_options, axis=1)].reset_index(drop=True)

    # 標籤填補
    if sheet_name:
        df["Tag"] = df["Tag"].astype(str)
        mask = df["Tag"].str.strip().eq("") | df["Tag"].str.lower().eq("nan")
        df.loc[mask, "Tag"] = sheet_name

    df["SourceFile"] = (source_file or "").strip()
    df["SourceSheet"] = (sheet_name or "").strip()
    
    return df

# === 檔案讀取區 ===

def load_bank(file_like):
    """
    讀取 Excel 檔案，支援多 Sheet 合併
    """
    try:
        xls = pd.ExcelFile(file_like)
        dfs = []
        
        # 嘗試取得檔名 (若是上傳物件)
        try:
            source_file = getattr(file_like, "name", None) or ""
            source_file = source_file.replace("\\", "/").split("/")[-1]
        except: 
            source_file = ""
            
        for sh in xls.sheet_names:
            # 跳過明顯無用的 Sheet
            if any(x in sh for x in ["修改紀錄", "空白", "附錄", "Sheet", "工作表"]):
                # 但要小心，有些只有 Sheet1，所以如果是預設名稱先不跳過，除非內容真的空
                if "空白" in sh or "附錄" in sh or "修改" in sh:
                    continue
                
            raw = pd.read_excel(xls, sheet_name=sh)
            
            # 轉換
            norm = normalize_bank_df(raw, sheet_name=sh, source_file=source_file)
            
            if not norm.empty:
                dfs.append(norm)

        if not dfs: return None
        return pd.concat(dfs, ignore_index=True)
    except Exception as e:
        st.error(f"讀取 Excel 發生錯誤: {e}")
        return None

def load_banks_from_github(paths: list[str]) -> pd.DataFrame | None:
    dfs = []
    for p in paths:
        try:
            data = gh_download_bytes(p)
            if not data: continue
            bio = BytesIO(data)
            try: bio.name = p
            except: pass
            df = load_bank(bio)
            if df is None or df.empty: continue
            dfs.append(df)
        except: continue
    if not dfs: return None
    return pd.concat(dfs, ignore_index=True)

def sample_paper(df, n, random_order=True, shuffle_options=True):
    """
    從題庫中抽選題目並生成考卷
    """
    n = min(n, len(df))
    if n <= 0: return []

    option_cols = sorted([c for c in df.columns if c.startswith("Option")])
    if not option_cols: return []

    rows = df.sample(n=n, replace=False)
    if random_order: rows = rows.sample(frac=1)

    questions = []
    for _, r in rows.iterrows():
        # 1. 收集選項
        items = []
        for i, col in enumerate(option_cols):
            txt = str(r.get(col, "")).strip()
            # 排除 nan 或空字串
            if txt and txt.lower() != "nan":
                orig_lab = chr(ord('A') + i)
                items.append((orig_lab, txt))

        if not items: continue

        # 2. 選項洗牌 (若需要)
        if shuffle_options: random.shuffle(items)

        # 3. 重新賦予 A, B, C, D...
        choices, orig_to_new = [], {}
        for idx, (orig_lab, txt) in enumerate(items):
            new_lab = chr(ord('A') + idx)
            choices.append((new_lab, txt))
            orig_to_new[orig_lab] = new_lab

        # 4. 轉換答案 (舊答案字母 -> 新答案字母)
        raw_ans = str(r.get("Answer", "")).upper().strip()
        ans_clean = re.sub(r'[^A-E]', '', raw_ans) # 只保留 A-E
        
        new_ans = {orig_to_new[a] for a in set(ans_clean) if a in orig_to_new}

        questions.append({
            "ID": r["ID"],
            "Question": r["Question"],
            "Type": str(r.get("Type", "SC")).upper(),
            "Choices": choices,
            "Answer": new_ans,
            "Explanation": r.get("Explanation", ""),
            "Image": r.get("Image", ""),
            "Tag": r.get("Tag", ""),
            "SourceFile": r.get("SourceFile", ""),
            "SourceSheet": r.get("SourceSheet", ""),
        })
    return questions