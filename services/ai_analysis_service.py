import streamlit as st
from google import genai
from google.genai import types

def generate_overall_analysis(wrong_df, exam_type="模擬考"):
    """
    接收錯題的 DataFrame，請 AI 進行整體診斷與建議。
    """
    # 1. 檢查 API Key
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        return "❌ 錯誤：找不到 GEMINI_API_KEY，請檢查 secrets.toml 設定。"

    # 2. 準備錯題資料
    # 為了節省 Token 並讓 AI 聚焦，我們整理成「章節 - 題目」的格式
    if wrong_df.empty:
        return "🎉 太棒了！本次考試沒有錯題，無須分析。請繼續保持！"

    # 限制題目數量，避免超過 Token 上限 (例如取前 30 題錯題，或全部)
    # 通常錯題不會太多，全部送出效果最好
    questions_text = ""
    for idx, row in wrong_df.iterrows():
        # 嘗試取得章節與題目，若無欄位則用預設值
        chapter = row.get("AI分類章節", "未分類章節")
        question = row.get("題目", row.get("q_text", "題目內容遺失"))
        questions_text += f"- [{chapter}] {question}\n"

    # 3. 建立 Prompt (提示詞)
    prompt = f"""
    你是一位專業的保險證照考試教練。學生剛剛完成了一份「{exam_type}」，以下是他的「所有錯題列表」。
    請你根據這些錯題，幫學生做一份「整體學習診斷」。

    錯題列表：
    {questions_text}

    請輸出以下分析內容（請用 Markdown 格式，語氣鼓勵且專業）：
    1. **🔍 弱點分布分析**：指出學生在哪個章節或哪類概念錯誤最多（例如：「你似乎對『保險法規』中的罰則特別不熟...」）。
    2. **💡 觀念盲點偵測**：分析這些錯題背後，是否反映出某種錯誤的邏輯或混淆的觀念。
    3. **🚀 下一步加強建議**：給予 3 點具體的複習建議（例如：「建議重新複習第 3 章的年金險種類比較表」）。
    
    請直接給出分析結果，不需要開頭問候語。
    """

    # 4. 呼叫 Gemini API
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash", # 使用較快速的 Flash 模型即可
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3 # 降低隨機性，讓分析較為客觀
            )
        )
        return response.text
    except Exception as e:
        return f"❌ AI 分析失敗：{str(e)}"