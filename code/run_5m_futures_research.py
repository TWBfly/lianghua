"""
A-Share & Futures Quantitative Strategy - 5-Minute ML+PPO Research & Backtest Runner
【5 分钟期货机器学习 + PPO 策略全品种回测、参数寻优与报告生成器】
"""

import sys
import argparse
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_5m_symbol_engines import (
    SYMBOL_5M_CONFIGS,
    Decoupled5mSymbolStrategyRunner
)


def main():
    parser = argparse.ArgumentParser(description="5-Minute Futures ML+PPO Strategy Research Runner")
    parser.add_argument("--symbols", type=str, default="AG_IDX,AU_IDX,CU_IDX,RB_IDX,I_IDX,SC_IDX,SA_IDX,LC_IDX", help="以逗号分隔的品种代码，或 'all'")
    parser.add_argument("--mode", type=str, choices=["backtest", "optimize"], default="backtest", help="执行模式: backtest (回测) 或 optimize (参数优化)")
    parser.add_argument("--trials", type=int, default=15, help="寻优模式下的尝试次数")
    parser.add_argument("--capital", type=float, default=500000.0, help="初始回测资金 (元)")
    args = parser.parse_args()

    runner = Decoupled5mSymbolStrategyRunner()

    if args.symbols.lower() == "all":
        target_symbols = list(SYMBOL_5M_CONFIGS.keys())
    else:
        target_symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print("=" * 110)
    print(f"🚀 启动 5 分钟 (5m) 期货专属机器学习 (LightGBM) + PPO 执行策略")
    print(f"📌 模式: {args.mode.upper()} | 初始资金: {args.capital:,.2f} 元 | 目标品种数: {len(target_symbols)}")
    print("=" * 110)

    results = []

    for sym in target_symbols:
        if sym not in SYMBOL_5M_CONFIGS:
            print(f"⚠️ 跳过未配置的品种: {sym}")
            continue

        name = SYMBOL_5M_CONFIGS[sym]["name"]
        print(f"\n⚡ 正在执行 5m 策略处理: [{sym} | {name}]...")

        try:
            if args.mode == "backtest":
                res = runner.run_single_symbol_5m_backtest(sym, initial_capital=args.capital)
                results.append(res)
                print(f"   └─ 交易次数: {res['trades_count']:<3} | 胜率: {res['win_rate']:>5.1f}% | 盈亏比: {res['profit_factor']:>4.2f} | 夏普: {res['sharpe_ratio']:>5.2f} | 最大回撤: {res['max_drawdown_pct']:>4.2f}% | 收益率: {res['return_pct']:>+5.2f}%")
            elif args.mode == "optimize":
                opt_res = runner.optimize_5m_symbol(sym, n_trials=args.trials)
                best_m = opt_res["best_metrics"]
                if best_m:
                    results.append(best_m)
        except Exception as e:
            print(f"❌ 品种 [{sym}] 处理失败: {e}")

    if results:
        print("\n" + "=" * 110)
        print("📊 5 分钟 (5m) 各品种策略回测性能总排行榜 (对冲与滑点后真实收益)")
        print("=" * 110)

        df_summary = pd.DataFrame(results)[[
            "symbol", "name", "category", "trades_count", "win_rate", "profit_factor",
            "sharpe_ratio", "max_drawdown_pct", "total_pnl", "return_pct"
        ]]
        df_summary.columns = ["品种代码", "名称", "板块分类", "交易笔数", "胜率(%)", "盈亏比", "夏普比率", "最大回撤(%)", "总盈亏(元)", "收益率(%)"]
        df_summary = df_summary.sort_values(by="夏普比率", ascending=False)
        print(df_summary.to_string(index=False))
        print("=" * 110)

        valid_res = [r for r in results if r["trades_count"] > 0]
        if valid_res:
            avg_wr = sum(r["win_rate"] for r in valid_res) / len(valid_res)
            avg_pf = sum(r["profit_factor"] for r in valid_res) / len(valid_res)
            avg_sr = sum(r["sharpe_ratio"] for r in valid_res) / len(valid_res)
            total_profit = sum(r["total_pnl"] for r in valid_res)
            print(f"🎯 5m 组合综合表现: 平均胜率={avg_wr:.1f}% | 平均盈亏比={avg_pf:.2f} | 平均夏普={avg_sr:.2f} | 组合总盈利={total_profit:+,.2f} 元")
            print("=" * 110)


if __name__ == "__main__":
    main()
