"""5-bucket weighted composite + breadth adjustment + verdict (posture & action).

THE TWO-SIGNAL HIERARCHY (spec section 4, do not collapse to one number):
  * COMPOSITE = POSTURE  -- how defensive to sit. Weighted mean of bucket stress,
    renormalized over buckets with data, then DISCOUNTED by breadth so a score
    driven by one screaming indicator can't masquerade as broad stress.
  * TRIP-WIRES = ACTION   -- specific watchable lines that, when crossed, say "move".

composite_raw = sum(bucket_mean * weight) / sum(weights present)
breadth       = share of live indicators in the danger zone (>75)
composite     = composite_raw * (floor + (1-floor)*breadth)      <- the posture number
margin (+/-)  = base + staleness + missing-bucket + coverage + dispersion penalties
                (manual-heavy data => staleness weighs more than the US version)
"""
import os
import sys
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CFG, WEIGHTS, BUCKETS, indicators as cfg_indicators
from model import normalize

DZ = CFG["breadth"]["danger_zone"]
FLOOR = CFG["breadth"]["floor"]
CONF = CFG["confidence"]


# ===========================================================================
#  LIVE COMPOSITE
# ===========================================================================
def composite(rows=None) -> dict:
    rows = normalize.compute() if rows is None else rows
    ok = [r for r in rows if r["ok"]]

    bucket = {}
    for b in BUCKETS:
        vals = [r["score"] for r in ok if r["bucket"] == b]
        bucket[b] = sum(vals) / len(vals) if vals else None

    avail = {b: w for b, w in WEIGHTS.items() if bucket[b] is not None}
    wsum = sum(avail.values()) or 1.0
    comp_raw = sum(bucket[b] * w / wsum for b, w in avail.items()) if avail else 0.0

    breadth = (sum(1 for r in ok if r["score"] >= DZ) / len(ok)) if ok else 0.0
    comp = comp_raw * (FLOOR + (1.0 - FLOOR) * breadth)

    # ---- confidence margin ----
    missing = [b for b in BUCKETS if bucket[b] is None]
    coverage = len(ok) / len(rows) if rows else 0.0
    stale_days_over = sum(max(0, (r.get("age_days") or 0) - CFG["normalize"]["stale_days"])
                          for r in ok if r.get("stale"))
    bvals = [v for v in bucket.values() if v is not None]
    dispersion = (statistics.pstdev(bvals) / 50.0) if len(bvals) > 1 else 0.0
    margin = (CONF["base"]
              + min(CONF["stale_per_day"] * stale_days_over, 15)
              + CONF["missing_bucket_penalty"] * len(missing)
              + CONF["coverage_penalty"] * (1 - coverage)
              + CONF["dispersion_penalty"] * dispersion)
    margin = round(min(margin, 40), 1)

    return {
        "bucket": {b: (round(v, 1) if v is not None else None) for b, v in bucket.items()},
        "weights_used": {b: round(w / wsum, 2) for b, w in avail.items()},
        "composite_raw": round(comp_raw, 1),
        "composite": round(comp, 1),
        "breadth": round(breadth, 2),
        "margin": margin,
        "coverage": round(coverage, 2),
        "n_live": len(ok), "n_total": len(rows),
        "danger": [r["name"] for r in ok if r["score"] >= DZ],
        "missing_buckets": missing,
        "stale": [r["name"] for r in ok if r.get("stale")],
    }


# ===========================================================================
#  AS-OF COMPOSITE  (market series only -> backtest/trend; no lookahead)
# ===========================================================================
def composite_asof(loaded, asof) -> dict:
    per = {b: [] for b in BUCKETS}
    n_live = n_danger = 0
    for spec, s in loaded:
        if spec["bucket"] not in BUCKETS:
            continue
        _, score = normalize.score_asof(spec, s, asof)
        if score is None:
            continue
        per[spec["bucket"]].append(score)
        n_live += 1
        n_danger += score >= DZ
    bucket = {b: (sum(v) / len(v) if v else None) for b, v in per.items()}
    avail = {b: w for b, w in WEIGHTS.items() if bucket[b] is not None}
    wsum = sum(avail.values()) or 1.0
    comp_raw = sum(bucket[b] * w / wsum for b, w in avail.items()) if avail else None
    breadth = (n_danger / n_live) if n_live else 0.0
    comp = comp_raw * (FLOOR + (1.0 - FLOOR) * breadth) if comp_raw is not None else None
    return {"composite_raw": comp_raw, "composite": comp, "breadth": breadth,
            "bucket": bucket, "n_live": n_live}


# ===========================================================================
#  VERDICT  (posture stance + trip-wire action checklist + bull-case defeaters)
# ===========================================================================
def stance(comp, breadth, tripped, bands):
    if comp < bands["benign"]:
        return "NO CRISIS SIGNAL", "Thesis NOT supported by current data."
    if comp < bands["watch"]:
        return "LATE-CYCLE WATCH", "Early caution; signal building but not elevated."
    if comp < bands["warning"]:
        return "ELEVATED", "Late-cycle risk rising; still below the warning line."
    if comp >= bands["acute"] or tripped >= 3:
        return "ACUTE / BROAD STRESS", "Thesis STRONGLY supported and broad-based."
    if breadth >= 0.5 or tripped >= 2:
        return "ELEVATED - BROADENING", "Thesis SUPPORTED and starting to confirm."
    return "ELEVATED - NOT IMMINENT", "Thesis SUPPORTED, but concentrated, not yet acute."


def tripwires(values):
    """values: {key_or_raw_name: current_value}. Returns [(tripped|None, tw, value)]."""
    out = []
    for tw in CFG["tripwires"]:
        key = tw.get("raw") or tw["indicator"]
        val = values.get(key)
        if val is None:
            out.append((None, tw, None))
            continue
        trip = val <= tw["level"] if tw["trips_when"] == "below" else val >= tw["level"]
        out.append((bool(trip), tw, val))
    return out


def defeaters(rows, limit=6):
    """Lowest-stress live indicators -- what's working AGAINST the bearish thesis."""
    calm = [r for r in rows if r["ok"] and r["score"] < 35]
    return sorted(calm, key=lambda r: r["score"])[:limit]


def assess(rows, c, values) -> dict:
    tw = tripwires(values)
    tripped = sum(1 for t, _, _ in tw if t)
    label, why = stance(c["composite"], c["breadth"], tripped, CFG["bands"]["composite"])
    return {"label": label, "stance": why, "tripwires": tw, "tripped": tripped,
            "defeaters": defeaters(rows)}


if __name__ == "__main__":
    rows = normalize.compute()
    c = composite(rows)
    print(f"composite(posture)={c['composite']}  raw={c['composite_raw']}  "
          f"breadth={c['breadth']}  +/-{c['margin']}  coverage={c['coverage']}")
    print("buckets:", c["bucket"])
    print("weights used:", c["weights_used"])
    print("danger zone:", ", ".join(c["danger"]) or "none")
    if c["missing_buckets"]:
        print("missing buckets:", c["missing_buckets"])
