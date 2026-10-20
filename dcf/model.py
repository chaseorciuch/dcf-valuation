"""Core discounted-cash-flow math. No network calls here, so it's easy to test."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import CompanyData


@dataclass
class Assumptions:
    projection_years: int = 5
    initial_growth: float | None = None   # None -> estimated from revenue history
    terminal_growth: float = 0.025        # long-run growth after the projection period
    equity_risk_premium: float = 0.055    # used in CAPM cost of equity
    wacc: float | None = None             # None -> computed from CAPM + cost of debt
    base_fcf_years: int = 1               # average the last N years of FCF as the starting point
    base_fcf: float | None = None         # override the starting FCF entirely


@dataclass
class WACCBreakdown:
    cost_of_equity: float
    pre_tax_cost_of_debt: float
    after_tax_cost_of_debt: float
    weight_equity: float
    weight_debt: float
    wacc: float


@dataclass
class DCFResult:
    base_fcf: float
    initial_growth: float
    wacc: float
    wacc_breakdown: WACCBreakdown | None
    projections: pd.DataFrame
    terminal_value: float
    pv_terminal_value: float
    enterprise_value: float
    equity_value: float
    value_per_share: float
    current_price: float
    upside: float = field(init=False)
    terminal_share_of_ev: float = field(init=False)

    def __post_init__(self):
        self.upside = self.value_per_share / self.current_price - 1
        self.terminal_share_of_ev = (
            self.pv_terminal_value / self.enterprise_value if self.enterprise_value else float("nan")
        )


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def compute_wacc(data: CompanyData, equity_risk_premium: float) -> WACCBreakdown:
    """Weighted average cost of capital using market-value weights."""
    rf = data.risk_free_rate
    cost_of_equity = rf + data.beta * equity_risk_premium  # CAPM

    if data.total_debt > 0 and data.interest_expense > 0:
        kd = data.interest_expense / data.total_debt
        kd = min(max(kd, rf), 0.15)   # keep implied rate in a sane range
    else:
        kd = rf + 0.015               # simple spread if interest data is missing
    kd_after_tax = kd * (1 - data.tax_rate)

    equity_value = data.price * data.shares_outstanding
    debt_value = max(data.total_debt, 0.0)
    total = equity_value + debt_value
    we, wd = equity_value / total, debt_value / total

    return WACCBreakdown(
        cost_of_equity=cost_of_equity,
        pre_tax_cost_of_debt=kd,
        after_tax_cost_of_debt=kd_after_tax,
        weight_equity=we,
        weight_debt=wd,
        wacc=we * cost_of_equity + wd * kd_after_tax,
    )


def _cagr(series: pd.Series) -> float | None:
    s = series.dropna()
    if len(s) < 2 or s.iloc[0] <= 0 or s.iloc[-1] <= 0:
        return None
    years = len(s) - 1
    return (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1


def estimate_initial_growth(data: CompanyData) -> float:
    """Historical revenue CAGR (falls back to FCF CAGR), clipped to -5%..20%."""
    g = _cagr(data.revenue_history)
    if g is None:
        g = _cagr(data.fcf_history)
    if g is None:
        g = 0.05
    return float(np.clip(g, -0.05, 0.20))


def growth_path(initial: float, terminal: float, years: int) -> np.ndarray:
    """Growth fades linearly from the initial rate to the terminal rate."""
    if years == 1:
        return np.array([initial])
    return np.linspace(initial, terminal, years)


def starting_fcf(data: CompanyData, a: Assumptions) -> float:
    """Approximate unlevered FCF: levered FCF + after-tax interest."""
    if a.base_fcf is not None:
        return a.base_fcf
    levered = float(data.fcf_history.iloc[-a.base_fcf_years:].mean())
    return levered + data.interest_expense * (1 - data.tax_rate)


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------

def value_per_share(base_fcf: float, initial_growth: float, terminal_growth: float,
                    wacc: float, years: int, total_debt: float, cash: float,
                    shares: float) -> tuple[float, dict]:
    """Pure function used by both the main model and the sensitivity tables."""
    if wacc <= terminal_growth:
        raise ValueError(f"WACC ({wacc:.2%}) must be greater than terminal growth "
                         f"({terminal_growth:.2%}).")

    growths = growth_path(initial_growth, terminal_growth, years)
    fcfs = base_fcf * np.cumprod(1 + growths)
    t = np.arange(1, years + 1)
    discount = 1 / (1 + wacc) ** t
    pv = fcfs * discount

    tv = fcfs[-1] * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_tv = tv * discount[-1]
    ev = pv.sum() + pv_tv
    equity = ev - total_debt + cash

    detail = dict(growths=growths, fcfs=fcfs, discount=discount, pv=pv,
                  tv=tv, pv_tv=pv_tv, ev=ev, equity=equity)
    return equity / shares, detail


def run_dcf(data: CompanyData, a: Assumptions | None = None) -> DCFResult:
    a = a or Assumptions()

    base = starting_fcf(data, a)
    if base <= 0:
        raise ValueError(
            f"{data.ticker} has negative/zero starting free cash flow ({base:,.0f}). "
            "A standard DCF isn't meaningful here. Try --base-fcf-years 3 to smooth, "
            "or pass --base-fcf with your own estimate."
        )

    g0 = a.initial_growth if a.initial_growth is not None else estimate_initial_growth(data)

    breakdown = None
    if a.wacc is not None:
        wacc = a.wacc
    else:
        breakdown = compute_wacc(data, a.equity_risk_premium)
        wacc = breakdown.wacc

    per_share, d = value_per_share(base, g0, a.terminal_growth, wacc, a.projection_years,
                                   data.total_debt, data.cash, data.shares_outstanding)

    last_year = int(data.fcf_history.index[-1].year) if hasattr(data.fcf_history.index[-1], "year") else 0
    years = [last_year + i if last_year else i for i in range(1, a.projection_years + 1)]
    projections = pd.DataFrame({
        "Year": years,
        "Growth": d["growths"],
        "FCF": d["fcfs"],
        "Discount factor": d["discount"],
        "PV of FCF": d["pv"],
    })

    return DCFResult(
        base_fcf=base,
        initial_growth=g0,
        wacc=wacc,
        wacc_breakdown=breakdown,
        projections=projections,
        terminal_value=d["tv"],
        pv_terminal_value=d["pv_tv"],
        enterprise_value=d["ev"],
        equity_value=d["equity"],
        value_per_share=per_share,
        current_price=data.price,
    )
