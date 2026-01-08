import os

# 設定你的目標資料夾 (跟 secrets.toml 裡寫的一樣)
target_folder = "bank"

print(f"=== 開始檢查 '{target_folder}' 資料夾結構 ===")

if not os.path.exists(target_folder):
    print(f"❌ 錯誤：找不到主資料夾 '{target_folder}'！請確認它是否在 main.py 旁邊。")
else:
    # 遍歷所有子資料夾與檔案
    for root, dirs, files in os.walk(target_folder):
        level = root.replace(target_folder, '').count(os.sep)
        indent = ' ' * 4 * (level)
        print(f"{indent}📂 {os.path.basename(root)}/")
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            print(f"{subindent}📄 {f}")

print("=== 檢查結束 ===")