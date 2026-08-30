"""
strategies/island_orthogonal_portfolio_strategy.py — 「多物种岛屿正交对冲正反馈策略」
(Multi-Species Island Orthogonal Portfolio Strategy)

由 AutoQuant 分群自进化系统 50 代进化生成：
1. 趋势单边岛 (AG, LC, SN, AU, CU)：
   - DSP = (4, 16), Channel = 16, Trail = 2.5 * ATR
2. 基差均值岛 (RB, TA, MA, SC, P)：
   - Filter = 18, DevEntry = 2.0 * ATR, Hard SL = 0.8 * ATR
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd

STRATEGY_NAME = "island_orthogonal_portfolio_strategy"
TREND_UNIVERSE = ['AG_IDX', 'LC_IDX', 'SN_IDX', 'AU_IDX', 'CU_IDX']
REVERT_UNIVERSE = ['RB_IDX', 'TA_IDX', 'MA_IDX', 'SC_IDX', 'P_IDX']
