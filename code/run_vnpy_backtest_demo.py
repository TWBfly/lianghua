"""
run_vnpy_backtest_demo.py — 一键运行 vn.py CTA 策略高保真离散事件回测

使用方法：
python3 code/run_vnpy_backtest_demo.py --symbol AG_IDX --timeframe 15m --strategy tianji
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))
sys.path.append(str(PROJECT_ROOT / "strategies"))

from vnpy_data_adapter import VnpyDataAdapter, Interval, parse_symbol_exchange
from vnpy_backtest_runner import VnpyBacktestRunner
from vnpy_tianji_strategy import VnpyTianjiStrategy
from vnpy_zscore_strategy import VnpyZScoreStrategy
from symbol_strategies.decoupled_symbol_engines import SYMBOL_CONFIGS


def run_backtest(
    symbol: str = "AG_IDX",
    timeframe: str = "15m",
    strategy_type: str = "tianji",
    capital: float = 1_000_000.0
):
    print("=" * 80)
    print(f"📊 [vn.py 高保真离散事件回测] 品种: {symbol} | 周期: {timeframe} | 策略: {strategy_type.upper()}")
    print("=" * 80)

    adapter = VnpyDataAdapter()
    bars = adapter.load_futures_bars(symbol=symbol, timeframe=timeframe)

    if not bars:
        print(f"❌ 未在本地数据库找到 {symbol} ({timeframe}) 的 K 线数据！")
        return

    print(f"✅ 成功载入 {len(bars)} 根 {timeframe} 标准 BarData (区间: {bars[0].datetime} -> {bars[-1].datetime})")

    # 获取品种物理参数
    cfg = SYMBOL_CONFIGS.get(symbol, {})
    size = cfg.get("multiplier", 15.0)
    slippage = 1.0
    rate = 0.00005  # 万分之 0.5
    pricetick = 1.0

    std_sym, ex = parse_symbol_exchange(symbol)
    vt_symbol = f"{std_sym}.{ex.value}"

    # 初始化离散事件回测引擎
    runner = VnpyBacktestRunner(
        vt_symbol=vt_symbol,
        interval=Interval.MINUTE_15 if timeframe == "15m" else Interval.MINUTE_5,
        rate=rate,
        slippage=slippage,
        size=size,
        pricetick=pricetick,
        capital=capital
    )

    # 绑定策略
    if strategy_type.lower() == "zscore":
        runner.add_strategy(VnpyZScoreStrategy, {"entry_zscore": 2.0, "sl_atr_mult": 1.5, "fixed_size": 1.0})
    else:
        runner.add_strategy(VnpyTianjiStrategy, {"initial_stop_atr": 1.2, "trail_stop_atr": 2.5, "fixed_size": 1.0})

    runner.load_bars(bars)

    print("⏳ 正在运行离散事件撮合循环与每日盯市结算...")
    stats = runner.run_backtesting()

    print("\n" + "=" * 80)
    print("🏆 【vn.py 回测综合绩效评估报告】")
    print("=" * 80)
    print(f" 初始本金:          ¥{stats['initial_capital']:,.2f}")
    print(f" 期末净值:          ¥{stats['final_balance']:,.2f}")
    print(f" 累计净利润:        ¥{stats['total_net_pnl']:,.2f}")
    print(f" 累计收益率:        {stats['total_return_pct']}%")
    print(f" 最大回撤:          {stats['max_drawdown_pct']}%")
    print(f" 年化夏普比率:      {stats['sharpe_ratio']}")
    print(f" 总委托成交笔数:    {stats['total_trade_count']} 笔 (已平仓回合: {stats['closed_trade_count']})")
    print(f" 交易胜率:          {stats['win_rate_pct']}%")
    print(f" 盈亏比 (P/L Ratio): {stats['profit_loss_ratio']}")
    print(f" 累计手续费:        ¥{stats['total_commission']:,.2f}")
    print(f" 累计滑点磨损:      ¥{stats['total_slippage']:,.2f}")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="vn.py CTA Strategy Backtest Runner")
    parser.add_argument("--symbol", type=str, default="AG_IDX", help="合约品种代码 (如 AG_IDX, AU_IDX, RB_IDX)")
    parser.add_argument("--timeframe", type=str, default="15m", help="周期 (15m 或 5m)")
    parser.add_argument("--strategy", type=str, default="tianji", help="策略类型 (tianji 或 zscore)")
    parser.add_argument("--capital", type=float, default=1000000.0, help="初始资金")
    args = parser.parse_args()

    run_backtest(args.symbol, args.timeframe, args.strategy, args.capital)
