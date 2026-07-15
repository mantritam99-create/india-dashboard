"""Raw values -> a 0-100 stress score per indicator, plus the directionality audit.

Two scoring methods (the spec's anchor->percentile design):
  * PERCENTILE  -- % of an indicator's OWN history below the current reading,
                   flipped if `direction == low`. Used for market series and for
                   manual series once they have >= anchor_switch_n readings.
  * ANCHOR      -- linear map calm->0, stress->100 (clamped). Used for manual
                   indicators with too little history yet, for India VIX (where a
                   pure percentile would mislabel calm-but-low as low-stress), and
                   for derived indicators. As manual history accumulates past the
                   switch point, that indicator graduates to percentile.

`direction` is the single source of truth for inversion. The audit() asserts every
anchor's calm/stress ORDERING agrees with it -- one flipped sign silently corrupts
the whole composite, so we check on every build.
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from config import CFG, indicators as cfg_indicators
from data import fetch_market, fetch_manual

NORM = CFG["normalize"]
MIN_HIST = NORM["min_hist"]
SWITCH_N = NORM["anchor_switch_n"]
STALE_DAYS = NORM["stale_days"]


# ===========================================================================
#  PRIMITIVES
# ===========================================================================
def percentile_score(current, history, direction="high"):
    """% of historical readings below `current`, flipped if low values are stressful."""
    if current is None:
        return None
    h = pd.Series(history).dropna()
    if len(h) < MIN_HIST:
        return None
    pct = float((h < current).mean() * 100.0)
    return pct if direction == "high" else 100.0 - pct


def percentile_asof(series, asof, direction="high"):
    """Point-in-time percentile vs ONLY prior history (no lookahead). For the backtest."""
    if series is None:
        return None, None
    s = series[series.index <= asof].dropna()
    if len(s) < MIN_HIST:
        return None, None
    cur = float(s.iloc[-1])
    pct = float((s < cur).mean() * 100.0)
    return cur, (pct if direction == "high" else 100.0 - pct)


def anchor_score(value, calm, stress):
    """Linear map: value at `calm` -> 0, at `stress` -> 100, clamped to [0,100].
    Handles either ordering because calm/stress may run low->high or high->low."""
    if value is None or stress == calm:
        return None
    frac = (value - calm) / (stress - calm)
    return max(0.0, min(1.0, frac)) * 100.0


# ===========================================================================
#  MARKET TRANSFORMS  (compose raw close series into the scored quantity)
# ===========================================================================
def pct12m(series):
    """Trailing 12-month % change. Date-based (robust to monthly/irregular spacing)."""
    if series is None:
        return None
    s = series.dropna().sort_index()
    out = {}
    for d, v in s.items():
        prior = s[s.index <= d - pd.Timedelta(days=350)]
        if len(prior) and prior.iloc[-1]:
            out[d] = (v / prior.iloc[-1] - 1.0) * 100.0
    return pd.Series(out)


def _aligned(t1, t2):
    a, b = fetch_market.history(t1), fetch_market.history(t2)
    if a is None or b is None:
        return None
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1, sort=False).sort_index().ffill().dropna()
    return df


def brent_inr_series():
    """Brent (USD) * USD/INR -> Brent in rupees, the figure that actually hits India."""
    df = _aligned("BZ=F", "INR=X")
    return (df["a"] * df["b"]) if df is not None else None


def midcap_ratio_series():
    """Nifty Midcap / Nifty 50 -- broadening into smaller caps = late-cycle froth."""
    df = _aligned("^NSMIDCP", "^NSEI")
    return (df["a"] / df["b"]) if df is not None else None


def market_series(spec):
    """The (possibly transformed) series a market indicator is scored on."""
    t = spec.get("transform")
    if t == "pct12m":
        return pct12m(fetch_market.history(spec["ticker"]))
    if t == "brent_inr":
        return brent_inr_series()
    if t == "midcap_ratio":
        return midcap_ratio_series()
    return fetch_market.history(spec["ticker"])   # raw level (e.g. India VIX)


# ===========================================================================
#  DERIVED  (computed from other indicators' current values, anchor-scored)
# ===========================================================================
def derived_value(formula, base):
    if formula == "ey_minus_gsec":
        pe, gsec = base.get("nifty_pe"), base.get("gsec_10y")
        if pe and gsec and pe > 0:
            return (100.0 / pe) - gsec        # earnings yield (%) minus bond yield (%)
    elif formula == "gsec_minus_repo":
        gsec, repo = base.get("gsec_10y"), CFG["derived_inputs"]["repo_rate"]
        if gsec is not None:
            return gsec - repo
    return None


# ===========================================================================
#  LIVE COMPUTE  -> one row per indicator
# ===========================================================================
def _meta(spec):
    return {"key": spec["key"], "name": spec["name"], "bucket": spec["bucket"],
            "direction": spec["direction"], "source": spec["source"]}


def _score_market(spec):
    s = market_series(spec)
    if s is None or not len(s.dropna()):
        return {"current": None, "score": None, "n": 0, "method": spec.get("method", "percentile"),
                "stale": False, "date": None, "series": s}
    s = s.dropna()
    cur = float(s.iloc[-1])
    date = s.index[-1].date()
    if spec.get("method") == "anchor":
        return {"current": cur, "score": anchor_score(cur, spec["calm"], spec["stress"]),
                "n": len(s), "method": "anchor", "stale": False, "date": date, "series": s}
    return {"current": cur, "score": percentile_score(cur, s, spec["direction"]),
            "n": len(s), "method": "percentile", "stale": False, "date": date, "series": s}


def _score_manual(spec, series):
    if series is None or not len(series.dropna()):
        return {"current": None, "score": None, "n": 0, "method": "anchor",
                "stale": True, "age_days": None, "date": None, "series": series}
    s = series.dropna().sort_index()
    cur = float(s.iloc[-1])
    age = (pd.Timestamp(datetime.date.today()) - s.index[-1]).days
    if len(s) >= SWITCH_N:
        score, method = percentile_score(cur, s, spec["direction"]), "percentile"
    else:
        score, method = anchor_score(cur, spec["calm"], spec["stress"]), "anchor"
    return {"current": cur, "score": score, "n": len(s), "method": method,
            "stale": age > STALE_DAYS, "age_days": age, "date": s.index[-1].date(), "series": s}


def compute():
    """[{key,name,bucket,direction,source,current,score,n,method,ok,stale,...}, ...]."""
    specs = cfg_indicators()
    manual = fetch_manual.load_series()
    rows = {}
    for k, spec in specs.items():
        if spec["source"] == "market":
            rows[k] = {**_meta(spec), **_score_market(spec)}
        elif spec["source"] == "manual":
            rows[k] = {**_meta(spec), **_score_manual(spec, manual.get(k))}

    base = {k: r.get("current") for k, r in rows.items()}
    for k, spec in specs.items():
        if spec["source"] != "derived":
            continue
        val = derived_value(spec["formula"], base)
        rows[k] = {**_meta(spec), "current": val,
                   "score": anchor_score(val, spec["calm"], spec["stress"]),
                   "n": 1, "method": "derived", "stale": False}

    out = []
    for k, spec in specs.items():
        r = rows.get(k) or {**_meta(spec), "current": None, "score": None, "n": 0,
                            "method": "-", "stale": False}
        r["ok"] = r.get("score") is not None
        if r.get("score") is not None:
            r["score"] = round(r["score"], 1)
        out.append(r)
    return out


# ===========================================================================
#  AS-OF SCORING  (point-in-time, market series only -> the honest backtest)
#  The manual layer has no history yet, so it is excluded here -- exactly like
#  the US dashboard excludes its manual AI-layer from composite_asof. The 2013
#  taper-tantrum test stands on the real USD/INR + Brent-INR signal, not on
#  fabricated historical FII/reserve rows.
# ===========================================================================
def market_loaded():
    """[(spec, transformed_series), ...] for every market-sourced indicator."""
    out = []
    for spec in cfg_indicators().values():
        if spec["source"] == "market":
            out.append((spec, market_series(spec)))
    return out


def score_asof(spec, series, asof):
    """(value, stress_score) as-of `asof` for one market series, or (None, None)."""
    if series is None:
        return None, None
    if spec.get("method") == "anchor":
        s = series[series.index <= asof].dropna()
        if not len(s):
            return None, None
        v = float(s.iloc[-1])
        return v, anchor_score(v, spec["calm"], spec["stress"])
    return percentile_asof(series, asof, spec["direction"])


# ===========================================================================
#  DIRECTIONALITY AUDIT  (print every build; the spec calls this non-negotiable)
# ===========================================================================
def audit(rows=None):
    """Print value / score / invert flag / method per indicator and FLAG any anchor
    whose calm/stress ordering disagrees with `direction`. Returns list of problems."""
    rows = compute() if rows is None else rows
    specs = cfg_indicators()
    problems = []

    print("=" * 86)
    print("  DIRECTIONALITY AUDIT  -  one flipped sign silently corrupts the composite")
    print("=" * 86)
    print(f"  {'indicator':32s} {'value':>11s} {'stress':>7s}  {'stress-when':10s} {'method':10s}")
    print("  " + "-" * 82)
    for r in rows:
        spec = specs[r["key"]]
        stress_when = "HIGH" if spec["direction"] == "high" else "LOW"
        # ordering sanity for anchor-scored indicators
        if "calm" in spec and "stress" in spec:
            want_high = spec["direction"] == "high"
            if (spec["stress"] > spec["calm"]) != want_high:
                problems.append(f"{r['name']}: calm/stress ordering disagrees with direction={spec['direction']}")
        cur = f"{r['current']:,.2f}" if r.get("current") is not None else "n/a"
        sc = f"{r['score']:5.1f}" if r["ok"] else "  -- "
        flag = "  <<< CHECK" if r["key"] in str(problems) else ""
        print(f"  {r['name']:32s} {cur:>11s} {sc:>7s}  stress={stress_when:5s} {r['method']:10s}{flag}")

    print("  " + "-" * 82)
    # Spot-check the four signs the spec calls out by name.
    checks = [
        ("usdinr_12m",     "rupee weakening (USD/INR 12m up)", "high"),
        ("fx_reserves_8w", "FX reserves falling",              "low"),
        ("fii_3m",         "FII outflows (negative)",          "low"),
        ("sip_inflows",    "SIP inflows falling",              "low"),
    ]
    print("  EXPECTED SIGNS (manually verify these read as MORE stress):")
    for key, phrase, want in checks:
        got = specs[key]["direction"]
        ok = "OK " if got == want else "BAD"
        print(f"    [{ok}] {phrase:38s} -> direction={got}")
    if problems:
        print("\n  !! PROBLEMS:")
        for p in problems:
            print("     - " + p)
    else:
        print("\n  No ordering problems detected.")
    print("=" * 86)
    return problems


if __name__ == "__main__":
    audit()
