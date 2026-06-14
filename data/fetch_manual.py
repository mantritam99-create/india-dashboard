"""Manual monthly inputs -- the RBI / AMFI / NSE / MoSPI series with no clean free API.

Pure I/O: reads data/manual_inputs.csv and returns {indicator_key: dated Series}.
ALL scoring (anchor vs percentile, staleness) lives in model/normalize.py, so there
is exactly one place that turns a number into a stress score.

CSV schema:  date,indicator,value,note
  date       ISO date of the reading (month-end is fine)
  indicator  the key from config.yaml `indicators` (e.g. fii_3m)
  value      the raw reading
  note       free text (source / context)

Add one new dated row per indicator each month. History accumulates and each manual
indicator auto-graduates from anchor- to percentile-scoring once it has
`normalize.anchor_switch_n` readings.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from config import ROOT

CSV = os.path.join(ROOT, "data", "manual_inputs.csv")


def load_series() -> dict:
    """{indicator_key: pd.Series(value, index=date)} -- newest-last, NaNs dropped."""
    if not os.path.exists(CSV):
        return {}
    df = pd.read_csv(CSV, parse_dates=["date"])
    out = {}
    for ind, g in df.groupby("indicator"):
        g = g.sort_values("date")
        out[str(ind)] = pd.Series(g["value"].to_numpy(), index=pd.DatetimeIndex(g["date"])).dropna()
    return out


if __name__ == "__main__":
    series = load_series()
    if not series:
        print("no manual_inputs.csv yet")
    for k, s in sorted(series.items()):
        print(f"{k:16s} n={len(s):3d}  last={float(s.iloc[-1]):>12.2f} @ {s.index[-1].date()}")
