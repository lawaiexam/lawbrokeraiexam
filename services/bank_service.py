from io import BytesIO
import pandas as pd
from utils import github_handler as gh
from utils import data_loader as dl

def load_bank_df(bank_type: str, merge_all: bool, bank_source_path: str | None) -> pd.DataFrame | None:
    """
    - merge_all=True：合併該類型下所有題庫
    - merge_all=False：載入 bank_source_path 指定的題庫
    """
    if merge_all:
        paths = gh.list_bank_files(bank_type)
        if not paths:
            return None
        return dl.load_banks_from_github(paths)

    if not bank_source_path:
        return None

    data = gh.gh_download_bytes(bank_source_path)
    if not data:
        return None

    bio = BytesIO(data)
    try:
        bio.name = bank_source_path
    except Exception:
        pass
    return dl.load_bank(bio)


def get_all_tags(df) -> list[str]:
    if df is None or df.empty or "Tag" not in df.columns:
        return []
    tags = set()
    for s in df["Tag"].dropna().astype(str):
        for t in s.split(";"):
            t = t.strip()
            if t:
                tags.add(t)
    return sorted(tags)


def filter_by_tags(df, picked_tags: list[str]):
    if df is None or df.empty or not picked_tags or "Tag" not in df.columns:
        return df
    picked = set(t.strip() for t in picked_tags if t.strip())
    if not picked:
        return df

    def _match(s: str) -> bool:
        parts = [x.strip() for x in str(s).split(";")]
        return any(t in parts for t in picked)

    mask = df["Tag"].astype(str).apply(_match)
    return df[mask].copy()
