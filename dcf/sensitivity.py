"""Sensitivity tables: how intrinsic value per share moves as key inputs change."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import CompanyData
from .model import Assumptions, DCFResult, value_per_share


def _grid(center: float, step: float, n_each_side: int) -> np.ndarray:
    # No rounding: the middle cell must equal the base case exactly.
    return center + step * np.arange(-n_each_side, n_each_side + 1)


def wacc_vs_terminal_growth(data: CompanyData, a: Assumptions, result: DCFResult,
                            wacc_step: float = 0.005, tg_step: float = 0.005,
                            n: int = 2) -> pd.DataFrame:
    """Rows = WACC, columns = terminal growth, cells = value per share."""
    waccs = _grid(result.wacc, wacc_step, n)
    tgs = _grid(a.terminal_growth, tg_step, n)
    table = pd.DataFrame(index=waccs, columns=tgs, dtype=float)
    for w in waccs:
        for g in tgs:
            if w <= g:
                table.loc[w, g] = np.nan
                continue
            v, _ = value_per_share(result.base_fcf, result.initial_growth, g, w,
                                   a.projection_years, data.total_debt, data.cash,
                                   data.shares_outstanding, a.hold_years)
            table.loc[w, g] = v
    table.index.name = "WACC"
    table.columns.name = "Terminal growth"
    return table


def wacc_vs_initial_growth(data: CompanyData, a: Assumptions, result: DCFResult,
                           wacc_step: float = 0.005, g_step: float = 0.02,
                           n: int = 2) -> pd.DataFrame:
    """Rows = WACC, columns = initial (year-1) growth, cells = value per share."""
    waccs = _grid(result.wacc, wacc_step, n)
    gs = _grid(result.initial_growth, g_step, n)
    table = pd.DataFrame(index=waccs, columns=gs, dtype=float)
    for w in waccs:
        for g in gs:
            if w <= a.terminal_growth:
                table.loc[w, g] = np.nan
                continue
            v, _ = value_per_share(result.base_fcf, g, a.terminal_growth, w,
                                   a.projection_years, data.total_debt, data.cash,
                                   data.shares_outstanding, a.hold_years)
            table.loc[w, g] = v
    table.index.name = "WACC"
    table.columns.name = "Initial growth"
    return table
