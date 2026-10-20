# DCF Valuation Tool

Type a stock ticker, get a discounted cash flow (DCF) valuation with sensitivity analysis, and see how the model's intrinsic value compares to the current share price.

```bash
python main.py AAPL
```

Outputs:
- A console summary (assumptions, projected cash flows, valuation bridge, upside/downside)
- An Excel workbook with Summary, Projections, History and two sensitivity sheets (green = above current price, red = below)
- Two heatmap charts: **WACC vs terminal growth** and **WACC vs initial growth**

Data comes free from Yahoo Finance via [`yfinance`](https://github.com/ranaroussi/yfinance). No API key needed.

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
| `--years` | 5 | Projection years |
| `--growth` | historical revenue CAGR (clipped -5%..20%) | Year-1 FCF growth; fades linearly to terminal growth |
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
2. **Growth**: starts at the initial growth rate and fades linearly to the terminal growth rate by the final projection year.
3. **Discount rate (WACC)**
   - Cost of equity = risk-free rate (10-yr Treasury, `^TNX`) + beta × equity risk premium
   - Cost of debt = interest expense ÷ total debt, after tax
   - Weighted by market value of equity and book value of debt
4. **Terminal value**: Gordon growth model, `FCF_final × (1 + g) / (WACC − g)`
5. **Equity value** = enterprise value − debt + cash, divided by shares outstanding
6. **Sensitivity**: re-runs the valuation across a 5×5 grid of WACC and growth assumptions.

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
