import time
import streamlit as st
from utils import github_handler as gh

def render_upload_bank():
    st.subheader("Excel 題庫上傳")

    up_type = st.selectbox("上傳類型", options=gh.BANK_TYPES)
    up = st.file_uploader("選擇 Excel", type=["xlsx"])
    name = st.text_input("儲存檔名", value=f"new_bank_{int(time.time())}.xlsx")
    set_now = st.checkbox("上傳後直接設為預設題庫", value=True)

    if st.button("確認上傳", type="primary"):
        if up and name:
            dest = f"{gh._type_dir(up_type)}/{name}"
            gh.gh_put_file(dest, up.getvalue(), f"Admin upload {name}")
            if set_now:
                gh.set_current_bank_path(up_type, dest)
            st.success(f"✅ 上傳成功！路徑：{dest}")
        else:
            st.error("請選擇檔案並輸入檔名")
