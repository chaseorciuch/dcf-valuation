"""Tests for the FactSet source using canned API responses (no network, no key)."""
import numpy as np
import pandas as pd
import pytest

from dcf import factset
from dcf.model import run_dcf


def fundamentals_rows():
    rows = []
    data = {  # values in millions, like FactSet returns them
        "FF_SALES":       [1000, 1100, 1210],
        "FF_OPER_CF":     [150, 170, 180],
        "FF_CAPEX":       [50, 60, 70],
        "FF_DEBT":        [300, 300, 300],
        "FF_CASH_ST":     [100, 110, 120],
        "FF_INT_EXP_NET": [12, 12, 12],
        "FF_INC_TAX":     [20, 21, 21],
        "FF_PTX_INC":     [100, 100, 100],
        "FF_COM_SHS_OUT": [10, 10, 10],
    }
    dates = ["2023-12-31", "2024-12-31", "2025-12-31"]
    for metric, values in data.items():
        for d, v in zip(dates, values):
            rows.append({"requestId": "TEST-US", "metric": metric, "fiscalEndDate": d,
                         "value": v, "currency": "USD"})
    return rows


def test_ticker_conversion():
    assert factset.to_factset_id("aapl") == "AAPL-US"
    assert factset.to_factset_id("VOD-GB") == "VOD-GB"


def test_build_company_data_scales_and_computes_fcf():
    f = factset.parse_fundamentals(fundamentals_rows())
    prices = factset.parse_prices([{"date": "2026-10-19", "price": 25.0},
                                   {"date": "2026-10-20", "price": 26.0}])
    d = factset.build_company_data("test", f, prices, beta=1.1, risk_free=0.04)

    assert d.price == 26.0
    assert d.shares_outstanding == 10e6
    assert d.fcf_history.iloc[-1] == pytest.approx(110e6)   # 180 - 70
    assert d.total_debt == 300e6 and d.cash == 120e6
    assert d.interest_expense == 12e6
    assert d.tax_rate == pytest.approx(0.21)
    assert d.revenue_history.iloc[0] == 1000e6

    r = run_dcf(d)
    assert r.value_per_share > 0


def test_negative_capex_sign_is_handled():
    rows = [r | ({"value": -r["value"]} if r["metric"] == "FF_CAPEX" else {})
            for r in fundamentals_rows()]
    f = factset.parse_fundamentals(rows)
    prices = factset.parse_prices([{"date": "2026-10-20", "price": 26.0}])
    d = factset.build_company_data("test", f, prices, beta=None, risk_free=0.04)
    assert d.fcf_history.iloc[-1] == pytest.approx(110e6)
    assert d.beta == 1.0


def test_beta_estimate():
    rng = np.random.default_rng(0)
    m = rng.normal(0.01, 0.04, 60)
    s = 1.5 * m + rng.normal(0, 0.005, 60)
    idx = pd.date_range("2021-01-31", periods=61, freq="ME")
    market = pd.Series(100 * np.cumprod(np.r_[1, 1 + m]), index=idx)
    stock = pd.Series(100 * np.cumprod(np.r_[1, 1 + s]), index=idx)
    assert factset.estimate_beta(stock, market) == pytest.approx(1.5, abs=0.1)


def test_missing_credentials(monkeypatch):
    monkeypatch.delenv("FACTSET_USERNAME", raising=False)
    monkeypatch.delenv("FACTSET_API_KEY", raising=False)
    monkeypatch.setattr(factset.os, "getenv", lambda k, d=None: None)
    with pytest.raises(factset.FactSetError):
        factset._credentials()
