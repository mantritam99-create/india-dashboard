"""V2 decision-support analytics layered on top of the live composite.

Everything HISTORICAL here is computed from the market-core series (external/currency
+ sentiment/froth) -- the only buckets with back-history, the same honest scope as the
backtest. So the trajectory, forward-returns, analogs and probabilities describe the
*market-driven core*, not the full 5-bucket composite. Labelled as such in the UI.

Live framings (distance-to-trip, three-stress lenses, regime, interpretation) use the
full 5-bucket live read.
"""
import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from config import CFG
from model import normalize, scoring
from data import fetch_market

MARKET_KEYS = ["usdinr_12m", "brent_inr", "india_vix", "smallcap_ratio"]
STRESS_BANDS = [
    ("GFC 2008", "2008-09", "2009-03"),
    ("Taper 2013", "2013-05", "2013-12"),
    ("NBFC 2018", "2018-08", "2019-02"),
    ("COVID 2020", "2020-02", "2020-05"),
]

_CACHE = {}


def _sweep():
    """Monthly market-core composite_asof from 2008 -> today (memoised per process)."""
    if "sweep" not in _CACHE:
        loaded = normalize.market_loaded()
        dates = pd.date_range("2008-01-01", pd.Timestamp.today().normalize(), freq="MS")
        _CACHE["sweep"] = (loaded, {d: scoring.composite_asof(loaded, d) for d in dates})
    return _CACHE["sweep"]


def _asof_price(series, when):
    s = series[series.index <= when].dropna()
    return float(s.iloc[-1]) if len(s) else None


# ===========================================================================
#  COMPOSITE TRAJECTORY  (market-core, ~15y) + stress bands + threshold lines
# ===========================================================================
def trajectory():
    _, sweep = _sweep()
    pts = [{"d": d.strftime("%Y-%m"), "v": round(s["composite"], 1)}
           for d, s in sweep.items() if s["composite"] is not None]
    return {"points": pts,
            "bands": [{"label": l, "start": a, "end": b} for l, a, b in STRESS_BANDS],
            "thresholds": CFG["bands"]["composite"]}


# ===========================================================================
#  DISTANCE-TO-TRIP gauges  (highest-ROI item)
# ===========================================================================
def distance_to_trip(values):
    out = []
    for tw in CFG["tripwires"]:
        cur = values.get(tw.get("raw") or tw["indicator"])
        floor, level = tw.get("floor"), tw["level"]
        fill = None
        if cur is not None and floor is not None and level != floor:
            fill = max(0.0, min(1.25, (cur - floor) / (level - floor)))
        out.append({
            "name": tw["name"], "current": cur, "floor": floor, "level": level,
            "unit": tw.get("unit", ""), "trips_when": tw["trips_when"], "note": tw["note"],
            "fill": round(fill, 3) if fill is not None else None,
            "tripped": bool(fill is not None and fill >= 1.0),
        })
    return out


# ===========================================================================
#  FORWARD RETURNS  (composite band -> avg fwd 12m Nifty) + drawdown frequency
# ===========================================================================
def forward_returns():
    _, sweep = _sweep()
    nifty = fetch_market.history("^NSEI")
    if nifty is None:
        return []
    nifty = nifty.dropna().sort_index()
    edges = [(0, 30), (30, 50), (50, 70), (70, 999)]
    buckets = {e: [] for e in edges}
    for d, s in sweep.items():
        comp = s["composite"]
        if comp is None:
            continue
        fwd = d + pd.DateOffset(months=12)
        if fwd > nifty.index[-1]:
            continue
        p0, p1 = _asof_price(nifty, d), _asof_price(nifty, fwd)
        if not p0 or not p1:
            continue
        ret = (p1 / p0 - 1) * 100
        for e in edges:
            if e[0] <= comp < e[1]:
                buckets[e].append(ret)
                break
    out = []
    for (lo, hi), rets in buckets.items():
        if not rets:
            continue
        out.append({
            "band": f"{lo}-{hi if hi < 999 else '+'}", "n": len(rets),
            "avg_fwd_12m": round(sum(rets) / len(rets), 1),
            "worst": round(min(rets), 1), "best": round(max(rets), 1),
            "p_down20": round(sum(1 for r in rets if r < -20) / len(rets) * 100),
        })
    return out


# ===========================================================================
#  HISTORICAL ANALOGS  (similarity on the 4-dim market stress vector)
# ===========================================================================
def _vec_asof(loaded, d):
    v = {}
    for spec, s in loaded:
        _, score = normalize.score_asof(spec, s, d)
        if score is not None:
            v[spec["key"]] = score
    return v


def analogs(current_rows):
    loaded, sweep = _sweep()
    cur = {r["key"]: r["score"] for r in current_rows if r["key"] in MARKET_KEYS and r["ok"]}
    keys = [k for k in MARKET_KEYS if k in cur]
    if len(keys) < 3:
        return []
    best_by_year = {}
    for d in sweep:
        if d.year >= pd.Timestamp.today().year:
            continue
        v = _vec_asof(loaded, d)
        if not all(k in v for k in keys):
            continue
        dist = math.sqrt(sum((cur[k] - v[k]) ** 2 for k in keys)) / (100 * math.sqrt(len(keys)))
        sim = round((1 - dist) * 100)
        if sim > best_by_year.get(d.year, (None, -1))[1]:
            best_by_year[d.year] = (d.strftime("%Y-%m"), sim)
    ranked = sorted(best_by_year.values(), key=lambda x: -x[1])[:4]
    return [{"period": p, "similarity": s} for p, s in ranked]


# ===========================================================================
#  REGIME  (transparent rule-based label)
# ===========================================================================
def regime(c, traj, st):
    R = next(x["score"] for x in st if x["key"] == "recession")
    Cr = next(x["score"] for x in st if x["key"] == "credit")
    B = next(x["score"] for x in st if x["key"] == "bubble")
    comp = c["composite"]
    pts = traj["points"]
    slope = round(pts[-1]["v"] - pts[-4]["v"], 1) if len(pts) >= 4 else 0.0
    if R >= 60:
        lab, why = "Recession-risk", "growth & demand stress is acute"
    elif Cr >= 72:
        lab, why = "Credit / currency stress", "external/currency stress is acute"
    elif B >= 50 and R < 42:
        lab, why = "Late-cycle / asset-froth", "valuations & froth elevated while growth stays resilient"
    elif comp < 32 and slope <= 1 and B < 45:
        lab, why = "Expansion", "broad stress low and not rising"
    elif slope < -5:
        lab, why = "Recovery", "stress easing from a higher level"
    else:
        lab, why = "Late-cycle", "mixed late-cycle signals"
    return {"label": lab, "why": why, "slope_3m": slope}


# ===========================================================================
#  THREE STRESS TYPES  (India framing: not just "recession")
# ===========================================================================
def stress_types(c):
    b = c["bucket"]
    g = lambda k: b.get(k) or 0
    return [
        {"key": "recession", "label": "Recession risk",
         "score": round(g("macro_stress") * 0.7 + g("domestic_flows") * 0.3),
         "desc": "growth & demand — IIP, GST, yields, credit"},
        {"key": "credit", "label": "Credit / currency stress",
         "score": round(g("external_currency") * 0.7 + g("macro_stress") * 0.3),
         "desc": "rupee, FII flows, reserves, oil, bonds"},
        {"key": "bubble", "label": "Asset-bubble stress",
         "score": round(g("valuation") * 0.45 + g("sentiment_froth") * 0.35 + g("domestic_flows") * 0.20),
         "desc": "valuations, froth, retail leverage"},
    ]


# ===========================================================================
#  HERO INTERPRETATION  (top-line read) + indicative probabilities
# ===========================================================================
def _band_word(s):
    return "low" if s < 35 else "moderate" if s < 55 else "elevated" if s < 70 else "high"


def interpretation(c, st, tripped):
    top = max(st, key=lambda x: x["score"])
    rec = next(x for x in st if x["key"] == "recession")
    label = {"recession": "recession", "credit": "credit/currency", "bubble": "asset-valuation"}[top["key"]]
    lead = (f"India's dominant risk right now is {label} stress "
            f"({_band_word(top['score'])}, {top['score']}/100), "
            f"while recession risk stays {_band_word(rec['score'])} ({rec['score']}/100).")
    if top["key"] == "bubble" and rec["score"] < 40:
        lead += " This is a froth setup, not a recession setup — valuation risk ≠ recession risk."
    tail = (" No acute trip-wires are firing." if tripped == 0
            else f" {tripped} acute trip-wire(s) firing — watch closely.")
    return lead + tail


def probabilities(fwd):
    """Indicative 12m odds anchored to the historical fwd-return distribution for the
    current composite band. Clearly heuristic — NOT a forecast."""
    if not fwd:
        return []
    # find the band the live market-core composite sits in
    _, sweep = _sweep()
    live = [s["composite"] for d, s in sweep.items() if s["composite"] is not None]
    cur = live[-1] if live else None
    band = next((f for f in fwd if cur is not None and _in_band(cur, f["band"])), fwd[0])
    soft = max(0, min(100, round(100 - band["p_down20"] - 15)))
    return [
        {"label": "Sharp drawdown >20% (12m)", "pct": band["p_down20"],
         "note": f"empirical, composite {band['band']} band, n={band['n']}"},
        {"label": "Positive 12m index return", "pct": soft,
         "note": "complement of large-drawdown frequency"},
        {"label": "Avg outcome", "pct": None, "note": f"{band['avg_fwd_12m']:+.0f}% mean fwd 12m"},
    ]


def _in_band(v, band):
    lo = float(band.split("-")[0])
    hi = 999 if band.endswith("+") else float(band.split("-")[1])
    return lo <= v < hi


def sparklines(months=24):
    """Recent point-in-time stress-score history per MARKET indicator (for table sparklines).
    Manual indicators have no back-history yet, so they get none."""
    loaded, _ = _sweep()
    dates = pd.date_range(pd.Timestamp.today().normalize().replace(day=1) - pd.DateOffset(months=months - 1),
                          periods=months, freq="MS")
    out = {}
    for spec, s in loaded:
        seq = [(lambda sc: round(sc, 1) if sc is not None else None)(normalize.score_asof(spec, s, d)[1])
               for d in dates]
        out[spec["key"]] = seq
    return out


def compute_all(rows, c, values):
    traj = trajectory()
    fwd = forward_returns()
    st = stress_types(c)
    tripped = sum(1 for t in distance_to_trip(values) if t["tripped"])
    return {
        "trajectory": traj,
        "distance_to_trip": distance_to_trip(values),
        "forward_returns": fwd,
        "fwd_note": ("Market-core stress is CONTRARIAN at extremes in India: the 70+ readings are "
                     "the 2008/2013 capitulation lows, which preceded rebounds — high composite is "
                     "NOT a sell signal here. The asset-bubble lens (valuations/froth), not the "
                     "composite, is the 'expensive' warning."),
        "analogs": analogs(rows),
        "regime": regime(c, traj, st),
        "stress_types": st,
        "interpretation": interpretation(c, st, tripped),
        "probabilities": probabilities(fwd),
        "sparklines": sparklines(),
    }


if __name__ == "__main__":
    rows = normalize.compute()
    c = scoring.composite(rows)
    vals = {r["key"]: r.get("current") for r in rows}
    vals["usdinr_raw"] = fetch_market.latest("INR=X")
    vals["brent_usd"] = fetch_market.latest("BZ=F")
    a = compute_all(rows, c, vals)
    import json
    print(json.dumps({k: a[k] for k in ["regime", "stress_types", "interpretation",
                                         "forward_returns", "analogs", "probabilities"]},
                     indent=2, default=str))
    print("trajectory points:", len(a["trajectory"]["points"]))
    print("distance-to-trip:", [(d["name"], d["fill"]) for d in a["distance_to_trip"]])
