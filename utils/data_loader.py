import pandas as pd
import random
import streamlit as st
import re
from io import BytesIO
from .github_handler import gh_download_bytes

# ==============================================================================
# 核心資料清洗邏輯 (Universal Cleaner V6)
# ==============================================================================
def clean_and_normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    通用資料清洗函式 (V6 最終強化版)
    修正：答案欄位強力轉型 (處理 (2), 2.0, B 等雜訊)、補強題目映射
    """
    if df is None or df.empty:
        return df

    # 複製以免影響原始資料
    df = df.copy()

    try:
        # 1. 清洗欄位名稱 (去除前後空白、換行)
        df.columns = [str(c).strip().replace("\n", "").replace(" ", "") for c in df.columns]

        # 2. 統一 ID 欄位
        if "ID" not in df.columns:
            for c in ["編號", "題目編號", "題號", "qp_id"]:
                if c in df.columns:
                    df.rename(columns={c: "ID"}, inplace=True)
                    break
            if "ID" not in df.columns:
                df["ID"] = range(1, len(df) + 1)

        # 3. 統一 題目 (Question) 欄位
        if "Question" not in df.columns:
            for c in ["題目", "題幹", "題目內容", "qp_title", "問題"]:
                if c in df.columns:
                    df.rename(columns={c: "Question"}, inplace=True)
                    break

        # 4. 統一 圖片 (Image) 欄位
        if "Image" not in df.columns:
            for c in ["圖片", "圖檔"]:
                if c in df.columns:
                    df.rename(columns={c: "Image"}, inplace=True)
                    break

        # 定義選項映射表 (Label -> 可能的欄位名)
        option_map_config = [
            ('A', ['選項一', '選項1', 'OptionA', 'A', 'qp_a1', '答案選項1']),
            ('B', ['選項二', '選項2', 'OptionB', 'B', 'qp_a2', '答案選項2']),
            ('C', ['選項三', '選項3', 'OptionC', 'C', 'qp_a3', '答案選項3']),
            ('D', ['選項四', '選項4', 'OptionD', 'D', 'qp_a4', '答案選項4']),
            ('E', ['選項五', '選項5', 'OptionE', 'E', 'qp_a5', '答案選項5'])
        ]

        # 5. 處理正確答案 (Answer) - 混合策略
        
        # 5a. 尋找答案欄位
        ans_col = None
        for c in ["Answer", "正確選項", "答案", "標準答案", "qp_right", "CorrectAnswer"]:
            if c in df.columns:
                ans_col = c
                break
        
        if ans_col:
            def normalize_answer(val):
                # 強力標準化：轉字串 -> 去空白 -> 轉大寫
                s = str(val).strip().upper()
                # 去除括號 (A) -> A, (1) -> 1
                s = s.replace("(", "").replace(")", "").replace("（", "").replace("）", "")
                # 去除小數點 1.0 -> 1
                if s.endswith(".0"): s = s[:-2]
                
                # 映射表
                mapping = {
                    '1': 'A', '2': 'B', '3': 'C', '4': 'D', '5': 'E',
                    '一': 'A', '二': 'B', '三': 'C', '四': 'D', '五': 'E'
                }
                # 如果是數字鍵則轉換，否則保留原樣 (如 'A', 'AB')
                return mapping.get(s, s)
            
            df["Answer"] = df[ans_col].apply(normalize_answer)
        else:
            df["Answer"] = ""

        # 5b. 掃描選項中的星號 (補強：若答案欄為空或無效，再次掃描選項)
        def extract_star_answer(row):
            # 檢查現有答案是否有效 (必須是 A-E 或是組合)
            current_ans = str(row.get("Answer", "")).strip()
            # 簡單判斷：如果有內容且不是 nan，就信任它
            if current_ans and current_ans.lower() != "nan":
                return current_ans
            
            # 否則掃描選項找星號
            stars = []
            for label, possible_cols in option_map_config:
                for col in possible_cols:
                    if col in row and pd.notna(row[col]):
                        txt = str(row[col]).strip()
                        # 支援全形與半形星號
                        if txt.startswith("*") or txt.startswith("＊"):
                            stars.append(label)
            return "".join(stars)

        df["Answer"] = df.apply(extract_star_answer, axis=1)

        # 5c. 移除選項文字中的星號 (保持介面乾淨)
        all_opt_cols = [col for _, cols in option_map_config for col in cols]
        for c in all_opt_cols:
            if c in df.columns:
                df[c] = df[c].apply(lambda x: str(x).lstrip('*').lstrip('＊').strip() if pd.notna(x) else x)

        # 6. 強力打包選項 (Choices)
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
                    if found_text:
                        choices.append((label, found_text))
                return choices

            df["Choices"] = df.apply(universal_pack, axis=1)

        # 7. 處理詳解
        if "Explanation" not in df.columns:
            for c in ["解答說明", "解析", "詳解", "qp_explain"]:
                if c in df.columns:
                    df["Explanation"] = df[c]
                    break
        
        # 8. 處理題型 (Type)
        if "Type" not in df.columns:
            if "題型" in df.columns:
                df["Type"] = df["題型"]
            else:
                df["Type"] = df["Answer"].apply(lambda x: "MC" if len(str(x)) > 1 else "SC")

        # 9. 處理標籤 (Tag)
        if "Tag" not in df.columns:
            for c in ["章節", "分類", "科目", "AI分類章節", "qp_ch"]:
                if c in df.columns:
                    df["Tag"] = df[c]
                    break

        return df

    except Exception as e:
        st.error(f"資料格式清洗失敗 (clean_and_normalize_df)：{e}")
        return pd.DataFrame()

# ==============================================================================
# 舊有相容層
# ==============================================================================

def normalize_bank_df(df: pd.DataFrame, sheet_name: str | None = None, source_file: str | None = None) -> pd.DataFrame:
    df = clean_and_normalize_df(df)
    if not df.empty:
        if "Tag" not in df.columns or df["Tag"].all() == "":
             if sheet_name:
                 df["Tag"] = sheet_name

        df["SourceFile"] = (source_file or "").strip()
        df["SourceSheet"] = (sheet_name or "").strip()
        
        for col in ["Explanation", "Tag", "Image", "Answer", "Question"]:
            if col not in df.columns: df[col] = ""

        if "Choices" in df.columns:
            df = df[df["Choices"].apply(lambda x: len(x) >= 2)].reset_index(drop=True)

    return df

# ==============================================================================
# 檔案讀取區
# ==============================================================================

def load_bank(file_like):
    try:
        xls = pd.ExcelFile(file_like)
        dfs = []
        try:
            source_file = getattr(file_like, "name", None) or ""
            source_file = source_file.replace("\\", "/").split("/")[-1]
        except: 
            source_file = ""
            
        for sh in xls.sheet_names:
            if any(x in sh for x in ["修改紀錄", "空白", "附錄", "Sheet", "工作表"]):
                if "空白" in sh or "附錄" in sh or "修改" in sh:
                    continue
            raw = pd.read_excel(xls, sheet_name=sh)
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

    # 1. 直接抽題
    rows = df.sample(n=n, replace=False)
    if random_order: rows = rows.sample(frac=1)

    questions = []
    for _, r in rows.iterrows():
        # 確保 Question 欄位存在
        q_text = r.get("Question")
        if not q_text or pd.isna(q_text):
            q_text = r.get("題目", "")
            
        choices = r.get("Choices", [])
        if not choices: continue

        # 複製一份以免影響原始參照
        current_choices = list(choices)

        # 舊答案 (字串集合)
        raw_ans_str = str(r.get("Answer", "")).upper().strip() 
        # 防止 nan 跑出來
        if raw_ans_str == "NAN": raw_ans_str = ""

        # 建立舊 Label 對映表
        label_to_text = {lab: txt for lab, txt in current_choices}

        # 若需要洗牌選項
        if shuffle_options:
            items = [txt for _, txt in current_choices]
            random.shuffle(items)
            
            new_choices = []
            new_ans_set = set()
            
            # 重新分配 A, B, C...
            for idx, txt in enumerate(items):
                new_lab = chr(ord('A') + idx)
                new_choices.append((new_lab, txt))
                
                # 反查舊 Label
                orig_label = None
                for ol, ot in label_to_text.items():
                    if ot == txt:
                        orig_label = ol
                        break
                
                if orig_label and orig_label in raw_ans_str:
                    new_ans_set.add(new_lab)
            
            final_choices = new_choices
            final_ans = new_ans_set
        else:
            final_choices = current_choices
            final_ans = set(raw_ans_str) 

        questions.append({
            "ID": r.get("ID"),
            "Question": q_text,
            "Type": str(r.get("Type", "SC")).upper(),
            "Choices": final_choices,
            "Answer": final_ans, 
            "Explanation": r.get("Explanation", ""),
            "Image": r.get("Image", ""),
            "Tag": r.get("Tag", ""),
            "SourceFile": r.get("SourceFile", ""),
            "SourceSheet": r.get("SourceSheet", ""),
        })
    return questions
