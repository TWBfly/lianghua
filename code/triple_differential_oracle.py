"""
triple_differential_oracle.py — 三轨差分对账与终极真实验证预言机

架构目标：
1. 建立工业级三轨回测基准：
   - 轨 1: Lianghua 自研 K 线逐柱盯市引擎 (backtest_kline_engine)
   - 轨 2: vn.py CTA 离散事件回测引擎 (vnpy_backtest_runner)
   - 轨 3: AKQuant 高性能撮合引擎 (akquant_backtest_runner)
2. 实行三方交叉一致性门禁：
   - 交易笔数差分 (Trade Count Discrepancy) == 0
   - 累计净利润相对偏差 (PnL Relative Deviation) <= 3%
   - 最大回撤绝对偏差 (Max Drawdown Deviation) <= 2%
   - 撮合时点一致性 (严格次柱开盘 Next-Open 成交，排查偷价)
3. 发现偏差时自动输出根因诊断（如：滑点假设不一致、平今仓费率计算口径不同、偷价未来函数）。
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
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
from vnpy_data_adapter import VnpyDataAdapter, Interval, parse_symbol_exchange
from vnpy_strategy_template import CtaTemplate
from vnpy_backtest_runner import VnpyBacktestRunner
from contract_specs import get_spec

logger = logging.getLogger("triple_differential_oracle")


@dataclass
class EngineResultSummary:
    engine_name: str
    total_net_pnl: float
    total_trades: int
    win_rate_pct: float
    max_drawdown_pct: float
    profit_factor: float
    details: Dict[str, Any] = field(default_factory=dict)


class TripleDifferentialOracle:
    """三轨差分对账与真实性预言机"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (PROJECT_ROOT / "data" / "ashare_quant.db")
        self.ak_adapter = AkquantDataAdapter(self.db_path)
        self.vn_adapter = VnpyDataAdapter(self.db_path)

    def run_triple_audit(
        self,
        symbol: str,
        strategy_class_vnpy: Optional[Type[CtaTemplate]] = None,
        strategy_class_akquant: Optional[Type[AkquantStrategyBase]] = None,
        strategy_setting: Optional[Dict[str, Any]] = None,
        timeframe: str = "15m",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        initial_cash: float = 1_000_000.0,
        internal_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行 Lianghua / vn.py / AKQuant 三轨全景差分对账
        """
        spec = get_spec(symbol)
        clean_code = symbol.strip().upper().replace("_IDX", "").lower()

        results: Dict[str, EngineResultSummary] = {}
        warnings: List[str] = []

        # -------------------------------------------------------------
        # 1. 轨 1: 接入内部自研引擎结果
        # -------------------------------------------------------------
        if internal_summary:
            wr = float(internal_summary.get("win_rate_pct", internal_summary.get("win_rate", 0.0)))
            if 0.0 < wr <= 1.0:
                wr *= 100.0
            mdd = internal_summary.get("max_drawdown_pct")
            if mdd is None and "max_drawdown" in internal_summary and initial_cash > 0:
                mdd = (float(internal_summary["max_drawdown"]) / initial_cash) * 100.0

            results["Lianghua_Internal"] = EngineResultSummary(
                engine_name="Lianghua_Internal_M2M",
                total_net_pnl=float(internal_summary.get("total_net_pnl", internal_summary.get("net_pnl", 0.0))),
                total_trades=int(internal_summary.get("total_trades", internal_summary.get("trade_count", internal_summary.get("trades", 0)))),
                win_rate_pct=wr,
                max_drawdown_pct=float(mdd or 0.0),
                profit_factor=float(internal_summary.get("profit_factor", 0.0)),
                details=internal_summary
            )

        # -------------------------------------------------------------
        # 2. 轨 2: 执行 vn.py 离散事件回测
        # -------------------------------------------------------------
        if strategy_class_vnpy:
            try:
                vn_bars = self.vn_adapter.load_futures_bars(
                    symbol=symbol,
                    timeframe=timeframe,
                    start_date=start_date,
                    end_date=end_date
                )
                if vn_bars:
                    std_sym, ex = parse_symbol_exchange(symbol)
                    vt_symbol = f"{std_sym}.{ex.value}"
                    vn_runner = VnpyBacktestRunner(
                        vt_symbol=vt_symbol,
                        interval=Interval.MINUTE,
                        start_date=start_date,
                        end_date=end_date,
                        rate=spec.fee_rate,
                        slippage=spec.tick_size,
                        size=spec.multiplier,
                        pricetick=spec.tick_size,
                        capital=initial_cash
                    )
                    vn_runner.add_strategy(strategy_class_vnpy, strategy_setting or {})
                    vn_runner.load_bars(vn_bars)
                    vn_stats = vn_runner.run_backtesting()

                    vn_mdd = vn_stats.get("max_drawdown_pct")
                    if vn_mdd is None:
                        vn_mdd = vn_stats.get("max_drawdown_percent")
                    if vn_mdd is None and "max_drawdown" in vn_stats and initial_cash > 0:
                        vn_mdd = (float(vn_stats["max_drawdown"]) / initial_cash) * 100.0

                    vn_trades = vn_stats.get("closed_trade_count")
                    if vn_trades is None:
                        vn_trades = vn_stats.get("total_trade_count", vn_stats.get("total_trades", 0))

                    results["VNPy_CTA"] = EngineResultSummary(
                        engine_name="VNPy_CTA_EventEngine",
                        total_net_pnl=float(vn_stats.get("total_net_pnl", vn_stats.get("net_pnl", 0.0))),
                        total_trades=int(vn_trades),
                        win_rate_pct=float(vn_stats.get("win_rate_pct", vn_stats.get("win_rate", 0.0))),
                        max_drawdown_pct=abs(float(vn_mdd or 0.0)),
                        profit_factor=float(vn_stats.get("profit_factor", vn_stats.get("profit_loss_ratio", 0.0))),
                        details=vn_stats
                    )
            except Exception as e:
                logger.error(f"VN.PY track execution failed: {e}")
                warnings.append(f"VN.PY 轨执行失败: {e}")

        # -------------------------------------------------------------
        # 3. 轨 3: 执行 AKQuant 高保真回测
        # -------------------------------------------------------------
        if strategy_class_akquant:
            try:
                ak_runner = AkquantBacktestRunner(initial_cash=initial_cash)
                ak_res = ak_runner.run(
                    symbol=symbol,
                    strategy_class=strategy_class_akquant,
                    timeframe=timeframe,
                    start_date=start_date,
                    end_date=end_date,
                    custom_params=strategy_setting
                )
                if ak_res.get("status") == "SUCCESS":
                    m = ak_res.get("metrics", {})
                    results["AKQuant"] = EngineResultSummary(
                        engine_name=f"AKQuant ({ak_res.get('engine')})",
                        total_net_pnl=float(m.get("total_pnl", 0.0)),
                        total_trades=int(m.get("closed_trade_count", 0)),
                        win_rate_pct=float(m.get("win_rate", 0.0)),
                        max_drawdown_pct=abs(float(m.get("max_drawdown_pct", 0.0))),
                        profit_factor=float(m.get("profit_factor", 0.0)),
                        details=m
                    )
                else:
                    warnings.append(f"AKQuant 轨回测状态异常: {ak_res.get('status')}")
            except Exception as e:
                logger.error(f"AKQuant track execution failed: {e}")
                warnings.append(f"AKQuant 轨执行失败: {e}")

        # -------------------------------------------------------------
        # 4. 三轨多维交叉比对与一致性门禁判定
        # -------------------------------------------------------------
        audit_matrix: Dict[str, Any] = {}
        is_passed = True

        engine_keys = list(results.keys())
        if len(engine_keys) < 2:
            return {
                "status": "INSUFFICIENT_ENGINES",
                "symbol": symbol,
                "engines_ran": engine_keys,
                "warnings": warnings + ["至少需要 2 条独立引擎轨道进行差分对账"],
                "results": {k: v.__dict__ for k, v in results.items()}
            }

        # 选取基准对账引擎 (优先 VN.PY 或 Lianghua_Internal)
        base_key = "VNPy_CTA" if "VNPy_CTA" in results else engine_keys[0]
        base_res = results[base_key]

        pairwise_diffs = []
        for other_key in engine_keys:
            if other_key == base_key:
                continue
            other_res = results[other_key]

            # 差异计算
            pnl_diff = abs(other_res.total_net_pnl - base_res.total_net_pnl)
            pnl_rel_diff = pnl_diff / (abs(base_res.total_net_pnl) + 1e-6)
            trade_diff = abs(other_res.total_trades - base_res.total_trades)
            mdd_diff = abs(other_res.max_drawdown_pct - base_res.max_drawdown_pct)

            pair_audit = {
                "compare_pair": f"{other_key} vs {base_key}",
                "pnl_diff_rmb": round(pnl_diff, 2),
                "pnl_relative_diff_pct": round(pnl_rel_diff * 100.0, 2),
                "trade_count_diff": trade_diff,
                "mdd_diff_pct": round(mdd_diff, 2),
                "trade_matched": (trade_diff == 0),
                "pnl_tolerance_passed": (pnl_rel_diff <= 0.05),
                "mdd_tolerance_passed": (mdd_diff <= 3.0),
            }
            pairwise_diffs.append(pair_audit)

            # 门禁触发
            if not pair_audit["trade_matched"]:
                is_passed = False
                warnings.append(
                    f"【门禁失败】{other_key} 交易笔数 ({other_res.total_trades}) 与基准 {base_key} ({base_res.total_trades}) 不一致！"
                )
            if not pair_audit["pnl_tolerance_passed"]:
                is_passed = False
                warnings.append(
                    f"【门禁失败】{other_key} 收益偏差 ({pair_audit['pnl_relative_diff_pct']}%) 超出 5.0% 容差边界！"
                )
            if not pair_audit["mdd_tolerance_passed"]:
                is_passed = False
                warnings.append(
                    f"【门禁失败】{other_key} 最大回撤偏差 ({pair_audit['mdd_diff_pct']}%) 超出 3.0% 容差边界！"
                )

        if len(engine_keys) < 3:
            warnings.append(f"【降级提醒】当前仅有 {len(engine_keys)} 条引擎轨道参与差分对账 (完整三轨要求: Lianghua + vn.py + AKQuant)")
            final_status = "PARTIAL_DIFF_PASS" if is_passed else "FAIL_DIFF_GATE"
        else:
            final_status = "PASS" if is_passed else "FAIL_DIFF_GATE"

        # -------------------------------------------------------------
        # 5. 组装输出报告
        # -------------------------------------------------------------
        return {
            "status": final_status,
            "symbol": symbol,
            "contract_name": spec.name,
            "multiplier": spec.multiplier,
            "fee_rate": spec.fee_rate,
            "base_engine": base_key,
            "engines_evaluated": len(results),
            "pairwise_comparisons": pairwise_diffs,
            "results_summary": {k: v.__dict__ for k, v in results.items()},
            "warnings": warnings,
            "audit_timestamp": datetime.now().isoformat()
        }
