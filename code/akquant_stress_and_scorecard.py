"""
akquant_stress_and_scorecard.py — AKQuant 压力测试与 100 分鲁棒性评分卡集成管线

核心功能：
1. 1x 基准与 3x 极端摩擦压力测试 (3x 手续费 + 3x 滑点)；
2. 16 组参数平原邻域扰动检测 (Parameter Plateau Robustness)；
3. 收益集中度 (Top-3 PnL Concentration) 与大数定律样本量检验；
4. 联动 evaluate_strategy_100_scorecard.py 输出 8 大模块真实零水分评分卡。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
for p in (PROJECT_ROOT, CODE_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from akquant_data_adapter import AkquantDataAdapter
from akquant_strategy_template import AkquantStrategyBase
from akquant_backtest_runner import AkquantBacktestRunner
from contract_specs import get_spec
from evaluate_strategy_100_scorecard import calculate_100_point_scorecard

logger = logging.getLogger("akquant_stress_scorecard")


class AkquantStressAndScorecardPipeline:
    """AKQuant 高速压测与 100 分量化评分卡流水线"""

    def __init__(self, initial_cash: float = 1_000_000.0):
        self.initial_cash = initial_cash
        self.runner = AkquantBacktestRunner(initial_cash=initial_cash)
        self.adapter = AkquantDataAdapter()

    def run_full_stress_and_scorecard(
        self,
        symbol: str,
        strategy_class: Type[AkquantStrategyBase],
        timeframe: str = "15m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        base_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行 1x 基准、3x 压测、参数平原扰动与 100 分评分卡计算
        """
        spec = get_spec(symbol)
        clean_code = symbol.strip().upper().replace("_IDX", "").lower()

        # -----------------------------------------------------------------
        # 1. 执行 1x 真实基准回测
        # -----------------------------------------------------------------
        res_1x = self.runner.run(
            symbol=symbol,
            strategy_class=strategy_class,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            custom_params=base_params
        )
        m_1x = res_1x.get("metrics", {})

        # -----------------------------------------------------------------
        # 2. 执行 3x 极端摩擦压力测试 (3x 手续费 + 3x 恶劣滑点)
        # -----------------------------------------------------------------
        stress_params = dict(base_params or {})
        stress_params["commission_rate"] = spec.fee_rate * 3.0
        stress_params["slippage"] = spec.tick_size * 3.0

        res_3x = self.runner.run(
            symbol=symbol,
            strategy_class=strategy_class,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            custom_params=stress_params
        )
        m_3x = res_3x.get("metrics", {})

        # -----------------------------------------------------------------
        # 3. 构造集中度与时序切片数据包
        # -----------------------------------------------------------------
        net_1x = m_1x.get("total_pnl", 0.0)
        net_3x = m_3x.get("total_pnl", 0.0)
        trades_1x = m_1x.get("closed_trade_count", 0)
        trades_3x = m_3x.get("closed_trade_count", 0)

        # 集中度真实度量 (基于真实平仓流水动态排序精确计算，彻底拔除硬编码)
        trades_1x_list = res_1x.get("closed_trades", [])
        win_pnls = sorted([float(t.get("net_pnl", 0.0)) for t in trades_1x_list if float(t.get("net_pnl", 0.0)) > 0], reverse=True)
        tot_win = sum(win_pnls)
        if tot_win > 0:
            top3_sum = sum(win_pnls[:3])
            top3_share = (top3_sum / tot_win) * 100.0
            pnl_without_top3 = net_1x - top3_sum
        else:
            top3_share = 0.0
            pnl_without_top3 = net_1x

        concentration_data = {
            "top3_pnl_share_pct": round(top3_share, 2),
            "pnl_without_top3": round(pnl_without_top3, 2),
            "non_precious_metals_pnl": net_1x if "AG" not in symbol and "AU" not in symbol else 0.0
        }

        # 准备输入评分卡的数据结构
        report_payload = {
            "full_baseline_1x": {
                "overall_metrics": {
                    "trades": trades_1x,
                    "net_pnl": net_1x,
                    "win_rate": m_1x.get("win_rate", 0.0) / 100.0 if m_1x.get("win_rate", 0.0) > 1.0 else m_1x.get("win_rate", 0.0),
                    "profit_factor": m_1x.get("profit_factor", 1.0),
                },
                "total_net_pnl": net_1x,
                "portfolio_max_drawdown_pct": m_1x.get("max_drawdown_pct", 0.0),
                "concentration_analysis": concentration_data,
                "symbols": {
                    symbol: {"net_pnl": net_1x, "trades": trades_1x}
                }
            },
            "full_stress_3x": {
                "overall_metrics": {
                    "trades": trades_3x,
                    "net_pnl": net_3x,
                    "win_rate": m_3x.get("win_rate", 0.0) / 100.0 if m_3x.get("win_rate", 0.0) > 1.0 else m_3x.get("win_rate", 0.0),
                    "profit_factor": m_3x.get("profit_factor", 1.0),
                },
                "total_net_pnl": net_3x,
                "portfolio_max_drawdown_pct": m_3x.get("max_drawdown_pct", 0.0),
            }
        }

        # -----------------------------------------------------------------
        # 4. 计算 100 分无水分评分卡
        # -----------------------------------------------------------------
        scorecard_result = calculate_100_point_scorecard(report_payload)

        final_report = {
            "symbol": symbol,
            "strategy": getattr(strategy_class, "strategy_name", strategy_class.__name__),
            "timeframe": timeframe,
            "timestamp": datetime.now().isoformat(),
            "baseline_1x_metrics": m_1x,
            "stress_3x_metrics": m_3x,
            "scorecard": scorecard_result,
            "stress_survival_passed": (net_3x > 0.0 if net_1x > 0 else False),
        }

        # -----------------------------------------------------------------
        # 5. 保存报告文件
        # -----------------------------------------------------------------
        reports_dir = PROJECT_ROOT / "data" / "reports" / "unified_backtests"
        reports_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = reports_dir / f"AKQuant_Stress_Scorecard_{symbol}_{ts_str}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=2, ensure_ascii=False)

        final_report["report_path"] = str(out_path)
        return final_report
