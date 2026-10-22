"""Pull DCF inputs from FactSet's REST APIs (Fundamentals v2 + Prices v1).

Needs a FactSet API key. Put these in a `.env` file in the project folder
(see `.env.example`) or set them as environment variables:

    FACTSET_USERNAME=USERNAME-SERIAL
    FACTSET_API_KEY=your-api-key

The 10-year Treasury yield still comes from Yahoo Finance (^TNX), since it
isn't part of these two FactSet APIs.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .data import DEFAULT_TAX_RATE, CompanyData, get_analyst_growth, get_risk_free_rate

BASE = "https://api.factset.com/content"
FUNDAMENTALS_URL = f"{BASE}/factset-fundamentals/v2/fundamentals"
PRICES_URL = f"{BASE}/factset-prices/v1/prices"
MARKET_PROXY = "SPY-US"  # S&P 500 ETF, used to estimate beta

METRICS = [
    "FF_SALES",        # revenue
    "FF_OPER_CF",      # operating cash flow
    "FF_CAPEX",        # capital expenditures
    "FF_DEBT",         # total debt
    "FF_CASH_ST",      # cash & short-term investments
    "FF_INT_EXP_NET",  # interest expense
    "FF_INC_TAX",      # income taxes
    "FF_PTX_INC",      # pretax income
    "FF_COM_SHS_OUT",  # common shares outstanding
]


class FactSetError(ValueError):
    pass


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _credentials() -> tuple[str, str]:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    user = os.getenv("FACTSET_USERNAME")
    key = os.getenv("FACTSET_API_KEY")
    if not user or not key:
        raise FactSetError(
            "FactSet credentials not found. Copy .env.example to .env and fill in "
            "FACTSET_USERNAME (your USERNAME-SERIAL) and FACTSET_API_KEY."
        )
    return user, key


def _get(url: str, params: dict, auth: tuple[str, str]) -> list[dict]:
    import requests

    r = requests.get(url, params=params, auth=auth, timeout=30)
    if r.status_code == 401:
        raise FactSetError("FactSet rejected your credentials (401). Check the "
                           "username-serial and API key in your .env file.")
    if r.status_code == 403:
        raise FactSetError("FactSet says you're not entitled to this API (403). Your "
                           "school's subscription may not include API access to "
                           f"{url.split('/content/')[1].split('/')[0]}.")
    if not r.ok:
        raise FactSetError(f"FactSet request failed ({r.status_code}): {r.text[:300]}")
    return r.json().get("data", [])


def to_factset_id(ticker: str) -> str:
    """AAPL -> AAPL-US. Tickers that already have a region suffix are left alone."""
    t = ticker.upper().strip()
    return t if "-" in t else f"{t}-US"


# ---------------------------------------------------------------------------
# Parsing (kept separate from HTTP so it can be unit tested)
# ---------------------------------------------------------------------------

def parse_fundamentals(rows: list[dict]) -> pd.DataFrame:
    """Rows of {metric, fiscalEndDate, value, ...} -> DataFrame (index = fiscal end date)."""
    records = [
        {"date": r.get("fiscalEndDate"), "metric": r.get("metric"), "value": r.get("value"),
         "currency": r.get("currency")}
        for r in rows if r.get("value") is not None and r.get("fiscalEndDate")
    ]
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    wide = df.pivot_table(index="date", columns="metric", values="value", aggfunc="last")
    wide.attrs["currency"] = df["currency"].dropna().iloc[-1] if df["currency"].notna().any() else None
    return wide.sort_index()


def parse_prices(rows: list[dict]) -> pd.Series:
    s = pd.Series(
        {pd.to_datetime(r["date"]): r["price"] for r in rows
         if r.get("price") is not None and r.get("date")},
        dtype=float,
    )
    return s.sort_index()


def estimate_beta(stock: pd.Series, market: pd.Series) -> float | None:
    """Beta from monthly returns: cov(stock, market) / var(market)."""
    rets = pd.concat([stock.pct_change(), market.pct_change()], axis=1).dropna()
    if len(rets) < 24:
        return None
    cov = np.cov(rets.iloc[:, 0], rets.iloc[:, 1])
    return float(cov[0, 1] / cov[1, 1])


def build_company_data(ticker: str, fundamentals: pd.DataFrame, prices: pd.Series,
                       beta: float | None, risk_free: float) -> CompanyData:
    if fundamentals.empty:
        raise FactSetError(f"FactSet returned no fundamentals for '{ticker}'.")
    if prices.empty:
        raise FactSetError(f"FactSet returned no prices for '{ticker}'.")

    f = fundamentals

    def col(name: str) -> pd.Series:
        return f[name].dropna() if name in f else pd.Series(dtype=float)

    def latest(name: str, default: float = 0.0) -> float:
        s = col(name)
        return float(s.iloc[-1]) if not s.empty else default

    ocf, capex = col("FF_OPER_CF"), col("FF_CAPEX")
    if ocf.empty or capex.empty:
        raise FactSetError(f"FactSet has no cash-flow data for '{ticker}'.")
    fcf = (ocf - capex.abs()).dropna()  # works whether CapEx is reported + or -

    shares = latest("FF_COM_SHS_OUT")
    if shares <= 0:
        raise FactSetError(f"FactSet has no shares outstanding for '{ticker}'.")

    # FactSet reports money and share counts in millions. Scale everything to units
    # so output matches the Yahoo source. (The valuation itself is unaffected.)
    scale = 1e6 if shares < 1e6 else 1.0

    pretax, tax = latest("FF_PTX_INC"), latest("FF_INC_TAX")
    tax_rate = tax / pretax if pretax > 0 else DEFAULT_TAX_RATE

    return CompanyData(
        ticker=ticker.upper(),
        name=ticker.upper(),
        price=float(prices.iloc[-1]),
        shares_outstanding=shares * scale,
        beta=beta if beta is not None else 1.0,
        fcf_history=fcf * scale,
        revenue_history=col("FF_SALES") * scale,
        total_debt=latest("FF_DEBT") * scale,
        cash=latest("FF_CASH_ST") * scale,
        interest_expense=abs(latest("FF_INT_EXP_NET")) * scale,
        tax_rate=min(max(tax_rate, 0.0), 0.35),
        risk_free_rate=risk_free,
        currency=fundamentals.attrs.get("currency") or "USD",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_company_data_factset(ticker: str) -> CompanyData:
    auth = _credentials()
    fid = to_factset_id(ticker)
    today = date.today()

    fundamentals = parse_fundamentals(_get(FUNDAMENTALS_URL, {
        "ids": fid,
        "metrics": ",".join(METRICS),
        "periodicity": "ANN",
        "fiscalPeriodStart": (today - timedelta(days=365 * 6)).isoformat(),
        "fiscalPeriodEnd": today.isoformat(),
        "currency": "LOCAL",
    }, auth))

    recent = parse_prices(_get(PRICES_URL, {
        "ids": fid,
        "startDate": (today - timedelta(days=14)).isoformat(),
        "endDate": today.isoformat(),
        "frequency": "D",
    }, auth))

    beta = None
    try:
        monthly = {}
        for sid in (fid, MARKET_PROXY):
            monthly[sid] = parse_prices(_get(PRICES_URL, {
                "ids": sid,
                "startDate": (today - timedelta(days=365 * 5)).isoformat(),
                "endDate": today.isoformat(),
                "frequency": "M",
            }, auth))
        beta = estimate_beta(monthly[fid], monthly[MARKET_PROXY])
    except FactSetError:
        pass  # fall back to beta = 1.0

    data = build_company_data(ticker, fundamentals, recent, beta, get_risk_free_rate())

    # FactSet's fundamentals API doesn't return the company name or analyst
    # estimates (those are separate FactSet products); borrow them from Yahoo.
    data.analyst_growth = get_analyst_growth(ticker)
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        data.name = info.get("longName") or info.get("shortName") or data.name
    except Exception:
        pass
    return data
