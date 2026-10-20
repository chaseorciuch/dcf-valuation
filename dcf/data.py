"""Pull the raw inputs a DCF needs from Yahoo Finance (via yfinance)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFAULT_RISK_FREE = 0.042  # fallback if the 10-year Treasury yield can't be fetched
DEFAULT_TAX_RATE = 0.21


@dataclass
class CompanyData:
    ticker: str
    name: str
    price: float
    shares_outstanding: float
    beta: float
    fcf_history: pd.Series      # annual free cash flow (OCF - CapEx), oldest -> newest
    revenue_history: pd.Series  # annual revenue, oldest -> newest
    total_debt: float
    cash: float
    interest_expense: float     # latest annual, positive number
    tax_rate: float
    risk_free_rate: float
    currency: str = "USD"


def _row(df: pd.DataFrame | None, labels: list[str]) -> pd.Series | None:
    """First matching row of a yfinance statement, as an oldest -> newest series.

    Yahoo occasionally renames line items, so we try several labels.
    """
    if df is None or df.empty:
        return None
    for label in labels:
        if label in df.index:
            s = df.loc[label]
            if isinstance(s, pd.DataFrame):  # duplicate labels: take the first
                s = s.iloc[0]
            s = pd.to_numeric(s, errors="coerce").dropna()
            if not s.empty:
                return s.sort_index().astype(float)
    return None


def _latest(df: pd.DataFrame | None, labels: list[str], default: float = 0.0) -> float:
    s = _row(df, labels)
    return float(s.iloc[-1]) if s is not None else default


def get_risk_free_rate() -> float:
    """Latest 10-year US Treasury yield (^TNX is quoted in percent)."""
    import yfinance as yf

    try:
        hist = yf.Ticker("^TNX").history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1]) / 100
    except Exception:
        pass
    return DEFAULT_RISK_FREE


def fetch_company_data(ticker: str) -> CompanyData:
    import yfinance as yf

    ticker = ticker.upper().strip()
    t = yf.Ticker(ticker)

    try:
        info = t.info or {}
    except Exception:
        info = {}

    # --- Price -------------------------------------------------------------
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        hist = t.history(period="5d")
        if hist.empty:
            raise ValueError(f"No price data found for '{ticker}'. Check the ticker symbol.")
        price = float(hist["Close"].iloc[-1])

    # --- Shares ------------------------------------------------------------
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    if not shares:
        try:
            shares = t.fast_info["shares"]
        except Exception:
            shares = None
    if not shares:
        raise ValueError(f"Could not find shares outstanding for '{ticker}'.")

    # --- Financial statements ---------------------------------------------
    cf, bs, inc = t.cashflow, t.balance_sheet, t.income_stmt

    fcf = _row(cf, ["Free Cash Flow"])
    if fcf is None:
        ocf = _row(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        capex = _row(cf, ["Capital Expenditure", "Capital Expenditures"])
        if ocf is None or capex is None:
            raise ValueError(f"No cash-flow data available for '{ticker}'.")
        fcf = (ocf + capex).dropna()  # yfinance reports CapEx as a negative number

    revenue = _row(inc, ["Total Revenue", "Operating Revenue"])
    if revenue is None:
        revenue = pd.Series(dtype=float)

    total_debt = _latest(bs, ["Total Debt"])
    cash = _latest(bs, ["Cash Cash Equivalents And Short Term Investments",
                        "Cash And Cash Equivalents"])
    interest = abs(_latest(inc, ["Interest Expense", "Interest Expense Non Operating"]))

    pretax = _latest(inc, ["Pretax Income"])
    tax = _latest(inc, ["Tax Provision"])
    tax_rate = tax / pretax if pretax > 0 else DEFAULT_TAX_RATE
    tax_rate = min(max(tax_rate, 0.0), 0.35)

    return CompanyData(
        ticker=ticker,
        name=info.get("longName") or info.get("shortName") or ticker,
        price=float(price),
        shares_outstanding=float(shares),
        beta=float(info.get("beta") or 1.0),
        fcf_history=fcf,
        revenue_history=revenue,
        total_debt=total_debt,
        cash=cash,
        interest_expense=interest,
        tax_rate=tax_rate,
        risk_free_rate=get_risk_free_rate(),
        currency=info.get("currency") or "USD",
    )
