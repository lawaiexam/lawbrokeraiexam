import streamlit as st

DEFAULTS = {
    "user_info": None,

    # bank / exam
    "df": None,
    "paper": None,
    "current_bank_name": "",

    # mock exam
    "start_ts": None,
    "time_limit": 0,
    "answers": {},
    "started": False,
    "show_results": False,
    "results_df": None,
    "score_tuple": None,
    "saved_to_db": False,

    # practice
    "practice_idx": 0,
    "practice_correct": 0,
    "practice_answers": {},

    # AI cache
    "hints": {},
}

def ensure_state():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v
