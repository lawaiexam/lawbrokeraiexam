import os
import json
import time
import io
import sys

# 1. 設定 API KEY
API_KEY = "" 

from google import genai
from google.genai import types

def safe_print(text):
    try:
        print(text)
    except:
        pass

client = genai.Client(api_key=API_KEY)

CONFIGS = {
    "人身保險": {
        "pdf_path": "bank/人身/筆記_人身.pdf",
        "chapters": [
            "保險中重要的角色", "保險契約", "保險契約六大原則", "契約解除、無效、失效、停效、復效",
            "保險金與解約金", "繼承相關", "遺產稅、贈與稅", "所得稅",
            "保險業務員相關法規及規定", "金融消費者保護法", "個人資料保護法", "洗錢防制法",
            "風險與風險管理", "人身保險歷史及生命表", "保險費架構、解約金、準備金、保單紅利",
            "人身保險意義、功能、分類", "人身保險－人壽保險", "人身保險－年金保險",
            "人身保險－健康保險", "人身保險－傷害保險", "人身保險－其他人身保險", "投保實務與行銷"
        ]
    },
    "投資型保險": {
        "pdf_path": "bank/投資型/筆記_投資型.pdf",
        "chapters": [
            "投資型保險概論", "投資型保險法令介紹", "金融體系概述", "證券投資信託及顧問之規範與制度",
            "貨幣時間價值", "債券評價", "證券評價", "風險、報酬與投資組合",
            "資本資產訂價模式、績效", "投資工具簡介"
        ]
    },
    "外幣保單": {
        "pdf_path": "bank/外幣/筆記_外幣.pdf",
        "chapters": [
            "壽險基本概念", "保險業辦理外匯業務管理辦法", "管理外匯條例", "外匯收支或交易申報辦法",
            "保險業辦理國外投資管理辦法", "人身保險業辦理以外幣收付之非投資型人身保險業務應具備資格條件及注意事項",
            "投資型保險觀念", "投資型保險專設帳簿保管機構及投資標的應注意事項",
            "銷售應注意事項", "新型態人身保險商品審查", "保險業各類監控措施"
        ]
    }
}

# 👇 新增：自動重試函式，專門對付 503 錯誤
def generate_with_retry(model_id, contents, config, retries=5):
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=contents,
                config=config
            )
            return response
        except Exception as e:
            error_str = str(e)
            # 如果是 503 (Overloaded) 或 429 (Too Many Requests)
            if "503" in error_str or "429" in error_str:
                wait_time = (attempt + 1) * 10  # 第一次等 10秒, 第二次 20秒...
                safe_print(f"   [Server Busy] 503/429 Error. Retrying in {wait_time}s... (Attempt {attempt+1}/{retries})")
                time.sleep(wait_time)
            else:
                # 如果是其他錯誤 (如 API Key 錯)，直接丟出異常
                raise e
    raise Exception("Max retries exceeded. Google Server is too busy.")

full_data = {}

for exam_name, conf in CONFIGS.items():
    safe_print(f"\n>>> Processing: {exam_name}") 
    
    if not os.path.exists(conf['pdf_path']):
        safe_print(f"xx File not found: {conf['pdf_path']}")
        continue

    try:
        with open(conf['pdf_path'], 'rb') as f:
            file_bytes = f.read()
            
        file_io = io.BytesIO(file_bytes)
        file_io.name = "temp_upload_file.pdf" 

        # A. 上傳
        uploaded_file = client.files.upload(
            file=file_io,
            config=types.UploadFileConfig(mime_type='application/pdf')
        )
        
        safe_print(f"   [OK] Uploaded. Waiting for processing...")
        
        while uploaded_file.state == "PROCESSING":
            time.sleep(2)
            uploaded_file = client.files.get(name=uploaded_file.name)
            
        if uploaded_file.state != "ACTIVE":
            safe_print(f"   [Error] File state: {uploaded_file.state}")
            continue

        # B. Prompt
        prompt = (
            f"你是一位專業的保險考題分析師。請仔細閱讀這份文件（包含圖片與表格內的文字）。\n"
            f"你的任務是針對下列每一個章節，提取 5-8 個最關鍵的『專有名詞』(Keyword)。\n"
            f"如果該章節內容在表格圖片中，請務必辨識圖片文字。\n\n"
            f"章節清單：{conf['chapters']}\n\n"
            f"請直接回傳純 JSON 格式： {{ \"章節名\": [\"關鍵字1\", \"關鍵字2\"...], ... }}"
        )

        safe_print("   [AI] Analyzing content (approx 20s)...")
        
        # C. 請求 (改用 retry 函式)
        response = generate_with_retry(
            model_id="gemini-2.5-flash",
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        
        # D. 解析
        data = json.loads(response.text)
        full_data[exam_name] = data
        safe_print(f"   [Success] Keywords generated for {exam_name}!")

    except Exception as e:
        safe_print(f"   [Error] {e}")

# 存檔
json_filename = "keywords_db.json"
with open(json_filename, "w", encoding="utf-8") as f:
    json.dump(full_data, f, ensure_ascii=False, indent=4)

safe_print(f"\n*** All Done! Saved to {json_filename} ***")