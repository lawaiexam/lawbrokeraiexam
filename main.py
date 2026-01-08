import time
import pandas as pd
import streamlit as st
import json
from io import BytesIO

# 引入模組
from utils import github_handler as gh
from utils import ai_handler as ai
from utils import data_loader as dl
from utils import db_handler as db  # 引入資料庫模組

# -----------------------------
# 1. Page setup & 初始化
# -----------------------------
st.set_page_config(page_title="錠嵂AI考照系統", layout="wide")

# 嘗試初始化資料庫 (自動建表)
try:
    db.init_db()
except Exception as e:
    st.error(f"⚠️ 資料庫連線失敗，請檢查 MySQL 是否已啟動。\n錯誤訊息: {e}")

# Session State 初始化
if "user_info" not in st.session_state: st.session_state.user_info = None

# 確保指標檔案前綴正確
gh.migrate_pointer_prefix_if_needed()

# 初始化考試相關變數
for key, default in [
    ("df", None), ("paper", None), ("start_ts", None), ("time_limit", 0),
    ("answers", {}), ("started", False), ("show_results", False),
    ("results_df", None), ("score_tuple", None),
    ("practice_idx", 0), ("practice_correct", 0), ("practice_answers", {}),
    ("current_bank_name", ""), ("saved_to_db", False)
]:
    if key not in st.session_state:
        st.session_state[key] = default

# -----------------------------
# 2. 登入頁面 (Login UI)
# -----------------------------
def login_page():
    st.markdown("## 🔐 錠嵂 AI 考照系統 - 員工登入")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.info("**系統資訊**\n\n請輸入您的員工編號與密碼進行登入。\n(預設測試帳號: A001 / 0000)")
    with col2:
        with st.form("login_form"):
            emp_id = st.text_input("員工編號 / 業務代碼")
            password = st.text_input("密碼", type="password")
            if st.form_submit_button("登入", type="primary"):
                user = db.login_user(emp_id, password)
                if user:
                    st.session_state.user_info = user
                    st.toast(f"歡迎回來，{user['name']}！")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("帳號或密碼錯誤")

# -----------------------------
# 3. 練習模式邏輯 (保留原功能)
# -----------------------------
def show_practice_mode(paper, show_image=True):
    i = st.session_state.practice_idx
    q = paper[i]
    st.markdown(f"### 第 {i+1} / {len(paper)} 題")
    st.markdown(q["Question"])

    if show_image and str(q.get("Image","")).strip():
        try: st.image(q["Image"], use_container_width=True)
        except: st.info("圖片載入失敗。")

    # AI 提示
    if ai.gemini_ready():
        if st.button(f"💡 AI 提示（Q{i+1}）", key=f"ai_hint_practice_{i}"):
            ck, sys, usr = ai.build_hint_prompt(q)
            with st.spinner("AI 產生提示中…"):
                hint = ai.gemini_generate_cached(ck, sys, usr)
            st.session_state.setdefault("hints", {})[q["ID"]] = hint
        if q["ID"] in st.session_state.get("hints", {}):
            st.info(st.session_state["hints"][q["ID"]])

    display = [f"{lab}. {txt}" for lab, txt in q["Choices"]]
    if q["Type"] == "MC":
        picked = st.multiselect("（複選）選擇所有正確選項：", options=display, key=f"practice_pick_{i}")
        picked_labels = {opt.split(".", 1)[0] for opt in picked}
    else:
        choice = st.radio("（單選）選擇一個答案：", options=display, key=f"practice_pick_{i}")
        picked_labels = {choice.split(".", 1)[0]} if choice else set()

    if st.button("提交這題", key=f"practice_submit_{i}"):
        gold = set(q["Answer"])
        st.session_state.practice_answers[q["ID"]] = picked_labels
        if picked_labels == gold:
            st.success("✅ 答對了！")
            st.session_state.practice_correct += 1
        else:
            st.error(f"❌ 答錯了。正確：{', '.join(sorted(list(gold))) or '(空)'}")
            if str(q.get("Explanation","")).strip():
                st.caption(f"📖 題庫詳解：{q['Explanation']}")

    cols = st.columns([1,1])
    with cols[0]:
        if st.button("➡️ 下一題", key=f"practice_next_{i}"):
            if i < len(paper) - 1:
                st.session_state.practice_idx += 1
                st.rerun()
            else:
                st.success(f"🎉 完成練習：{st.session_state.practice_correct}/{len(paper)}")
    with cols[1]:
        if st.button("🔁 重新練習"):
            for k in ["practice_idx","practice_correct","practice_answers"]:
                st.session_state.pop(k, None)
            st.rerun()

# -----------------------------
# 4. 主控制器 (Main Controller)
# -----------------------------
if st.session_state.user_info is None:
    login_page()
else:
    user = st.session_state.user_info
    
    if "current_nav" not in st.session_state:
        st.session_state.current_nav = "📝 開始考試"

    # 側邊欄導航
    with st.sidebar:
        st.write(f"👤 **{user['name']}** ({user['department']})")
        
        nav = st.radio(
            "功能選單", 
            ["📝 開始考試", "📊 歷史成績", "🛠 管理員後台"],
            key="nav_selection"
        )
        st.session_state.current_nav = nav
        
        st.divider()
        if st.button("登出"):
            st.session_state.user_info = None
            st.rerun()

    # ==========================
    # 分頁 1: 開始考試
    # ==========================
    if st.session_state.current_nav == "📝 開始考試":
        st.title(" 錠嵂AI考照機器人")
        
        # --- 考試設定區塊 ---
        with st.sidebar:
            st.divider()
            st.header("⚙️ 考試參數設定")
            exam_mode = st.radio('出題模式', ['練習模式', '模擬考模式'], index=1)
            
            st.subheader("題庫來源")
            pick_type = st.selectbox("選擇類型", options=gh.BANK_TYPES, index=0)
            merge_all = st.checkbox("合併載入此類型下所有題庫檔", value=False)

            bank_source = None
            type_files = gh.list_bank_files(pick_type)

            if merge_all:
                bank_source = type_files
                st.caption(f"將合併 {len(type_files)} 檔")
                if not type_files: st.warning("無檔案")
            else:
                current_path = gh.get_current_bank_path(pick_type)
                idx = type_files.index(current_path) if current_path in type_files and type_files else 0
                pick_file = st.selectbox("選擇題庫檔", options=type_files or ["（尚無檔案）"], index=idx if type_files else 0)
                bank_source = pick_file if type_files else None

            # 載入邏輯
            if bank_source:
                try:
                    if isinstance(bank_source, list):
                        st.session_state["df"] = dl.load_banks_from_github(bank_source)
                    else:
                        data = gh.gh_download_bytes(bank_source)
                        bio = BytesIO(data)
                        try: bio.name = bank_source
                        except: pass
                        st.session_state["df"] = dl.load_bank(bio)
                except Exception as e:
                    st.error(f"載入失敗: {e}")

            if st.session_state["df"] is not None and not st.session_state["df"].empty:
                bank = st.session_state["df"]
                all_tags = sorted({t.strip() for tags in bank["Tag"].dropna().astype(str) for t in tags.split(";") if t.strip()})
                picked_tags = st.multiselect("過濾章節", options=all_tags)
                
                if picked_tags:
                    mask = bank["Tag"].astype(str).apply(lambda s: any(t in [x.strip() for x in s.split(";")] for t in picked_tags))
                    filtered = bank[mask].copy()
                else:
                    filtered = bank.copy()

                max_q = len(filtered)
                num_q = st.number_input("題目數量", min_value=1, max_value=max(1, max_q), value=min(20, max_q))
                shuffle_options = st.checkbox("隨機選項", value=True)
                random_order = st.checkbox("隨機題目", value=True)
                show_image = st.checkbox("顯示圖片", value=True)
                
                time_limit_min = st.number_input("限時(分)", 0, 300, 0)
                st.session_state.time_limit = int(time_limit_min) * 60

                if st.button("🚀 生成試卷", type="primary"):
                    st.session_state.paper = dl.sample_paper(filtered, int(num_q), random_order, shuffle_options)
                    st.session_state.start_ts = time.time()
                    st.session_state.answers = {}
                    st.session_state.started = True
                    st.session_state.show_results = False
                    st.session_state.results_df = None
                    st.session_state.saved_to_db = False 
                    
                    tags_str = ",".join(picked_tags) if picked_tags else "全範圍"
                    bank_name_simple = bank_source if isinstance(bank_source, str) else "多檔合併"
                    st.session_state.current_bank_name = f"{pick_type} - {bank_name_simple} [範圍: {tags_str}]"
                    
                    if (not merge_all) and isinstance(bank_source, str):
                        try: gh.set_current_bank_path(pick_type, bank_source)
                        except: pass
                    st.rerun()

        # --- 考試作答區 (Main Area) ---
        if st.session_state.started and st.session_state.paper and not st.session_state.show_results:
            if exam_mode == '練習模式':
                show_practice_mode(st.session_state.paper, show_image=show_image)
            else:
                # 模擬考模式 UI
                paper = st.session_state.paper
                col1, col2 = st.columns([3, 1])
                with col1: st.subheader("📝 模擬考試中")
                with col2:
                    if st.session_state.time_limit > 0:
                        elapsed = int(time.time() - st.session_state.start_ts)
                        remain = max(0, st.session_state.time_limit - elapsed)
                        mm, ss = divmod(remain, 60)
                        st.metric("⏳ 剩餘時間", f"{mm:02d}:{ss:02d}")

                answers_key = "answers"
                for idx, q in enumerate(paper, start=1):
                    st.markdown(f"**Q{idx}. {q['Question']}**")
                    if show_image and str(q.get("Image","")).strip():
                        try: st.image(q["Image"])
                        except: pass

                    display = [f"{lab}. {txt}" for lab, txt in q["Choices"]]
                    if q["Type"] == "MC":
                        picked = st.multiselect("選擇答案", options=display, key=f"q_{idx}")
                        picked_labels = {opt.split(".", 1)[0] for opt in picked}
                    else:
                        choice = st.radio("選擇答案", options=display, key=f"q_{idx}")
                        picked_labels = {choice.split(".", 1)[0]} if choice else set()
                    
                    st.session_state[answers_key][q["ID"]] = picked_labels
                    st.divider()

                # --- 交卷區 ---
                submitted = st.button("📥 交卷並看成績", type="primary", use_container_width=True)
                timeup = (st.session_state.time_limit > 0 and time.time() - st.session_state.start_ts >= st.session_state.time_limit)

                if submitted or timeup:
                    records, correct_count = [], 0
                    for q in paper:
                        gold = set(q["Answer"])
                        pred = st.session_state[answers_key].get(q["ID"], set())
                        is_correct = (pred == gold)
                        correct_count += int(is_correct)
                        
                        records.append({
                            "ID": q["ID"], 
                            "Tag": q.get("Tag", ""), 
                            "Question": q["Question"],
                            "Choices": q.get("Choices", []), 
                            "Your Answer": "".join(sorted(list(pred))),
                            "Correct": "".join(sorted(list(gold))),
                            "Result": "✅" if is_correct else "❌",
                            "Explanation": q.get("Explanation", "")
                        })
                    
                    result_df = pd.DataFrame.from_records(records)
                    final_score = round(100 * correct_count / len(paper), 2)
                    
                    st.session_state.results_df = result_df
                    st.session_state.score_tuple = (correct_count, len(paper), final_score)
                    st.session_state.show_results = True

                    # === 寫入 MySQL (含防重複機制) ===
                    if not st.session_state.get("saved_to_db", False):
                        duration = int(time.time() - st.session_state.start_ts)
                        
                        # [修正] 取得題庫名稱並截斷，避免超過 MySQL VARCHAR(50) 限制導致寫入錯誤
                        raw_bank_name = st.session_state.get("current_bank_name", "未知題庫")
                        bank_name = (raw_bank_name[:47] + "...") if len(raw_bank_name) > 50 else raw_bank_name
                        
                        # 篩選錯題
                        df_wrong = result_df[result_df["Result"] == "❌"]
                        
                        db.save_exam_record(
                            emp_id=user["emp_id"],
                            bank_type=bank_name,
                            score=final_score,
                            duration=duration,
                            wrong_df=df_wrong
                        )
                        st.session_state.saved_to_db = True # 鎖定寫入狀態
                        st.toast("✅ 成績與錯題紀錄已儲存！")
                    
                    st.rerun()

        # --- 結果顯示區 (含 AI 詳解) ---
        elif st.session_state.started and st.session_state.show_results:
            correct_count, total_q, score_pct = st.session_state.score_tuple
            st.success(f"🏆 考試結束！分數：{score_pct} 分 ({correct_count}/{total_q})")
            
            result_df = st.session_state.results_df
            with st.expander("查看完整作答明細"):
                st.dataframe(result_df)
                st.download_button("⬇️ 下載 CSV", data=result_df.to_csv(index=False).encode("utf-8-sig"), file_name="result.csv")

            st.subheader("🤖 AI 錯題解析")
            df_wrong = result_df[result_df["Result"] == "❌"]
            
            if df_wrong.empty:
                st.balloons()
                st.info("太強了！全對！")
            else:
                st.info(f"以下是您答錯的 {len(df_wrong)} 題，AI 老師將為您逐題解析。")

                if st.session_state.results_df is not None:
                    st.divider()
                    st.subheader("📊 測驗結果詳情")

                    # 遍歷每一題
                    for idx, row in st.session_state.results_df.iterrows():
                        # 設定標題顏色與文字
                        res_icon = "✅" if row["Result"] == "✅" else "❌"
                        is_wrong = (row["Result"] == "❌")
                        
                        with st.expander(f"{res_icon} 第 {idx+1} 題：{row['Question'][:30]}...", expanded=is_wrong):
                            st.markdown(f"**完整題目**：{row['Question']}")
                            
                            c1, c2 = st.columns(2)
                            c1.info(f"正確答案：{row['Correct']}")
                            if is_wrong:
                                c2.error(f"你的答案：{row['Your Answer']}")
                            else:
                                c2.success(f"你的答案：{row['Your Answer']}")

                            st.markdown(f"**💡 原始詳解**：{row['Explanation']}")
                            
                            st.divider()

                            # AI 按鈕邏輯
                            if ai.gemini_ready():
                                btn_key = f"ai_btn_{row['ID']}_{st.session_state.start_ts}"
                                if st.button("🤖 呼叫 AI 老師詳解", key=btn_key):
                                    with st.spinner("AI 老師正在分析題目與您的盲點..."):
                                        q_data = {
                                            "Question": row["Question"],
                                            "Choices": row["Choices"],
                                            "Answer": row["Correct"],
                                            "Explanation": row["Explanation"]
                                        }
                                        ck, sys_msg, user_msg = ai.build_explain_prompt(q_data)
                                        explanation = ai.gemini_generate_cached(ck, sys_msg, user_msg)
                                        st.markdown("### 🤖 AI 老師解析：")
                                        st.markdown(explanation)
                            else:
                                st.caption("🚫 AI 功能未啟用 (未偵測到 GEMINI_API_KEY)")

            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔁 再考一次 (同設定)", use_container_width=True):
                    for k in ["paper", "start_ts", "answers", "started", "show_results", "results_df", "score_tuple"]:
                        st.session_state[k] = None if k != "answers" else {}
                    st.session_state.saved_to_db = False # 重置 DB 鎖
                    st.rerun()
            
            with col2:
                if st.button("🏁 結束複習，回首頁", type="primary", use_container_width=True):
                    for k in ["paper", "start_ts", "answers", "started", "show_results", "results_df", "score_tuple", "df"]:
                        st.session_state[k] = None if k != "answers" else {}
                    st.session_state.started = False
                    st.session_state.saved_to_db = False
                    st.rerun()

    # ==========================
    # 分頁 2: 歷史成績 (含詳細錯題檢討)
    # ==========================
    elif st.session_state.current_nav == "📊 歷史成績":
        st.title(f"📊 {user['name']} 的歷史成績")
        history = db.get_user_history(user["emp_id"])
        
        if not history.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("考試次數", f"{len(history)} 次")
            c2.metric("平均分數", f"{history['score'].mean():.1f} 分")
            c3.metric("最高分數", f"{history['score'].max():.1f} 分")
            
            st.divider()
            st.subheader("📜 測驗紀錄 (點擊表格以查看錯題)")

            display_df = history[["exam_date", "bank_type", "score", "duration_seconds"]].copy()
            display_df.columns = ["測驗時間", "題庫與範圍", "分數", "耗時(秒)"]
            
            event = st.dataframe(
                display_df,
                on_select="rerun",
                selection_mode="single-row",
                use_container_width=True,
                hide_index=True
            )

            # 若有選取，顯示詳細資料
            if len(event.selection.rows) > 0:
                selected_index = event.selection.rows[0]
                selected_record = history.iloc[selected_index]
                
                st.info(f"您正在檢視：{selected_record['exam_date']} 的錯題紀錄")
                
                try:
                    wrong_log_str = selected_record.get("wrong_log", "[]")
                    if not wrong_log_str: wrong_log_str = "[]"
                    wrong_data = json.loads(wrong_log_str)
                    
                    if wrong_data:
                        st.markdown("### ❌ 錯題檢討卡片")
                        for w in wrong_data:
                            with st.expander(f"Q: {w.get('Question', '題目遺失')}", expanded=True):
                                # 顯示選項
                                if "Choices" in w and w["Choices"]:
                                    st.markdown("**選項：**")
                                    # 嘗試解析選項 (若已是列表則直接用，若是字串則需解析)
                                    choices_data = w["Choices"]
                                    if isinstance(choices_data, str):
                                        try: choices_data = eval(choices_data) 
                                        except: choices_data = [] # Fallback
                                    
                                    if isinstance(choices_data, list):
                                        for item in choices_data:
                                            # 處理 tuple 或 string 格式
                                            if isinstance(item, (list, tuple)) and len(item) >= 2:
                                                lab, txt = item[0], item[1]
                                            elif isinstance(item, str):
                                                lab, txt = item[:1], item[2:] # 簡易切分
                                            else:
                                                continue
                                                
                                            prefix = ""
                                            if lab in w.get("Your Answer", ""): prefix += " ❌ (您的回答)"
                                            if lab in w.get("Correct", ""): prefix += " ✅ (正確答案)"
                                            
                                            if "✅" in prefix:
                                                st.markdown(f":green[**{lab}. {txt}**] {prefix}")
                                            elif "❌" in prefix:
                                                st.markdown(f":red[**{lab}. {txt}**] {prefix}")
                                            else:
                                                st.write(f"{lab}. {txt}")
                                    st.divider()

                                c_a, c_b = st.columns(2)
                                c_a.error(f"你的答案: {w.get('Your Answer', '')}")
                                c_b.success(f"正確答案: {w.get('Correct', '')}")
                                
                                if w.get("Explanation"):
                                    st.info(f"💡 解析: {w['Explanation']}")
                                
                                # AI 按鈕 (歷史紀錄版)
                                if ai.gemini_ready():
                                    if st.button(f"🤖 呼叫 AI 老師詳解", key=f"ai_btn_hist_{selected_record['id']}_{w.get('ID', 'unknown')}"):
                                        q_data = {
                                            "Question": w.get("Question", ""),
                                            "Choices": w.get("Choices", []),
                                            "Answer": w.get("Correct", ""), 
                                            "Explanation": w.get("Explanation", "")
                                        }
                                        ck, sys, usr = ai.build_explain_prompt(q_data)
                                        with st.spinner("AI 老師正在解題中..."):
                                            st.markdown(ai.gemini_generate_cached(ck, sys, usr))

                    else:
                        st.success("🎉 太棒了！該次測驗滿分 (或無錯題)。")
                        
                except Exception as e:
                    st.warning(f"無法讀取錯題資料: {e}")

        else:
            st.info("目前尚無考試紀錄。")

    # ==========================
    # 分頁 3: 管理員後台
    # ==========================
    elif st.session_state.current_nav == "🛠 管理員後台":
        st.title("🛠 管理員後台")
        
        if user["emp_id"] != "admin":
            st.error("⛔️ 權限不足，僅限管理員存取。")
        else:
            tab1, tab2 = st.tabs(["全體成績報表", "題庫上傳管理"])
            
            with tab1:
                all_data = db.get_all_history()
                if not all_data.empty:
                    st.dataframe(all_data, use_container_width=True)
                    csv = all_data.to_csv(index=False).encode('utf-8-sig')
                    st.download_button("📥 下載完整報表 (CSV)", csv, "full_report.csv", "text/csv")
                else:
                    st.warning("暫無資料")

            with tab2:
                st.subheader("Excel 題庫上傳")
                up_type = st.selectbox("上傳類型", options=gh.BANK_TYPES)
                up = st.file_uploader("選擇 Excel", type=["xlsx"])
                name = st.text_input("儲存檔名", value=f"new_bank_{int(time.time())}.xlsx")
                set_now = st.checkbox("上傳後直接設為預設題庫", value=True)
                
                if st.button("確認上傳"):
                    if up and name:
                        dest = f"{gh._type_dir(up_type)}/{name}"
                        gh.gh_put_file(dest, up.getvalue(), f"Admin upload {name}")
                        if set_now:
                            gh.set_current_bank_path(up_type, dest)
                        st.success(f"✅ 上傳成功！路徑：{dest}")
                    else:
                        st.error("請選擇檔案並輸入檔名")