"""Date-stamped cache. Never hit a data source twice for what we already have.

JSON for scalars/metadata, CSV for time series. Freshness is by file mtime, so a
cached pull older than `max_age_h` hours is treated as stale and refetched.
"""
import os
import json
import time
import pandas as pd
from config import CACHE_DIR


def _path(key: str, ext: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.{ext}")


# ---- JSON (scalars, dicts) ----
def get_json(key: str, max_age_h: float):
    p = _path(key, "json")
    if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < max_age_h * 3600:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def put_json(key: str, obj):
    with open(_path(key, "json"), "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return obj


# ---- time series (pandas Series, date-indexed) ----
def get_series(key: str, max_age_h: float):
    p = _path(key, "csv")
    if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < max_age_h * 3600:
        return pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0]
    return None


def put_series(key: str, s: pd.Series):
    s.to_frame(name="value").to_csv(_path(key, "csv"))
    return s
