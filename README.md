# DCF Valuation Tool

Type a stock ticker, get a discounted cash flow (DCF) valuation with sensitivity analysis, and see how the model's intrinsic value compares to the current share price.

```bash
python main.py AAPL
```

Outputs:
- A console summary (assumptions, projected cash flows, valuation bridge, upside/downside)
- An Excel workbook with Summary, Projections, History and two sensitivity sheets (green = above current price, red = below)
- Two heatmap charts: **WACC vs terminal growth** and **WACC vs initial growth**

## Data sources

| `--source` | What you need | Notes |
|---|---|---|
| `yahoo` (default) | Nothing | Free, via [`yfinance`](https://github.com/ranaroussi/yfinance) |
| `factset` | A FactSet API key | Fundamentals API (annual statements) + Prices API (price, 5-yr monthly beta vs SPY). 10-yr Treasury still from Yahoo. |

### Setting up FactSet

1. Sign in at [developer.factset.com](https://developer.factset.com) and create an API key (look for **Manage API keys**). Your account must be entitled to the *FactSet Fundamentals* and *FactSet Prices* APIs. A desktop/workstation-only license is not enough.
2. Copy `.env.example` to `.env` and fill in `FACTSET_USERNAME` (your USERNAME-SERIAL) and `FACTSET_API_KEY`. `.env` is git-ignored, so the key stays on your computer.
3. Run `python main.py AAPL --source factset`. Tickers default to the US listing (`AAPL` → `AAPL-US`); pass a suffix for other markets, e.g. `VOD-GB`.

## Setup

```bash
git clone https://github.com/<your-username>/dcf-valuation.git
cd dcf-valuation
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

```bash
python main.py MSFT                                  # all defaults
python main.py MSFT --growth 0.10 --years 10         # your own growth view, longer horizon
python main.py KO --wacc 0.07 --terminal-growth 0.02 # override the discount rate
python main.py NKE --base-fcf-years 3                # smooth a lumpy cash-flow year
```

| Flag | Default | Meaning |
|---|---|---|
| `--years` | 10 | Projection years |
| `--hold-years` | 3 | Years the initial growth is held before fading to terminal growth |
| `--growth` | analyst revenue estimate, else historical CAGR (capped at 40%) | Initial FCF growth |
| `--no-analyst` | – | Ignore analyst estimates, use historical growth |
| `--raw-beta` | – | Use raw beta instead of Blume-adjusted (0.67 × raw + 0.33) |
| `--terminal-growth` | 0.025 | Perpetual growth after the projection period |
| `--wacc` | computed | Override the discount rate |
| `--erp` | 0.055 | Equity risk premium for CAPM |
| `--base-fcf-years` | 1 | Average the last N years of FCF as the starting point |
| `--base-fcf` | – | Override the starting FCF entirely |
| `--output-dir` | `output` | Where the Excel file and charts go |
| `--no-excel`, `--no-chart` | – | Skip those outputs |

Run the tests with `pytest`.

## How the model works

1. **Free cash flow**: Operating cash flow − capital expenditure (from Yahoo's annual cash-flow statement), plus after-tax interest to approximate *unlevered* FCF.
2. **Growth**: the initial rate (analyst consensus revenue growth for next year, or historical revenue CAGR) is held for `--hold-years`, then fades linearly to terminal growth by the final year.
3. **Discount rate (WACC)**
   - Cost of equity = risk-free rate (10-yr Treasury, `^TNX`) + beta × equity risk premium
   - Cost of debt = interest expense ÷ total debt, after tax
   - Weighted by market value of equity and book value of debt
4. **Terminal value**: Gordon growth model, `FCF_final × (1 + g) / (WACC − g)`
5. **Equity value** = enterprise value − debt + cash, divided by shares outstanding
6. **Sensitivity**: re-runs the valuation across a 5×5 grid of WACC and growth assumptions.
7. **Reverse DCF**: solves for the growth rate that makes the model value equal today's price, and compares the market's EV/FCF multiple with the exit multiple the model assumes. For high-quality growth companies this is often more informative than the "overvalued" label: it tells you what you'd have to believe to buy at today's price.

## Project structure

```
dcf/
  data.py         # fetch statements + price from Yahoo Finance
  model.py        # WACC, growth, projections, terminal value (pure math, no network)
  sensitivity.py  # 5x5 sensitivity grids
  report.py       # console output, Excel export, heatmaps
main.py           # command-line interface
tests/            # unit tests with a fake company (no internet needed)
```

## Limitations

- **Not suited to banks, insurers or REITs.** Their cash flows don't map to OCF − CapEx; use dividend-discount or P/B models instead.
- Companies with **negative FCF** (early-stage, turnarounds) will error out unless you pass `--base-fcf`.
- Yahoo provides only ~4 years of annual statements, and line items occasionally change names.
- The output is only as good as the assumptions. Use the sensitivity tables to see which inputs matter most, and check the terminal value's share of EV (above ~75% means the answer depends mostly on the far future).

*For educational purposes only. Not investment advice.*

## Ideas for next versions

- Pull consensus analyst growth estimates instead of historical CAGR
- Bear / base / bull scenarios
- Revenue-driven model (revenue × margin − reinvestment) instead of growing FCF directly
- Streamlit web app front end
- Compare DCF value to multiples (P/E, EV/EBITDA) of peers
