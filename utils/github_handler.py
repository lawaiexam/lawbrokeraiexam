import os
import json
import base64
import requests
import streamlit as st

# =========================================================
# 設定讀取與模式判斷
# =========================================================
# 檢查是否啟用本機模式 (建議在 secrets.toml 設定 LOCAL_MODE = true)
LOCAL_MODE = st.secrets.get("LOCAL_MODE", False)
LOCAL_BANKS_DIR = st.secrets.get("LOCAL_BANKS_DIR", "bank")  # 本機題庫資料夾名稱

# GitHub 設定 (即使在 LOCAL_MODE 也可以保留讀取，避免變數未定義報錯)
GH_OWNER     = st.secrets.get("REPO_OWNER")
GH_REPO      = st.secrets.get("REPO_NAME")
GH_BRANCH    = st.secrets.get("REPO_BRANCH", "main")
GH_TOKEN     = st.secrets.get("GH_TOKEN")
BANKS_DIR    = st.secrets.get("BANKS_DIR", "bank")
POINTER_FILE = st.secrets.get("POINTER_FILE", "bank_pointer.json")

BANK_TYPES   = ["人身", "投資型", "外幣"]

def _type_dir(t: str) -> str:
    """根據模式回傳正確的資料夾路徑"""
    if LOCAL_MODE:
        return os.path.join(LOCAL_BANKS_DIR, t)
    return f"{BANKS_DIR}/{t}"

# =========================================================
# GitHub API 基礎函式 (僅在非 Local Mode 時使用)
# =========================================================
def _gh_headers():
    h = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        h["Authorization"] = f"Bearer {GH_TOKEN}"
    return h

def _gh_write_ready() -> tuple[bool, str]:
    if LOCAL_MODE:
        return False, "本機模式不支援 GitHub 寫入"
        
    missing = []
    if not GH_OWNER:  missing.append("REPO_OWNER")
    if not GH_REPO:   missing.append("REPO_NAME")
    if not GH_BRANCH: missing.append("REPO_BRANCH")
    if not GH_TOKEN:  missing.append("GH_TOKEN")
    if missing:
        return False, "缺少 secrets：" + ", ".join(missing)
    return True, ""

def require_gh_write_or_warn():
    ok, msg = _gh_write_ready()
    if not ok:
        if not LOCAL_MODE: # 本機模式下不跳警告，直接靜默失敗即可
            st.warning("GitHub 寫入未啟用——" + msg)
    return ok

def _gh_api(path, method="GET", **kwargs):
    if LOCAL_MODE:
        return {} # 本機模式下不應呼叫此函式，回傳空字典防呆
        
    url = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/{path}"
    r = requests.request(method, url, headers=_gh_headers(), **kwargs)
    if r.status_code >= 400:
        snippet = r.text[:300].replace("\n"," ")
        raise RuntimeError(f"GitHub API {method} {path} -> {r.status_code}: {snippet}")
    return r.json()

def _gh_get_sha(path):
    if LOCAL_MODE: return None
    try:
        j = _gh_api(f"contents/{path}", params={"ref": GH_BRANCH})
        return j.get("sha")
    except Exception:
        return None

# =========================================================
# 核心功能：下載與寫入 (支援雙模式)
# =========================================================

def gh_put_file(path, content_bytes, message):
    """上傳檔案 (本機模式下會被停用)"""
    if LOCAL_MODE:
        st.toast("本機模式下無法上傳檔案到 GitHub")
        return {}
        
    b64 = base64.b64encode(content_bytes).decode("ascii")
    payload = {"message": message, "content": b64, "branch": GH_BRANCH}
    sha = _gh_get_sha(path)
    if sha:
        payload["sha"] = sha
    return _gh_api(f"contents/{path}", method="PUT", json=payload)

@st.cache_data(ttl=300)
def gh_download_bytes(path):
    """
    通用下載函式：自動判斷是從本機讀取還是從 GitHub 下載
    """
    # --- 本機模式 ---
    if LOCAL_MODE:
        try:
            # 確保路徑格式正確 (處理 Windows/Mac 斜線差異)
            safe_path = path.replace("/", os.sep)
            
            # 檢查檔案是否存在
            if not os.path.exists(safe_path):
                # 嘗試加上 LOCAL_BANKS_DIR 前綴再找一次 (容錯處理)
                if not safe_path.startswith(LOCAL_BANKS_DIR):
                     safe_path = os.path.join(LOCAL_BANKS_DIR, safe_path)
            
            with open(safe_path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            st.error(f"[Local] 找不到檔案：{path}")
            return b""
        except Exception as e:
            st.error(f"[Local] 讀取錯誤：{e}")
            return b""

    # --- GitHub 模式 ---
    try:
        j = _gh_api(f"contents/{path}", params={"ref": GH_BRANCH})
        if j.get("encoding") == "base64":
            return base64.b64decode(j["content"])
        
        # 如果不是 API 回傳內容，嘗試用 raw url 下載 (大檔處理)
        raw_url = f"https://raw.githubusercontent.com/{GH_OWNER}/{GH_REPO}/{GH_BRANCH}/{path}"
        h = {"Authorization": f"Bearer {GH_TOKEN}"} if GH_TOKEN else {}
        return requests.get(raw_url, headers=h).content
    except Exception:
        return b""

def list_bank_files(bank_type: str | None = None):
    """
    列出題庫檔案 (支援本機掃描與 GitHub API)
    """
    # --- 本機模式 ---
    if LOCAL_MODE:
        files = []
        try:
            # 決定要掃描的目標資料夾
            target_dir = _type_dir(bank_type) if bank_type else LOCAL_BANKS_DIR
            
            if not os.path.exists(target_dir):
                return []

            for f in os.listdir(target_dir):
                # 只抓取 .xlsx 且排除暫存檔
                if f.lower().endswith(".xlsx") and not f.startswith("~$"):
                    # 組合出相對路徑 (例如: bank/人身/test.xlsx)
                    full_path = os.path.join(target_dir, f)
                    # 統一將分隔符號轉為 '/' (讓後續處理跟 GitHub 路徑一致)
                    files.append(full_path.replace("\\", "/"))
            return sorted(files)
        except Exception as e:
            st.error(f"本機目錄掃描失敗: {e}")
            return []

    # --- GitHub 模式 ---
    try:
        if bank_type:
            folder = _type_dir(bank_type)
            items = _gh_api(f"contents/{folder}", params={"ref": GH_BRANCH})
            return [it["path"] for it in items if it["type"] == "file" and it["name"].lower().endswith(".xlsx")]
        else:
            items = _gh_api(f"contents/{BANKS_DIR}", params={"ref": GH_BRANCH})
            return [it["path"] for it in items if it["type"] == "file" and it["name"].lower().endswith(".xlsx")]
    except Exception:
        return []

# =========================================================
# 指標檔 (Pointer) 處理
# =========================================================
# 本機模式下，我們略過複雜的指標檔同步，因為通常是單人測試

def _read_pointer():
    if LOCAL_MODE: return {}
    try:
        data = gh_download_bytes(POINTER_FILE)
        return json.loads(data.decode("utf-8"))
    except Exception:
        return {}

def _write_pointer(obj: dict):
    if LOCAL_MODE or not require_gh_write_or_warn():
        return
    gh_put_file(
        POINTER_FILE,
        json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
        "update bank pointers"
    )
    gh_download_bytes.clear()

def get_current_bank_path(bank_type: str | None = None):
    """取得目前預設使用的題庫路徑"""
    if LOCAL_MODE:
        # 本機模式下，不做「預設題庫」的記憶功能，直接回傳 None
        # 使用者需在介面上手動選擇題庫
        return None

    conf = _read_pointer()
    current = conf.get("current")
    if isinstance(current, dict):
        if bank_type:
            p = current.get(bank_type)
            if p: return p
    legacy = conf.get("path")
    if legacy and not bank_type:
        return legacy
    return st.secrets.get("BANK_FILE", f"{BANKS_DIR}/exam_bank.xlsx")

def set_current_bank_path(bank_type: str, path: str):
    """更新目前預設題庫"""
    if LOCAL_MODE:
        # 本機模式不寫入
        return

    if not require_gh_write_or_warn():
        return
    if not path.startswith(f"{BANKS_DIR}/"):
        path = f"{_type_dir(bank_type)}/{path}"
    conf = _read_pointer()
    if "current" not in conf or not isinstance(conf.get("current"), dict):
        conf["current"] = {}
    conf["current"][bank_type] = path
    try:
        _write_pointer(conf)
    except Exception as e:
        st.warning(f"更新 {POINTER_FILE} 失敗：{e}")

def migrate_pointer_prefix_if_needed():
    if LOCAL_MODE: return
    
    conf = _read_pointer()
    changed = False
    if isinstance(conf.get("path"), str) and conf["path"].startswith("banks/"):
        conf["path"] = conf["path"].replace("banks/", f"{BANKS_DIR}/", 1)
        changed = True
    cur = conf.get("current")
    if isinstance(cur, dict):
        for k, p in list(cur.items()):
            if isinstance(p, str) and p.startswith("banks/"):
                cur[k] = p.replace("banks/", f"{BANKS_DIR}/", 1)
                changed = True
    if changed:
        try:
            _write_pointer(conf)
        except Exception as e:
            st.warning(f"自動遷移 {POINTER_FILE} 失敗：{e}")