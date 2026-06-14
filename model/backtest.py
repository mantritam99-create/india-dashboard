"""Calibrate the composite against India's real crises BEFORE trusting live output.

HONEST SCOPE: only the market-sourced indicators have history, so the backtest
scores the two market-driven buckets -- EXTERNAL/CURRENCY (USD/INR 12m move,
Brent-in-INR) and SENTIMENT/FROTH (India VIX, Midcap/largecap ratio). Valuation,
macro-stress and domestic-flows are manual and have no back-history in this keyless
setup, so they are NOT backtested. That's fine: the spec's make-or-break is the
EM-stress core, and that core is exactly what's market-driven and testable here.

The questions the spec insists on:
  1. 2013 TAPER TANTRUM -- does external/currency SPIKE?  (make-or-break)
  2. 2008 GFC / 2018 NBFC -- does the composite rise ahead of the equity peak?
  3. COVID 2020 -- does it correctly STAY LOW pre-peak (exogenous, not predictable)?
  4. 2017 small/mid mania -- does sentiment/froth flag before the 2018 correction?
  5. How often does it fire in benign months?  (false-positive discipline)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from config import CFG
from model import normalize, scoring

# Equity peaks the thesis would have needed to fire BEFORE.
PEAKS = {"GFC 2008": "2008-01-08", "NBFC 2018": "2018-08-28", "COVID 2020": "2020-01-20"}
REC_END = {"GFC 2008": "2009-03-31", "NBFC 2018": "2019-09-30", "COVID 2020": "2020-04-30"}


def _mdiff(a, b):
    return (a.year - b.year) * 12 + (a.month - b.month)


def _fmt(x):
    return f"{x:5.1f}" if x is not None else "  -- "


def run():
    print("=" * 80)
    print("  BACKTEST  -  point-in-time, monthly 2005-2021 (no lookahead)")
    print("  Backtestable buckets: external_currency + sentiment_froth (market-sourced).")
    print("=" * 80)

    loaded = normalize.market_loaded()
    dates = pd.date_range("2005-01-01", "2021-06-01", freq="MS")
    sweep = {d: scoring.composite_asof(loaded, d) for d in dates}

    def at(month, field="composite", bucket=None):
        s = sweep.get(month)
        if not s:
            return None
        return s["bucket"].get(bucket) if bucket else s[field]

    # ---- per-peak trajectory ----
    for label, pk in PEAKS.items():
        peak = pd.Timestamp(pk).to_period("M").to_timestamp()
        print(f"\n  {label}   (equity peak {pk})")
        print("    lead:           T-12    T-6     T-3    T-0")
        for name, field, bk in [("composite", "composite", None),
                                ("external/ccy", None, "external_currency"),
                                ("sentiment", None, "sentiment_froth")]:
            cells = []
            for lead in (12, 6, 3, 0):
                m = (peak.to_period("M") - lead).to_timestamp()
                cells.append(_fmt(at(m, field, bk)))
            print(f"    {name:14s} " + "  ".join(cells))

    # ---- THE MAKE-OR-BREAK: 2013 taper tantrum, external/currency monthly ----
    print("\n" + "=" * 80)
    print("  *** 2013 TAPER TANTRUM -- external/currency bucket (MAKE-OR-BREAK) ***")
    print("=" * 80)
    t2013 = pd.date_range("2013-01-01", "2013-12-01", freq="MS")
    print("    month   :  " + "  ".join(d.strftime("%b") for d in t2013))
    print("    ext/ccy :  " + "  ".join(f"{(at(d, bucket='external_currency') or 0):3.0f}" for d in t2013))
    print("    usdinr% :  " + "  ".join(
        f"{(normalize.score_asof(_spec('usdinr_12m'), _series(loaded,'usdinr_12m'), d)[1] or 0):3.0f}"
        for d in t2013))
    peak_2013 = max((at(d, bucket="external_currency") or 0) for d in t2013)
    verdict = "PASS" if peak_2013 >= 70 else "FAIL"
    print(f"\n    peak external/currency bucket in 2013: {peak_2013:.1f}   -> {verdict}")
    print("    (FAIL here means inversion or weighting is broken -- fix before trusting live.)")

    # ---- 2017 small/mid mania: sentiment/froth should be elevated ----
    print("\n  ---- 2017 small/mid mania: sentiment/froth bucket ----")
    t2017 = pd.date_range("2017-01-01", "2017-12-01", freq="MS")
    print("    month   :  " + "  ".join(d.strftime("%b") for d in t2017))
    print("    froth   :  " + "  ".join(f"{(at(d, bucket='sentiment_froth') or 0):3.0f}" for d in t2017))
    peak_2017 = max((at(d, bucket="sentiment_froth") or 0) for d in t2017)
    print(f"    peak sentiment/froth in 2017: {peak_2017:.1f}  (should be elevated pre-2018 correction)")

    # ---- calibration: max composite reached IN each event window vs benign FP ----
    #  Currency/credit stress is coincident, not 12m-leading (it erupts fast and the
    #  buckets that WOULD lead -- valuation/froth -- aren't backtestable). So we score
    #  "did the composite reach level T anywhere in the event's stress window", not
    #  "did it lead the equity peak by N months".
    STRESS = {
        "GFC 2008":  ("2008-08-01", "2009-03-31"),   # rupee/credit crisis trailed the Jan equity peak
        "Taper 2013": ("2013-05-01", "2013-12-31"),
        "NBFC 2018": ("2018-06-01", "2019-02-28"),
    }
    win = {k: [d for d in dates if pd.Timestamp(a) <= d <= pd.Timestamp(b)] for k, (a, b) in STRESS.items()}
    covid_win = [d for d in dates if pd.Timestamp("2020-02-01") <= d <= pd.Timestamp("2020-06-30")]
    all_stress = set().union(*win.values()) | set(covid_win)
    benign = [d for d in dates if d not in all_stress]
    bands = CFG["bands"]["composite"]

    print("\n  " + "-" * 76)
    print("  CALIBRATION - max composite reached IN each stress window vs benign FP%")
    print(f"  (benign = {len(benign)} months outside all stress windows; bands: "
          f"watch {bands['watch']} / warning {bands['warning']} / acute {bands['acute']})")
    print("  " + "-" * 76)
    print("   thresh |  GFC08  |  Taper13 | NBFC18  | benign FP%")
    for T in (50, 58, 65, 75):
        cells = [("  hit  " if max((at(d) or 0) for d in win[k]) >= T else " under ") for k in STRESS]
        fp = sum(1 for d in benign if (at(d) or 0) >= T) / len(benign) * 100
        print(f"    >={T:<3d} | {cells[0]:^7s} | {cells[1]:^8s} | {cells[2]:^7s} |  {fp:4.1f}%")
    for k in STRESS:
        print(f"    peak composite {k:10s}: {max((at(d) or 0) for d in win[k]):.1f}")

    # ---- COVID restraint ----
    print("\n  COVID restraint check (composite at T-6/3/1 before Jan-2020 equity peak):")
    covid_peak = pd.Timestamp(PEAKS["COVID 2020"]).to_period("M").to_timestamp()
    pre = [at((covid_peak.to_period("M") - k).to_timestamp()) for k in (6, 3, 1)]
    pre = [x for x in pre if x is not None]
    ok = max(pre) < bands["warning"]
    print(f"    {', '.join(f'{x:.1f}' for x in pre)}   -> "
          f"{'PASS (stays below warning; not predicted)' if ok else 'FAIL (over-fired on exogenous shock)'}")

    print("\n" + "=" * 80)
    print("  Read honestly: 2013 & 2018 should HIT warning/acute; COVID should not;")
    print("  benign FP% should fall off fast above the watch band. Do NOT tune to a")
    print("  prettier number -- only to fix miscalibration.")
    print("=" * 80)


# -- small helpers to fish a single market spec/series out of `loaded` --
def _spec(key):
    from config import indicators as ci
    return ci()[key]


def _series(loaded, key):
    for spec, s in loaded:
        if spec["key"] == key:
            return s
    return None


if __name__ == "__main__":
    run()
