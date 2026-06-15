# India Recession / Bubble-Risk Dashboard

A backtested, 5-bucket stress composite for Indian equity-market risk. It answers two
**separate** questions and never collapses them into one number:

- **POSTURE** — how defensive to sit → the weighted, breadth-adjusted *composite*.
- **ACTION** — when to actually move → the *trip-wires* (a watchable checklist).

> The model's job is to be **right, not reassuring.** Weights, floor and thresholds are
> only changed to fix a backtest miscalibration — never to produce a prettier composite.

---

## Architecture

A static page can't call data sources directly (key leakage + CORS), so the work is split:

```
build.py   ── fetch (market + manual) → normalize → AUDIT → score → writes output/data.json
output/index.html ── static; reads ONLY data.json (no network, no keys)
GitHub Actions ── runs build.py on a daily cron + manual trigger, deploys output/ to Pages
```

```
india-dashboard/
├── config.yaml            # ALL weights, indicators, inversions, anchors, bands, trip-wires
├── config.py              # loads config.yaml, resolves paths
├── cache_util.py          # date-stamped cache (CSV for series, JSON for scalars)
├── build.py               # orchestrator → data.json + log.md + console audit
├── data/
│   ├── fetch_market.py    # Yahoo chart endpoint (keyless) + stooq fallback, cached
│   ├── fetch_manual.py    # reads manual_inputs.csv → dated series per indicator
│   └── manual_inputs.csv  # hand-updated monthly (RBI / AMFI / NSE / MoSPI series)
├── model/
│   ├── normalize.py       # percentile + anchor + derived scoring, transforms, AUDIT
│   ├── scoring.py         # buckets, breadth, composite, confidence margin, verdict
│   └── backtest.py        # calibration vs 2008 / 2013 / 2018 / 2020 / 2017
├── output/
│   ├── index.html         # the dashboard (static reader)
│   └── data.json          # generated artifact
└── .github/workflows/deploy.yml
```

---

## The five buckets (weights are deliberately asymmetric)

| Bucket | Weight | Why |
|---|---|---|
| Valuation | 0.25 | Nifty PE/PB, Buffett indicator, earnings-yield vs G-sec — ranked vs **India's own** history |
| **External / Currency** | **0.25** | USD/INR, FX reserves, FII flows, Brent-in-INR, trade deficit |
| Macro Stress | 0.20 | 10Y G-sec, 10Y−repo, CPI vs 4% target, IIP, GST |
| Domestic Flows / Leverage | 0.15 | SIP inflows, F&O/cash ratio, MTF book, demat growth (the retail-leverage risk) |
| Sentiment / Froth | 0.15 | India VIX, advance-decline, SME-IPO listing gains, midcap/largecap ratio |

The heavy **external/currency** weight is the whole point: India's real crashes (2013 taper
tantrum, 2018 NBFC) were **capital-flow / currency** driven, not domestic-yield driven. The
asymmetry is not "unbalanced" — it encodes the thesis.

---

## Scoring

1. **Percentile** — each indicator scored 0–100 as the % of its **own history** below the
   current reading, flipped when `direction: low` (e.g. falling FX reserves = high stress).
2. **Anchor** — manual indicators with too little history (and India VIX, where a pure
   percentile would mislabel "calm-but-low" as low-stress) map a reading between `calm`→0 and
   `stress`→100. Each manual series **auto-graduates** from anchor to percentile at **24**
   readings. Every indicator is labelled `anchor` / `percentile` / `derived` in the output.
3. **Bucket score** = mean of its live indicators (NaNs ignored).
4. **Composite (raw)** = weighted sum, **renormalized** over buckets that actually have data.
5. **Breadth adjustment** = `composite_raw × (floor + (1−floor) × breadth)`, where breadth =
   share of live indicators in the danger zone (>75). This **discounts a score driven by a few
   screaming indicators** — broad agreement is required for full conviction.
6. **Confidence margin** `±` widens with stale manual data, missing buckets, low coverage and
   bucket dispersion. (Manual-heavy data ⇒ staleness weighs more here than a US-style model.)

### Directionality audit (runs every build)
`build.py` prints every indicator's value, stress score, invert flag and method, and asserts
each anchor's `calm/stress` ordering agrees with its `direction`. **One flipped sign silently
corrupts the whole composite**, so it's checked on every run and surfaced in `data.json`
(`audit_problems`) and the dashboard footer.

---

## Backtest & calibration (`python model/backtest.py`)

**Honest scope:** only the market-sourced indicators have history, so the backtest scores the
two market-driven buckets — **external/currency** (USD/INR 12m move, Brent-in-INR) and
**sentiment/froth** (India VIX, midcap/largecap ratio). Valuation, macro-stress and
domestic-flows are manual and have **no back-history** in this keyless setup, so they are not
backtested. That's acceptable: the spec's make-or-break is the EM-stress core, which *is* the
market-driven, testable part. The confidence margin reflects this thinness.

Point-in-time, monthly 2005–2021, no lookahead:

| Event | Result |
|---|---|
| **2013 taper tantrum** | external/currency bucket peaks **~93**; composite hits **~76 (acute)** ✓ make-or-break |
| GFC 2008 | composite **~99** when the rupee/credit crisis erupted (Oct-08, *after* the Jan equity peak) |
| NBFC 2018 | composite **~64 (watch / near-warning)** — genuinely milder at the composite level |
| COVID 2020 | composite **~22** pre-peak → correctly **not predicted** (exogenous; predicting it = overfit) |
| 2017 mid/small mania | sentiment/froth elevated (~68) ahead of the 2018 correction |

Benign-month false-positive rate falls from ~20% (≥50) to **~2% (≥75)** — real events cluster
at 64–99, benign months rarely clear 65.

**Calibration decisions made from the backtest (not to flatter the number):**
- `breadth.floor` **kept at 0.50.** Sweeping it showed a higher floor inflates benign months
  as much as real events (separation *worsens*); 0.50 gives the cleanest discrimination and
  correctly suppresses COVID. The earlier "miss" was a band-placement problem, not a floor one.
- `bands` set to **benign 50 / watch 58 / warning 65 / acute 75** so the composite actually
  fires on 2013/2018-scale events without sitting lit through benign periods.
- **Currency/credit stress is coincident, not 12-month leading** — it erupts fast, and the
  buckets that *would* lead (valuation/froth) aren't backtestable. Treat the composite as
  posture and the trip-wires as the action signal accordingly.

---

## Deliberate deviations from the spec (and why)

- **Direct Yahoo chart endpoint instead of `yfinance`.** Same data source, no fragile
  dependency — and it matches the sibling US dashboard's proven pattern. A **stooq** CSV
  fallback is wired in as the spec requested.
- **Midcap/largecap instead of smallcap/largecap ratio.** No keyless long-history Nifty
  Smallcap series exists (`^CNXSC` returns one point); Nifty Midcap (`^NSMIDCP`, history to
  2007) is the froth-broadening proxy and covers every backtest event.
- **Nifty PE/PB, Buffett indicator, 10Y G-sec are in the manual CSV**, not auto-fetched — none
  has a clean keyless API. Anchors in `config.yaml` keep them scored until ≥24 readings accrue.
- **USD/INR trip-wire tuned 90 → 100.** Spot is already ~96 (structural rupee weakness), which
  would leave the spec's 90 wire permanently tripped and useless as an action signal. Revisit
  as the rupee drifts; a rate-of-change wire may eventually serve better.

---

## The manual layer (update monthly, or the margin correctly widens)

`data/manual_inputs.csv` schema: `date,indicator,value,note`. Add **one new dated row per
indicator each month** — history accumulates and each series auto-switches to percentile at 24
readings. Sources:

| Indicators | Source |
|---|---|
| FII 3m flows | NSDL/CDSL, moneycontrol FII-DII activity |
| FX reserves (8wk %) | RBI weekly statistical supplement |
| CPI, IIP | MoSPI |
| GST YoY | PIB monthly release |
| SIP inflows | AMFI |
| MTF book, F&O/cash, demat growth | NSE / broker reports |
| SME IPO gains | chittorgarh.com |
| Nifty PE/PB | niftyindices.com (daily) |
| Buffett (mcap/GDP), 10Y G-sec, trade deficit, A/D ratio | RBI / NSE / MoSPI |

Stale rows (>45 days) are still used but flagged, and they widen the confidence interval —
the model tells you honestly when it's running on old data.

---

## V2 — the decision-support layer (`model/analytics.py` → `data.json` → `output/index.html`)

The dashboard is a *quantified country-macro memo with scoring rails*, not a trading cockpit.
On top of the live composite it renders:

- **Three stress lenses** — recession · credit/currency · asset-bubble — so "recession risk ≠
  credit risk ≠ bubble risk" stays explicit (India's froth fires earlier than its macro).
- **Hero interpretation line** — a generated top-line read; **threshold ladder** next to the score.
- **Distance-to-trip gauges** — each trip-wire as a floor→trigger fill % ("what could break next"),
  paired with **bull-case defeaters** ("why risk is capped") as the headline anchor.
- **Composite trajectory** (market-core, ~15y) with stress bands + threshold lines — the 2013 spike
  is visible. **Contribution waterfall**, **forward-returns by band**, **indicative odds**,
  **historical analogs**, **regime label**, **freshness/confidence header**.
- **Scenario engine** — re-scores the composite client-side (Rupee crisis / Oil shock / Midcap mania
  / FII exodus) with the same math as `build.py`. **Methodology drawer**, **tooltips**,
  sortable/filterable **indicator table** with sparklines + trend arrows.

Honest scope: everything *historical* (trajectory, forward-returns, analogs, probabilities) is the
**market-core** (external + sentiment) — the only buckets with back-history. A key, non-obvious
finding surfaced and is captioned in the UI: India's market-core stress is **contrarian at extremes**
— the 70+ readings are the 2008/2013 capitulation lows, which *preceded rebounds*. High composite is
not a sell signal; the asset-bubble lens (valuations/froth) is the "expensive" warning.

## Run it

```bash
pip install -r requirements.txt
python build.py                 # fetch + score + audit, writes output/data.json + log.md
python model/normalize.py       # directionality audit only
python model/backtest.py        # calibration report

# preview the dashboard locally (browsers block file:// fetch):
cd output && python -m http.server 8000   # → http://localhost:8000/
```

## Deploy to GitHub Pages (one-time)

1. Push the repo to GitHub.
2. **Settings → Pages → Source: GitHub Actions.**
3. **Actions** tab → run **build-and-deploy** manually for the first build.
4. The site appears at `https://<you>.github.io/<repo>/`. It then rebuilds daily.

---

## Honesty guardrails (non-negotiable)

1. **Bull-case defeaters** panel — always shows the lowest-stress indicators (what's working
   *against* the thesis). Permanent anti-confirmation-bias check.
2. **Breadth adjustment** — discounts scores driven by few indicators.
3. **Posture / Action split** — never one number.
4. **Directionality audit** every build.
5. **Method labels** on every indicator so data quality is visible.
