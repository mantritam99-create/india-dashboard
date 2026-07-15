# Build & reading log

Automated build entries are appended below by `build.py`. Narrative milestones are
hand-written.

---

## 2026-06-05 — Initial build (M1–M9)

Built module-by-module, testing each gate before wiring the next (per spec §8):

- **config.yaml** — 5 buckets, asymmetric weights (external/currency 0.25), 22 indicators
  with `direction` + anchors, derived formulas, trip-wires, bands.
- **fetch_market.py** — keyless Yahoo chart endpoint + stooq fallback, cached. *Gate passed:*
  Nifty/BankNifty/VIX/USDINR/Brent all pull. Smallcap `^CNXSC` is dead (1 pt) → switched the
  froth ratio to **Nifty Midcap `^NSMIDCP` / Nifty 50**.
- **normalize.py** — percentile + anchor + derived scoring, market transforms (12m move,
  Brent×INR, midcap ratio), directionality audit. *Gate passed:* audit clean; all four
  spec-named signs (rupee↑, reserves↓, FII out, SIP↓) read as more stress.
- **scoring.py / build.py** — buckets, breadth, breadth-adjusted composite, confidence margin,
  verdict (stance + trip-wires + bull-case defeaters), writes data.json.
- **backtest.py** — point-in-time 2005–2021. **2013 taper tantrum: external/currency peaks ~93,
  composite ~76 (acute) → PASS** (the make-or-break). COVID correctly not predicted (~22).
  GFC 2008 hits ~99 when the crisis erupted; NBFC 2018 hits ~64 (watch). 2017 froth elevated.
- **Calibration:** kept `floor 0.50` (sweep showed raising it only inflates benign months);
  set bands 50/58/65/75 to match real event levels; tuned USD/INR trip-wire 90→100 (spot ~96
  already past 90). Noted: currency stress is coincident, not 12m-leading.
- **index.html** — static reader; posture/action split, bucket bars, trip-wire checklist,
  defeaters, full indicator table with method/source badges. Data contract verified.
- **deploy.yml** — daily cron + manual + push; builds and deploys output/ to Pages.

First live reading (calm-macro mid-2026): composite **29.6 (NO CRISIS SIGNAL)**, raw 48.2,
breadth 0.23 — elevated valuation/external/froth buckets but discounted because the stress is
concentrated (midcap ratio 99.6, Brent-INR 98.5, USD/INR 12m 89.6) rather than broad. 0/7
trip-wires. The breadth discount is doing exactly its job.

---

### Automated build log

### 2026-06-05 06:21
- composite (posture) **29.6** +/-7.0 | raw 48.2 | breadth 0.23 | NO CRISIS SIGNAL
- buckets: valuation=56.7 / external_currency=61.5 / macro_stress=15.6 / domestic_flows=47.8 / sentiment_froth=55.8
- trip-wires: 0/7 | live 22/22
- highest stress: Midcap / largecap index ratio (100), Brent crude, INR-adjusted (98), Earnings yield - 10Y G-sec (pp) (90)

### 2026-06-05 07:29
- composite (posture) **29.6** +/-7.0 | raw 48.2 | breadth 0.23 | NO CRISIS SIGNAL
- buckets: valuation=56.7 / external_currency=61.5 / macro_stress=15.6 / domestic_flows=47.8 / sentiment_froth=55.8
- trip-wires: 0/7 | live 22/22
- highest stress: Midcap / largecap index ratio (100), Brent crude, INR-adjusted (98), Earnings yield - 10Y G-sec (pp) (90)

### 2026-06-14 18:06
- composite (posture) **29.2** +/-6.9 | raw 47.6 | breadth 0.23 | NO CRISIS SIGNAL
- buckets: valuation=56.7 / external_currency=60.4 / macro_stress=15.6 / domestic_flows=47.8 / sentiment_froth=53.5
- trip-wires: 0/7 | live 22/22
- highest stress: Midcap / largecap index ratio (100), Brent crude, INR-adjusted (96), Earnings yield - 10Y G-sec (pp) (90)

### 2026-06-15 15:36
- composite (posture) **28.7** +/-6.9 | raw 46.8 | breadth 0.23 | NO CRISIS SIGNAL
- buckets: valuation=56.7 / external_currency=57.8 / macro_stress=15.6 / domestic_flows=47.8 / sentiment_froth=52.6
- trip-wires: 0/7 | live 22/22
- highest stress: Midcap / largecap index ratio (100), Brent crude, INR-adjusted (95), Earnings yield - 10Y G-sec (pp) (90)

### 2026-06-15 15:42
- composite (posture) **28.7** +/-6.9 | raw 46.8 | breadth 0.23 | NO CRISIS SIGNAL
- buckets: valuation=56.7 / external_currency=57.8 / macro_stress=15.6 / domestic_flows=47.8 / sentiment_froth=52.6
- trip-wires: 0/7 | live 22/22
- highest stress: Midcap / largecap index ratio (100), Brent crude, INR-adjusted (95), Earnings yield - 10Y G-sec (pp) (90)


### 2026-07-15 07:19
- composite (posture) **26.6** +/-7.7 | raw 44.7 | breadth 0.19 | NO CRISIS SIGNAL
- buckets: valuation=56.7 / external_currency=59.5 / macro_stress=15.6 / domestic_flows=47.8 / sentiment_froth=35.7
- trip-wires: 0/7 | live 21/22
- highest stress: Brent crude, INR-adjusted (96), Earnings yield - 10Y G-sec (pp) (90), USD/INR 12-month % move (82)
