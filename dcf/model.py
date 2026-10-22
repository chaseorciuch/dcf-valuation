"""Core discounted-cash-flow math. No network calls here, so it's easy to test."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import CompanyData

MAX_GROWTH = 0.40  # cap on year-1 growth so one boom year doesn't get extrapolated for a decade


@dataclass
class Assumptions:
    projection_years: int = 10
    hold_years: int = 3                   # years the initial growth rate is held before fading
    initial_growth: float | None = None   # None -> analyst estimate, else historical revenue CAGR
    use_analyst_growth: bool = True
    terminal_growth: float = 0.025        # long-run growth after the projection period
    equity_risk_premium: float = 0.055    # used in CAPM cost of equity
    adjust_beta: bool = True              # Blume adjustment: 0.67 x raw beta + 0.33
    wacc: float | None = None             # None -> computed from CAPM + cost of debt
    base_fcf_years: int = 1               # average the last N years of FCF as the starting point
    base_fcf: float | None = None         # override the starting FCF entirely


@dataclass
class WACCBreakdown:
    beta_used: float
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
    growth_source: str
    wacc: float
    wacc_breakdown: WACCBreakdown | None
    projections: pd.DataFrame
    terminal_value: float
    pv_terminal_value: float
    enterprise_value: float
    equity_value: float
    value_per_share: float
    current_price: float
    implied_growth: float | None = None   # reverse DCF: initial growth that justifies today's price
    market_ev_to_fcf: float = float("nan")
    terminal_ev_to_fcf: float = float("nan")
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

def blume_beta(raw: float) -> float:
    """Betas drift toward 1 over time; this is the adjustment Bloomberg reports."""
    return 0.67 * raw + 0.33


def compute_wacc(data: CompanyData, equity_risk_premium: float,
                 adjust_beta: bool = True) -> WACCBreakdown:
    """Weighted average cost of capital using market-value weights."""
    rf = data.risk_free_rate
    beta = blume_beta(data.beta) if adjust_beta else data.beta
    cost_of_equity = rf + beta * equity_risk_premium  # CAPM

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
        beta_used=beta,
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


def estimate_initial_growth(data: CompanyData, use_analyst: bool = True) -> tuple[float, str]:
    """Analyst revenue growth if available, else historical revenue CAGR, else FCF CAGR."""
    candidates = []
    if use_analyst:
        candidates.append((data.analyst_growth, "analyst estimate"))
    candidates += [(_cagr(data.revenue_history), "historical revenue CAGR"),
                   (_cagr(data.fcf_history), "historical FCF CAGR")]
    for g, source in candidates:
        if g is not None and np.isfinite(g):
            return float(np.clip(g, -0.05, MAX_GROWTH)), source
    return 0.05, "default"


def growth_path(initial: float, terminal: float, years: int, hold_years: int = 0) -> np.ndarray:
    """Hold the initial rate for `hold_years`, then fade linearly to the terminal rate."""
    hold = min(max(hold_years, 0), years - 1)
    fade = years - hold
    if fade == 1:
        tail = np.array([terminal]) if hold else np.array([initial])
    else:
        tail = np.linspace(initial, terminal, fade + (1 if hold else 0))[(1 if hold else 0):]
    return np.concatenate([np.full(hold, initial), tail])


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
                    shares: float, hold_years: int = 0) -> tuple[float, dict]:
    """Pure function used by the main model, the sensitivity tables and the reverse DCF."""
    if wacc <= terminal_growth:
        raise ValueError(f"WACC ({wacc:.2%}) must be greater than terminal growth "
                         f"({terminal_growth:.2%}).")

    growths = growth_path(initial_growth, terminal_growth, years, hold_years)
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


def solve_implied_growth(data: CompanyData, a: Assumptions, base_fcf: float, wacc: float,
                         lo: float = -0.20, hi: float = 1.00) -> float | None:
    """Reverse DCF: the initial growth rate at which value per share equals today's price."""
    def gap(g: float) -> float:
        v, _ = value_per_share(base_fcf, g, a.terminal_growth, wacc, a.projection_years,
                               data.total_debt, data.cash, data.shares_outstanding,
                               a.hold_years)
        return v - data.price

    f_lo, f_hi = gap(lo), gap(hi)
    if f_lo > 0 or f_hi < 0:
        return None  # price is outside what any growth rate in [lo, hi] can explain
    for _ in range(100):
        mid = (lo + hi) / 2
        if gap(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def run_dcf(data: CompanyData, a: Assumptions | None = None) -> DCFResult:
    a = a or Assumptions()

    base = starting_fcf(data, a)
    if base <= 0:
        raise ValueError(
            f"{data.ticker} has negative/zero starting free cash flow ({base:,.0f}). "
            "A standard DCF isn't meaningful here. Try --base-fcf-years 3 to smooth, "
            "or pass --base-fcf with your own estimate."
        )

    if a.initial_growth is not None:
        g0, source = a.initial_growth, "user input"
    else:
        g0, source = estimate_initial_growth(data, a.use_analyst_growth)

    breakdown = None
    if a.wacc is not None:
        wacc = a.wacc
    else:
        breakdown = compute_wacc(data, a.equity_risk_premium, a.adjust_beta)
        wacc = breakdown.wacc

    per_share, d = value_per_share(base, g0, a.terminal_growth, wacc, a.projection_years,
                                   data.total_debt, data.cash, data.shares_outstanding,
                                   a.hold_years)

    last = data.fcf_history.index[-1]
    last_year = int(last.year) if hasattr(last, "year") else 0
    years = [last_year + i if last_year else i for i in range(1, a.projection_years + 1)]
    projections = pd.DataFrame({
        "Year": years,
        "Growth": d["growths"],
        "FCF": d["fcfs"],
        "Discount factor": d["discount"],
        "PV of FCF": d["pv"],
    })

    market_ev = data.price * data.shares_outstanding + data.total_debt - data.cash

    return DCFResult(
        base_fcf=base,
        initial_growth=g0,
        growth_source=source,
        wacc=wacc,
        wacc_breakdown=breakdown,
        projections=projections,
        terminal_value=d["tv"],
        pv_terminal_value=d["pv_tv"],
        enterprise_value=d["ev"],
        equity_value=d["equity"],
        value_per_share=per_share,
        current_price=data.price,
        implied_growth=solve_implied_growth(data, a, base, wacc),
        market_ev_to_fcf=market_ev / base,
        terminal_ev_to_fcf=d["tv"] / d["fcfs"][-1],
    )
