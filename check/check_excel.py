import pandas as pd
import os

# 設定要檢查的檔案路徑 (根據你剛剛掃描的結果)
files_to_check = [
    "bank/人身/人身.xlsx",
    "bank/外幣/外幣.xlsx",
    "bank/投資型/投資型.xlsx"
]

print("=== Excel 欄位名稱檢查 ===")

for path in files_to_check:
    print(f"\n📄 正在讀取：{path}")
    if not os.path.exists(path):
        print("❌ 找不到檔案，請確認路徑")
        continue
    
    try:
        # 讀取 Excel
        df = pd.read_excel(path)
        print(f"✅ 讀取成功！偵測到的欄位標題如下：")
        print(list(df.columns))
        
        # 簡易診斷
        cols = str(list(df.columns))
        has_q = any(x in cols for x in ['題目', 'Question', '題幹'])
        has_a = any(x in cols for x in ['答案', 'Answer'])
        
        if not has_q:
            print("⚠️ 警告：找不到 [題目] 相關欄位！程式會拒絕載入。")
        if not has_a:
            print("⚠️ 警告：找不到 [答案] 相關欄位！程式會拒絕載入。")
            
    except Exception as e:
        print(f"❌ 讀取失敗：{e}")

print("\n=== 檢查結束 ===")