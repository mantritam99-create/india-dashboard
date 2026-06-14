"""Market data via Yahoo's chart endpoint directly (keyless, ~0.4s), with a
stooq.com CSV fallback.

We hit query1.finance.yahoo.com instead of the yfinance wrapper: it's the exact
same data source yfinance uses, minus a fragile dependency. Cached per ticker.
If Yahoo is unreachable we try stooq, then fall back to the last cached pull
(any age) -- so an offline build degrades rather than crashes.
"""
import os
import sys
import io
import json
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import cache_util as cache
from config import CFG

_HDR = {"User-Agent": "Mozilla/5.0"}
_MAX = CFG["cache"]["market_max_age_h"]

# Yahoo ticker -> stooq symbol (fallback only). Best-effort; not every ticker maps.
_STOOQ = {
    "^NSEI": "^nsei",
    "^NSEBANK": "^nsebank",
    "^INDIAVIX": "^indiavix",
    "^CNXSC": "^cnxsc",
    "INR=X": "usdinr",
    "BZ=F": "cb.f",       # Brent continuous
}


def _get(url: str):
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def _from_yahoo(ticker: str, range_: str, interval: str) -> pd.Series:
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(ticker)}?range={range_}&interval={interval}")
    d = json.loads(_get(url))
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    s = pd.Series(closes, index=pd.to_datetime(ts, unit="s")).dropna()
    s.index = s.index.normalize()
    return s


def _from_stooq(ticker: str) -> pd.Series | None:
    sym = _STOOQ.get(ticker)
    if not sym:
        return None
    url = f"https://stooq.com/q/d/l/?s={urllib.parse.quote(sym)}&i=d"
    txt = _get(url)
    if "Date,Open" not in txt:
        return None
    df = pd.read_csv(io.StringIO(txt), parse_dates=["Date"])
    return pd.Series(df["Close"].values, index=df["Date"]).dropna()


def history(ticker: str, range_: str = "max", interval: str = "1d") -> pd.Series | None:
    """Date-indexed close-price series. Cached; Yahoo -> stooq -> stale cache."""
    key = f"mkt_{ticker}_{range_}_{interval}"
    s = cache.get_series(key, _MAX)
    if s is not None:
        return s
    for src, fn in (("yahoo", lambda: _from_yahoo(ticker, range_, interval)),
                    ("stooq", lambda: _from_stooq(ticker))):
        try:
            s = fn()
            if s is not None and len(s):
                return cache.put_series(key, s)
        except Exception as e:
            print(f"  [market] {ticker} via {src} failed ({e.__class__.__name__}: {e})")
    stale = cache.get_series(key, 1e9)  # any age
    print(f"  [market] {ticker} -> {'using stale cache' if stale is not None else 'NO DATA'}")
    return stale


def latest(ticker: str) -> float | None:
    s = history(ticker)
    return float(s.iloc[-1]) if s is not None and len(s) else None


if __name__ == "__main__":
    for t in ["^NSEI", "^NSEBANK", "^INDIAVIX", "INR=X", "BZ=F", "^CNXSC"]:
        s = history(t)
        if s is not None and len(s):
            print(f"{t:11s} last={float(s.iloc[-1]):>12.2f}  n={len(s):>5d}  "
                  f"{s.index[0].date()} -> {s.index[-1].date()}")
        else:
            print(f"{t:11s} NO DATA")
