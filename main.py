"""Command-line entry point.

Examples
--------
    python main.py AAPL
    python main.py MSFT --growth 0.10 --terminal-growth 0.03 --years 10
    python main.py KO --wacc 0.07 --base-fcf-years 3
    python main.py AAPL --source factset      # needs FactSet API key in .env
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dcf.data import fetch_company_data
from dcf.model import Assumptions, run_dcf
from dcf.report import plot_heatmap, print_summary, write_excel
from dcf.sensitivity import wacc_vs_initial_growth, wacc_vs_terminal_growth


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build a DCF model with sensitivity analysis for a stock.")
    p.add_argument("ticker", help="Stock ticker, e.g. AAPL")
    p.add_argument("--source", choices=["yahoo", "factset"], default="yahoo",
                   help="Data source (default yahoo). factset needs an API key in .env")
    p.add_argument("--years", type=int, default=10, help="Projection years (default 10)")
    p.add_argument("--hold-years", type=int, default=3,
                   help="Years the initial growth is held before fading (default 3)")
    p.add_argument("--growth", type=float, help="Initial FCF growth, e.g. 0.08 for 8%% "
                                                "(default: analyst estimate, else historical)")
    p.add_argument("--no-analyst", action="store_true",
                   help="Ignore analyst estimates; use historical revenue growth")
    p.add_argument("--raw-beta", action="store_true",
                   help="Use raw beta instead of the Blume-adjusted beta")
    p.add_argument("--terminal-growth", type=float, default=0.025,
                   help="Terminal growth rate (default 0.025)")
    p.add_argument("--wacc", type=float, help="Override the discount rate, e.g. 0.09")
    p.add_argument("--erp", type=float, default=0.055, help="Equity risk premium (default 0.055)")
    p.add_argument("--base-fcf-years", type=int, default=1,
                   help="Average the last N years of FCF as the starting point (default 1)")
    p.add_argument("--base-fcf", type=float, help="Override the starting FCF (in reporting currency)")
    p.add_argument("--output-dir", default="output", help="Where to save Excel/charts (default ./output)")
    p.add_argument("--no-excel", action="store_true", help="Skip the Excel export")
    p.add_argument("--no-chart", action="store_true", help="Skip the heatmap charts")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    assumptions = Assumptions(
        projection_years=args.years,
        hold_years=args.hold_years,
        initial_growth=args.growth,
        use_analyst_growth=not args.no_analyst,
        adjust_beta=not args.raw_beta,
        terminal_growth=args.terminal_growth,
        equity_risk_premium=args.erp,
        wacc=args.wacc,
        base_fcf_years=args.base_fcf_years,
        base_fcf=args.base_fcf,
    )

    try:
        print(f"Fetching data for {args.ticker.upper()} from {args.source}...")
        if args.source == "factset":
            from dcf.factset import fetch_company_data_factset
            data = fetch_company_data_factset(args.ticker)
        else:
            data = fetch_company_data(args.ticker)
        result = run_dcf(data, assumptions)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    sens_tg = wacc_vs_terminal_growth(data, assumptions, result)
    sens_g = wacc_vs_initial_growth(data, assumptions, result)
    print_summary(data, assumptions, result, sens_tg, sens_g)

    stem = f"{data.ticker}_{date.today():%Y-%m-%d}"
    out = Path(args.output_dir)
    if not args.no_excel:
        xlsx = write_excel(out / f"{stem}_dcf.xlsx", data, assumptions, result, sens_tg, sens_g)
        print(f"Saved Excel model: {xlsx}")
    if not args.no_chart:
        c1 = plot_heatmap(out / f"{stem}_sens_tg.png", sens_tg, data.price,
                          f"{data.ticker} value per share: WACC vs terminal growth",
                          "Terminal growth")
        c2 = plot_heatmap(out / f"{stem}_sens_growth.png", sens_g, data.price,
                          f"{data.ticker} value per share: WACC vs initial growth",
                          "Initial growth")
        print(f"Saved charts: {c1}, {c2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
