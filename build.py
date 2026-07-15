"""Orchestrator. Runs on a schedule (GitHub Actions), fetches + scores everything,
runs the directionality audit, writes output/data.json (the ONLY thing index.html
reads), and appends a line to log.md.

Pipeline:
  fetch (market + manual) -> normalize (percentile/anchor) -> AUDIT -> composite
  -> verdict (posture stance + trip-wire action + bull-case defeaters) -> data.json
"""
import os
import sys
import re
import json
import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                       # Windows console is cp1252; our strings use — and ≠ (UTF-8 in data)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import pandas as pd
from config import CFG, ROOT, WEIGHTS, BUCKETS, indicators as cfg_indicators
from model import normalize, scoring, analytics
from data import fetch_market

OUT = os.path.join(ROOT, "output", "data.json")
HTML = os.path.join(ROOT, "output", "index.html")
LOG = os.path.join(ROOT, "log.md")
HISTORY = os.path.join(ROOT, "history")
MODEL_VERSION = "india-risk-v2"

BUCKET_LABELS = {
    "valuation": "Valuation",
    "external_currency": "External / Currency",
    "macro_stress": "Macro Stress",
    "domestic_flows": "Domestic Flows / Leverage",
    "sentiment_froth": "Sentiment / Froth",
}


def _num(x):
    """JSON-safe number (handles numpy scalars / None / NaN)."""
    if x is None:
        return None
    try:
        f = float(x)
        return None if f != f else round(f, 4)   # NaN -> None
    except (TypeError, ValueError):
        return None


def _tripwire_values(rows):
    """Indicator currents keyed by key, plus the raw values trip-wires need."""
    vals = {r["key"]: r.get("current") for r in rows}
    vals["usdinr_raw"] = fetch_market.latest("INR=X")
    vals["brent_usd"] = fetch_market.latest("BZ=F")
    return vals


def build():
    print("=" * 86)
    print(f"  INDIA RECESSION / BUBBLE-RISK DASHBOARD   build {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 86)

    rows = normalize.compute()
    problems = normalize.audit(rows)          # directionality audit, every build
    c = scoring.composite(rows)
    values = _tripwire_values(rows)
    a = scoring.assess(rows, c, values)

    # ---- console summary ----
    print("\n  BUCKETS (weighted, renormalized over live data):")
    for b in BUCKETS:
        v = c["bucket"][b]
        w = c["weights_used"].get(b)
        print(f"    {BUCKET_LABELS[b]:28s} {('%5.1f' % v) if v is not None else '  -- ':>5s}"
              f"   w={w if w is not None else '--'}")
    print(f"\n  COMPOSITE (posture) : {c['composite']}  +/- {c['margin']}"
          f"   [raw {c['composite_raw']}, breadth {c['breadth']}, coverage {c['coverage']*100:.0f}%]")
    print(f"  STANCE              : {a['label']}  -- {a['stance']}")
    print(f"  TRIP-WIRES          : {a['tripped']} / {len(a['tripwires'])} tripped")
    if problems:
        print("  !! AUDIT PROBLEMS:", "; ".join(problems))

    # ---- V2 analytics (trajectory, distance-to-trip, fwd returns, regime, analogs...) ----
    an = analytics.compute_all(rows, c, values)
    print(f"  REGIME              : {an['regime']['label']}  ({an['regime']['why']})")
    print(f"  READ                : {an['interpretation']}")

    # ---- assemble data.json ----
    generated_at = datetime.datetime.now(datetime.timezone.utc)
    payload = _payload(rows, c, a, values, an, generated_at)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  wrote {OUT}")
    archived = _archive_snapshot(payload)
    removed = _compact_history()
    print(f"  archived {archived}" + (f"; compacted {removed} old snapshots" if removed else ""))
    _inject_snapshot(payload)

    _log(rows, c, a)
    return payload


def _inject_snapshot(payload):
    """Embed the fresh JSON into index.html's <script id='bootstrap-data'> block so the
    page also renders when opened directly from disk (file://), where fetch() is blocked.
    Served over HTTP the live fetch wins, so this is purely an offline-viewing fallback."""
    if not os.path.exists(HTML):
        return
    with open(HTML, "r", encoding="utf-8") as f:
        html = f.read()
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")  # safe in <script>
    new, n = re.subn(
        r'(<script id="bootstrap-data" type="application/json">)(.*?)(</script>)',
        lambda m: m.group(1) + "\n" + blob + "\n" + m.group(3),
        html, count=1, flags=re.S)
    if n:
        with open(HTML, "w", encoding="utf-8") as f:
            f.write(new)
        print(f"  embedded snapshot -> {HTML}")
    else:
        print("  [warn] bootstrap-data block not found; snapshot not embedded")


def _artifact_metadata(rows, c, generated_at):
    dates = lambda source: [r["date"] for r in rows
                            if r["source"] == source and r.get("date")]
    counts = {}
    for r in rows:
        item = counts.setdefault(r["source"], {"total": 0, "live": 0, "stale": 0})
        item["total"] += 1
        item["live"] += int(bool(r.get("ok")))
        item["stale"] += int(bool(r.get("stale")))
    return {
        "generated_at": generated_at.isoformat(timespec="microseconds"),
        "market_as_of": max((str(d) for d in dates("market")), default=None),
        "manual_as_of": max((str(d) for d in dates("manual")), default=None),
        "source_counts": counts,
        "margin": c["margin"],
        "model_version": MODEL_VERSION,
        "source_sha": (os.environ.get("GITHUB_SHA") or "local")[:12],
    }


def _archive_snapshot(payload, directory=HISTORY):
    """Write one immutable JSON snapshot per build and return its path."""
    stamp = datetime.datetime.fromisoformat(payload["generated"]).astimezone(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H%M%S.%fZ")
    path = Path(directory) / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return str(path)


def _compact_history(directory=HISTORY, keep_daily_days=730, today=None):
    """Keep every build for two years, then only the latest snapshot per month."""
    cutoff = (today or datetime.date.today()) - datetime.timedelta(days=keep_daily_days)
    old = {}
    for path in Path(directory).glob("*.json"):
        try:
            date = datetime.datetime.strptime(path.stem, "%Y-%m-%dT%H%M%S.%fZ").date()
        except ValueError:
            continue
        if date < cutoff:
            old.setdefault((date.year, date.month), []).append(path)
    removed = 0
    for paths in old.values():
        for path in sorted(paths)[:-1]:
            path.unlink()
            removed += 1
    return removed


def _payload(rows, c, a, values, an, generated_at):
    sparks = an.pop("sparklines", {})
    by_bucket = {b: [] for b in BUCKETS}
    ind_out = []
    for r in rows:
        spark = [x for x in (sparks.get(r["key"]) or []) if x is not None]
        item = {
            "key": r["key"], "name": r["name"], "bucket": r["bucket"],
            "bucket_label": BUCKET_LABELS[r["bucket"]],
            "direction": r["direction"], "source": r["source"],
            "method": r.get("method"), "current": _num(r.get("current")),
            "score": _num(r.get("score")), "ok": r["ok"],
            "stale": bool(r.get("stale")), "age_days": r.get("age_days"),
            "date": str(r["date"]) if r.get("date") else None,
            "spark": spark if len(spark) >= 3 else None,
            "trend": _num(spark[-1] - spark[-4]) if len(spark) >= 4 else None,
        }
        ind_out.append(item)
        by_bucket[r["bucket"]].append(item)

    buckets = [{
        "key": b, "label": BUCKET_LABELS[b], "score": c["bucket"][b],
        "weight": WEIGHTS[b], "weight_used": c["weights_used"].get(b),
        "indicators": by_bucket[b],
    } for b in BUCKETS]

    tw_out = []
    for tripped, tw, val in a["tripwires"]:
        tw_out.append({
            "name": tw["name"], "level": tw["level"], "unit": tw.get("unit", ""),
            "trips_when": tw["trips_when"], "note": tw["note"],
            "value": _num(val), "tripped": tripped,
        })

    context = []
    for tkr, m in CFG["context_tickers"].items():
        s = fetch_market.history(tkr)
        last = _num(s.iloc[-1]) if s is not None and len(s) else None
        chg = None
        if s is not None and len(s) > 1:
            prior = s[s.index <= s.index[-1] - pd.Timedelta(days=350)]
            if len(prior):
                chg = _num((s.iloc[-1] / prior.iloc[-1] - 1) * 100)
        context.append({"ticker": tkr, "name": m["name"], "value": last, "chg_12m": chg})

    # contribution / waterfall: each bucket's weighted share of composite_raw
    contributions = [{
        "key": b, "label": BUCKET_LABELS[b],
        "contribution": _num((c["bucket"][b] or 0) * (c["weights_used"].get(b) or 0)),
    } for b in BUCKETS if c["bucket"][b] is not None]

    # freshness / confidence decomposition
    artifact = _artifact_metadata(rows, c, generated_at)
    stale_count = sum(1 for r in rows if r.get("stale"))
    conf_map = {"market": 95, "derived": 80, "manual": 70}
    confidence = [{"source": s, "n": n["total"], "pct": conf_map.get(s, 60)}
                  for s, n in sorted(artifact["source_counts"].items())]
    freshness = {
        "coverage": c["coverage"], "n_live": c["n_live"], "n_total": c["n_total"],
        "stale_count": stale_count, "margin": c["margin"],
        "market_asof": artifact["market_as_of"],
        "manual_oldest": min((str(r["date"]) for r in rows
                              if r["source"] == "manual" and r.get("date")), default=None),
        "manual_newest": artifact["manual_as_of"],
        "confidence": confidence,
    }

    return {
        **an,                      # trajectory, distance_to_trip, forward_returns, fwd_note,
                                   # analogs, regime, stress_types, interpretation, probabilities
        "contributions": contributions,
        "freshness": freshness,
        "generated": artifact["generated_at"],
        "artifact": artifact,
        "composite": c["composite"], "composite_raw": c["composite_raw"],
        "margin": c["margin"], "breadth": c["breadth"], "coverage": c["coverage"],
        "n_live": c["n_live"], "n_total": c["n_total"],
        "verdict": {"label": a["label"], "stance": a["stance"], "tripped": a["tripped"]},
        "buckets": buckets,
        "tripwires": tw_out,
        "defeaters": [{"name": r["name"], "score": _num(r["score"]),
                       "bucket_label": BUCKET_LABELS[r["bucket"]]} for r in a["defeaters"]],
        "indicators": ind_out,
        "context": context,
        "danger": c["danger"], "stale": c["stale"], "missing_buckets": c["missing_buckets"],
        "audit_problems": _audit_problems(rows),
        "meta": {
            "weights": WEIGHTS, "bands": CFG["bands"]["composite"],
            "danger_zone": CFG["breadth"]["danger_zone"], "floor": CFG["breadth"]["floor"],
            "anchor_switch_n": CFG["normalize"]["anchor_switch_n"],
        },
    }


def _audit_problems(rows):
    specs = cfg_indicators()
    probs = []
    for r in rows:
        spec = specs[r["key"]]
        if "calm" in spec and "stress" in spec:
            if (spec["stress"] > spec["calm"]) != (spec["direction"] == "high"):
                probs.append(r["name"])
    return probs


def _log(rows, c, a):
    ok = [r for r in rows if r["ok"]]
    top = sorted(ok, key=lambda r: -r["score"])[:3]
    line = (f"\n### {datetime.datetime.now():%Y-%m-%d %H:%M}\n"
            f"- composite (posture) **{c['composite']}** +/-{c['margin']} "
            f"| raw {c['composite_raw']} | breadth {c['breadth']} | {a['label']}\n"
            f"- buckets: " + " / ".join(f"{b}={c['bucket'][b]}" for b in BUCKETS) + "\n"
            f"- trip-wires: {a['tripped']}/{len(a['tripwires'])} | live {len(ok)}/{len(rows)}\n"
            f"- highest stress: " + ", ".join(f"{r['name']} ({r['score']:.0f})" for r in top) + "\n")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    build()
