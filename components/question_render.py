import streamlit as st

def render_question(q, show_image=True, answer_key: str | None = None):
    st.markdown(q["Question"])

    if show_image and str(q.get("Image","")).strip():
        try:
            st.image(q["Image"], use_container_width=True)
        except Exception:
            st.info("圖片載入失敗。")

    display = [f"{lab}. {txt}" for lab, txt in q["Choices"]]

    if q["Type"] == "MC":
        picked = st.multiselect("（複選）選擇所有正確選項：", options=display, key=answer_key)
        picked_labels = {opt.split(".", 1)[0] for opt in picked}
    else:
        choice = st.radio("（單選）選擇一個答案：", options=display, key=answer_key)
        picked_labels = {choice.split(".", 1)[0]} if choice else set()

    return picked_labels
