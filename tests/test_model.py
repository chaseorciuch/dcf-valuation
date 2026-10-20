"""Unit tests using a made-up company, so no internet connection is needed."""
import math

import pandas as pd
import pytest

from dcf.data import CompanyData
from dcf.model import Assumptions, estimate_initial_growth, growth_path, run_dcf
from dcf.sensitivity import wacc_vs_initial_growth, wacc_vs_terminal_growth


def fake_company(**overrides) -> CompanyData:
    years = pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"])
    base = dict(
        ticker="TEST",
        name="Test Corp",
        price=50.0,
        shares_outstanding=100.0,
        beta=1.2,
        fcf_history=pd.Series([80.0, 90.0, 95.0, 100.0], index=years),
        revenue_history=pd.Series([1000.0, 1100.0, 1210.0, 1331.0], index=years),
        total_debt=200.0,
        cash=50.0,
        interest_expense=0.0,
        tax_rate=0.21,
        risk_free_rate=0.04,
    )
    base.update(overrides)
    return CompanyData(**base)


def test_growth_estimate_is_revenue_cagr():
    assert estimate_initial_growth(fake_company()) == pytest.approx(0.10)


def test_growth_fades_to_terminal():
    path = growth_path(0.10, 0.02, 5)
    assert path[0] == pytest.approx(0.10)
    assert path[-1] == pytest.approx(0.02)


def test_dcf_matches_hand_calculation():
    # 2-year projection, fixed 10% WACC, growth 10% -> 2%, base FCF 100
    data = fake_company()
    a = Assumptions(projection_years=2, initial_growth=0.10, terminal_growth=0.02, wacc=0.10)
    r = run_dcf(data, a)

    fcf1, fcf2 = 110.0, 110.0 * 1.02
    tv = fcf2 * 1.02 / (0.10 - 0.02)
    ev = fcf1 / 1.10 + fcf2 / 1.10**2 + tv / 1.10**2
    equity = ev - 200 + 50
    assert r.enterprise_value == pytest.approx(ev)
    assert r.value_per_share == pytest.approx(equity / 100)
    assert r.upside == pytest.approx(equity / 100 / 50 - 1)


def test_capm_wacc():
    data = fake_company()
    r = run_dcf(data, Assumptions(equity_risk_premium=0.05))
    ke = 0.04 + 1.2 * 0.05
    kd = (0.04 + 0.015) * (1 - 0.21)
    we, wd = 5000 / 5200, 200 / 5200
    assert r.wacc == pytest.approx(we * ke + wd * kd)


def test_negative_fcf_raises():
    years = pd.to_datetime(["2024-12-31", "2025-12-31"])
    data = fake_company(fcf_history=pd.Series([-10.0, -5.0], index=years))
    with pytest.raises(ValueError):
        run_dcf(data)


def test_wacc_below_terminal_growth_raises():
    with pytest.raises(ValueError):
        run_dcf(fake_company(), Assumptions(wacc=0.02, terminal_growth=0.03))


def test_sensitivity_center_equals_base_case():
    data = fake_company()
    a = Assumptions()
    r = run_dcf(data, a)
    tg = wacc_vs_terminal_growth(data, a, r)
    g = wacc_vs_initial_growth(data, a, r)
    assert tg.iloc[2, 2] == pytest.approx(r.value_per_share)
    assert g.iloc[2, 2] == pytest.approx(r.value_per_share)
    # higher discount rate -> lower value
    assert tg.iloc[0, 2] > tg.iloc[-1, 2]
    assert not math.isnan(tg.iloc[0, 0])
