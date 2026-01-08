# utils/db_handler.py
import mysql.connector
from mysql.connector import Error
import pandas as pd
import streamlit as st
from datetime import datetime
import json

def get_connection():
    """建立 MySQL 連線"""
    try:
        conf = st.secrets["mysql"]
        connection = mysql.connector.connect(
            host=conf["host"],
            database=conf["database"],
            user=conf["user"],
            password=conf["password"],
            port=conf.get("port", 3306)
        )
        return connection
    except Error as e:
        st.error(f"無法連接到 MySQL 資料庫: {e}")
        return None

def init_db():
    """初始化資料庫：自動建立資料表"""
    conn = get_connection()
    if conn is None: return

    cursor = conn.cursor()
    
    # 1. 建立員工資料表 (users)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            emp_id VARCHAR(50) PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            password VARCHAR(100) DEFAULT '0000',
            department VARCHAR(50)
        )
    """)
    
    # 2. 建立考試紀錄表 (records)
    # 使用 JSON 欄位存錯題 (MySQL 5.7+ 支援 JSON 格式，若太舊可用 TEXT)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            emp_id VARCHAR(50),
            bank_type VARCHAR(50),
            score FLOAT,
            duration_seconds INT,
            wrong_log JSON, 
            exam_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (emp_id) REFERENCES users(emp_id)
        )
    """)

    # --- 預設塞入一些假員工資料 (方便測試) ---
    cursor.execute("SELECT count(*) FROM users")
    if cursor.fetchone()[0] == 0:
        val = [
            ("ZZ0001", "王小明", "@Zz@0001", "業務一部"),
            ("ZZ0002", "李大華", "@Zz@0002", "業務二部"),
            ("admin", "管理員", "admin888", "總務部")
        ]
        stmt = "INSERT INTO users (emp_id, name, password, department) VALUES (%s, %s, %s, %s)"
        cursor.executemany(stmt, val)
        print("已建立預設使用者資料")
        conn.commit()

    cursor.close()
    conn.close()

def login_user(emp_id, password):
    """驗證登入"""
    conn = get_connection()
    if not conn: return None
    
    cursor = conn.cursor(dictionary=True) # 回傳字典格式
    # 注意：正式環境建議密碼要 Hash，這裡先用明碼示範
    stmt = "SELECT emp_id, name, department FROM users WHERE emp_id = %s AND password = %s"
    cursor.execute(stmt, (emp_id, password))
    user = cursor.fetchone()
    
    cursor.close()
    conn.close()
    return user # 若無查到會回傳 None

def save_exam_record(emp_id, bank_type, score, duration, wrong_df):
    """
    將考試紀錄寫入 MySQL
    :param wrong_df: 包含錯題資訊的 DataFrame，必須包含 Choices 與 Explanation
    """
    conn = get_connection()
    if conn is None:
        return

    cursor = conn.cursor()
    
    # --- [BUG FIX 2-2] 修正資料欄位過濾 ---
    # 確保寫入的 JSON 包含 AI 詳解所需的欄位 (Choices, Explanation)
    if not wrong_df.empty:
        # 定義需要保留的欄位
        desired_cols = [
            "ID", "Question", "Your Answer", "Correct", "Tag", 
            "Choices", "Explanation"  # <--- 關鍵：補上這兩個欄位
        ]
        
        # 僅保留實際存在於 DataFrame 的欄位，避免報錯
        valid_cols = [col for col in desired_cols if col in wrong_df.columns]
        
        # 轉成 JSON，force_ascii=False 確保中文可讀
        wrong_json = wrong_df[valid_cols].to_json(orient="records", force_ascii=False)
    else:
        wrong_json = "[]"

    stmt = """
        INSERT INTO records (emp_id, bank_type, score, duration_seconds, wrong_log, exam_date)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    val = (emp_id, bank_type, score, int(duration), wrong_json, datetime.now())
    
    try:
        cursor.execute(stmt, val)
        conn.commit()
        # st.success("✅ 成績已成功上傳資料庫！") # Debug 用，生產環境可註解
    except Error as e:
        st.error(f"⚠️ 寫入資料庫失敗: {e}")
    finally:
        cursor.close()
        conn.close()

def get_user_history(emp_id):
    """取得特定員工的歷史紀錄 (包含錯題細節)"""
    conn = get_connection()
    if not conn: return pd.DataFrame()
    
    # 修改：多選取 'id' 和 'wrong_log' 以便前端解析
    query = """
        SELECT id, bank_type, score, duration_seconds, exam_date, wrong_log 
        FROM records 
        WHERE emp_id = %s 
        ORDER BY exam_date DESC
    """
    df = pd.read_sql(query, conn, params=(emp_id,))
    conn.close()
    return df

def get_all_history():
    """管理員用：取得所有人的紀錄"""
    conn = get_connection()
    if not conn: return pd.DataFrame()

    query = """
        SELECT r.id, u.name, u.department, r.bank_type, r.score, r.exam_date 
        FROM records r
        JOIN users u ON r.emp_id = u.emp_id
        ORDER BY r.exam_date DESC
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df