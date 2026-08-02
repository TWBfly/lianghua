"""Export validated A-share daily bars for an MT5 custom symbol."""

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3

import pandas as pd

from ashare_data_engine import AShareDataEngine, DB_PATH
from market_data import MarketDataError, validate_daily_bars
from strategy_signal_library import supertrend_signal


def load_bars(db_path, symbol, end_date):
    with sqlite3.connect(db_path) as conn:
        frame = pd.read_sql_query("""
            SELECT symbol, trade_date, open, close, high, low,
                   volume, amount
            FROM stock_daily
            WHERE symbol=? AND trade_date<=?
            ORDER BY trade_date
        """, conn, params=(str(symbol), str(end_date)))
    if frame.empty:
        raise MarketDataError(f"no daily bars for {symbol}")
    return validate_daily_bars(frame, str(symbol))


def _atomic_csv(frame, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(target)


def export_symbol(db_path, symbol, output_dir, end_date):
    bars = load_bars(db_path, symbol, end_date)
    volume = bars["volume"].round().astype("int64").clip(lower=1)
    mt5 = pd.DataFrame({
        "Date": bars["trade_date"].dt.strftime("%Y.%m.%d"),
        "Time": "09:30:00",
        "Open": bars["open"],
        "High": bars["high"],
        "Low": bars["low"],
        "Close": bars["close"],
        "TickVolume": volume,
        "Volume": volume,
        "Spread": 0,
    })
    signal_frame = bars.copy()
    signal_frame.index = pd.DatetimeIndex(bars["trade_date"])
    signals = pd.DataFrame({
        "Date": signal_frame.index.strftime("%Y.%m.%d"),
        "Direction": supertrend_signal(
            signal_frame, period=10, multiplier=3.0
        ).astype(int).to_numpy(),
    })

    output = Path(output_dir)
    bars_path = output / f"lianghua_{symbol}_bars.csv"
    signals_path = output / f"lianghua_{symbol}_signals.csv"
    _atomic_csv(mt5, bars_path)
    _atomic_csv(signals, signals_path)
    return {
        "bars_path": bars_path,
        "signals_path": signals_path,
        "row_count": len(mt5),
        "first_date": mt5.iloc[0]["Date"],
        "last_date": mt5.iloc[-1]["Date"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--symbol", default="603986")
    parser.add_argument("--end-date", default="2026-07-28")
    parser.add_argument("--output-dir", default="mt5/exports")
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()

    if args.sync:
        summary = AShareDataEngine(args.db).sync_stock_daily(
            [args.symbol],
            start_date="20200101",
            end_date=datetime.now().strftime("%Y%m%d"),
        )
        if summary["failed"]:
            print(f"[MT5 Export] sync failed; validating local data: {summary['failed']}")

    result = export_symbol(
        args.db, args.symbol, args.output_dir, args.end_date
    )
    print(
        "[MT5 Export] "
        f"{args.symbol}: {result['row_count']} rows, "
        f"{result['first_date']} -> {result['last_date']}"
    )


if __name__ == "__main__":
    main()
