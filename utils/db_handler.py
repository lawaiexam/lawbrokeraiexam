# utils/db_handler.py
import mysql.connector
from mysql.connector import Error
import pandas as pd
import streamlit as st
from datetime import datetime
import json

# =========================
# DB Connection
# =========================
def get_connection():
    try:
        conf = st.secrets["mysql"]
        return mysql.connector.connect(
            host=conf["host"],
            database=conf["database"],
            user=conf["user"],
            password=conf["password"],
            port=conf.get("port", 3306),
        )
    except Error as e:
        st.error(f"無法連接到 MySQL 資料庫: {e}")
        return None


# =========================
# Init DB（只負責建基本表）
# =========================
def init_db():
    conn = get_connection()
    if conn is None:
        return
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            emp_id VARCHAR(50) PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            password VARCHAR(100) DEFAULT '0000',
            department VARCHAR(50)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            emp_id VARCHAR(50),
            bank_type VARCHAR(100),
            score FLOAT,
            duration_seconds INT,
            wrong_log JSON,
            exam_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            section_scores JSON NULL,
            total_score INT NULL,
            passed TINYINT(1) NULL,
            fail_reason VARCHAR(50) NULL,
            FOREIGN KEY (emp_id) REFERENCES users(emp_id)
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.executemany(
            "INSERT INTO users (emp_id, name, password, department) VALUES (%s, %s, %s, %s)",
            [
                ("ZZ0001", "王小明", "@Zz@0001", "業務一部"),
                ("ZZ0002", "李大華", "@Zz@0002", "業務二部"),
                ("admin", "管理員", "admin888", "總務部"),
            ],
        )
        conn.commit()

    cursor.close()
    conn.close()


# =========================
# Auth
# =========================
def login_user(emp_id, password):
    conn = get_connection()
    if not conn:
        return None
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT emp_id, name, department FROM users WHERE emp_id=%s AND password=%s",
        (emp_id, password),
    )
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


# =========================
# Save Exam Record
# =========================
def save_exam_record(
    emp_id,
    bank_type,
    score,
    duration,
    wrong_df,
    section_scores=None,
    total_score=None,
    passed=None,
    fail_reason=None,
):
    conn = get_connection()
    if conn is None:
        return
    cursor = conn.cursor()

    if isinstance(wrong_df, pd.DataFrame) and not wrong_df.empty:
        desired_cols = [
            "ID", "Tag", "Question", "Type",
            "Choices", "YourAnswer", "CorrectAnswer", "Explanation"
        ]
        valid_cols = [c for c in desired_cols if c in wrong_df.columns]
        wrong_json = wrong_df[valid_cols].to_json(orient="records", force_ascii=False)
    else:
        wrong_json = "[]"

    stmt = """
        INSERT INTO records
        (emp_id, bank_type, score, duration_seconds, wrong_log, exam_date,
         section_scores, total_score, passed, fail_reason)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    cursor.execute(
        stmt,
        (
            emp_id,
            bank_type,
            score,
            int(duration),
            wrong_json,
            datetime.now(),
            json.dumps(section_scores, ensure_ascii=False) if section_scores else None,
            total_score,
            passed,
            fail_reason,
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()


# =========================
# History (User)
# =========================
def get_user_history(emp_id):
    conn = get_connection()
    if not conn:
        return pd.DataFrame()

    query = """
        SELECT
            id, bank_type, score, total_score,
            section_scores, passed, fail_reason,
            duration_seconds, exam_date, wrong_log
        FROM records
        WHERE emp_id = %s
        ORDER BY exam_date DESC
    """
    df = pd.read_sql(query, conn, params=(emp_id,))
    conn.close()
    return df


# =========================
# History (Admin)
# =========================
def get_all_history():
    conn = get_connection()
    if not conn:
        return pd.DataFrame()

    query = """
        SELECT
            r.id, u.name, u.department,
            r.bank_type, r.score, r.total_score,
            r.passed, r.exam_date
        FROM records r
        JOIN users u ON r.emp_id = u.emp_id
        ORDER BY r.exam_date DESC
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df
