import time
import pandas as pd
from utils import data_loader as dl
from utils import db_handler as db

def build_paper(df, n_questions: int, random_order=True, shuffle_options=True):
    return dl.sample_paper(df, n_questions, random_order=random_order, shuffle_options=shuffle_options)

def grade_paper(paper, answers: dict) -> tuple[pd.DataFrame, tuple[int,int,int], pd.DataFrame]:
    rows = []
    correct = 0
    for q in paper:
        qid = q["ID"]
        gold = set(q["Answer"])
        pred = set(answers.get(qid, []))

        ok = (pred == gold)
        if ok:
            correct += 1

        rows.append({
            "ID": qid,
            "Tag": q.get("Tag",""),
            "Question": q.get("Question",""),
            "Type": q.get("Type",""),
            "Choices": q.get("Choices", []),

            # ✅ 對齊 db_handler.save_exam_record() 的欄名
            "Your Answer": sorted(list(pred)),
            "Correct": sorted(list(gold)),

            "Explanation": q.get("Explanation",""),
            "Result": "✅" if ok else "❌",
        })

    results_df = pd.DataFrame(rows)
    total = len(paper)
    score = int(round((correct / total) * 100)) if total else 0
    wrong_df = results_df[results_df["Result"] == "❌"].copy()
    return results_df, (correct, total, score), wrong_df

def persist_exam_record(user, bank_type: str, score_tuple: tuple[int, int, int], duration_sec: int, wrong_df):
    """
    對齊 utils/db_handler.py 的 save_exam_record(emp_id, bank_type, score, duration, wrong_df)
    """
    correct, total, score = score_tuple  # correct/total 目前 DB 不存，但保留計算用
    db.save_exam_record(
        user["emp_id"],
        bank_type,
        score,
        duration_sec,
        wrong_df
    )
