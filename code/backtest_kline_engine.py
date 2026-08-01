"""Causal A-share backtests backed by one shared-account simulator."""

import json
import math
from pathlib import Path
import sqlite3
import sys
import uuid

import joblib
import pandas as pd


CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from ashare_factor_pipeline import DB_PATH
from ashare_data_engine import AShareDataEngine
from backtest_metrics import build_daily_ledger, calculate_performance
from learning_loop import EvolutionManager, ExperienceStore, ModelRegistry
from market_data import MarketDataError, validate_daily_bars
from ml_ensemble import walk_forward_predict
from ml_strategy_engine import AShareMLStrategyEngine
from portfolio_simulator import _buy_quantity, simulate_portfolio


def _valid_symbol(symbol):
    value = str(symbol)
    return value if value.isdigit() and len(value) == 6 else None


def _friction_summary(simulation):
    fees = sum(float(fill["fees"]) for fill in simulation.fills)
    stamp = sum(
        float(fill.get(
            "stamp_duty",
            float(fill["gross_value"]) * 0.0005,
        ))
        for fill in simulation.fills
        if fill["side"] == "SELL"
    )
    slippage = sum(
        abs(float(fill["fill_price"]) - float(fill["raw_price"]))
        * int(fill["shares"])
        for fill in simulation.fills
    )
    return {
        "total_stamp_duty_cny": round(stamp, 2),
        "total_commission_cny": round(fees - stamp, 2),
        "total_slippage_cny": round(slippage, 2),
        "total_friction_cny": round(fees + slippage, 2),
    }


def _backtest_period(simulation):
    if not simulation.equity_curve:
        return ""
    first = pd.Timestamp(simulation.equity_curve[0]["date"])
    last = pd.Timestamp(simulation.equity_curve[-1]["date"])
    return f"{first:%Y-%m-%d} 至 {last:%Y-%m-%d}"


def _backtest_metadata(fallback_signal_count, universe_mode,
                       data_provenance):
    return {
        "engine": "NATIVE_A_SHARE_EVENT_V2",
        "price_mode": "QFQ_ADJUSTED_PROXY",
        "universe_mode": universe_mode,
        "fallback_signal_count": int(fallback_signal_count),
        "data_provenance": data_provenance,
        "research_limitations": [
            "NO_POINT_IN_TIME_UNIVERSE",
            "NO_HISTORICAL_ST_STATUS",
            "NO_HISTORICAL_IPO_LIMIT_STATUS",
            "NO_CORPORATE_ACTION_CASH_LEDGER",
            "TRANSACTION_RULES_APPROXIMATE",
        ],
    }


def _yearly_equity_breakdown(simulation):
    points = pd.DataFrame(simulation.equity_curve)
    if points.empty:
        return []
    points["date"] = pd.to_datetime(points["date"])
    points["year"] = points["date"].dt.year.astype(str)
    previous_equity = float(simulation.initial_cash)
    result = []
    for year, year_points in points.groupby("year", sort=True):
        final_equity = float(year_points.iloc[-1]["equity"])
        year_trades = [
            trade for trade in simulation.trades
            if pd.Timestamp(trade["sell_date"]).strftime("%Y") == year
        ]
        result.append({
            "year": year,
            "trades_count": len(year_trades),
            "win_rate_pct": round(
                sum(trade["pnl_amount"] > 0 for trade in year_trades)
                / len(year_trades) * 100,
                1,
            ) if year_trades else 0.0,
            "net_pnl": round(final_equity - previous_equity, 2),
            "return_pct": round(
                (final_equity / previous_equity - 1.0) * 100,
                2,
            ) if previous_equity else 0.0,
        })
        previous_equity = final_equity
    return result


class KLineBacktestEngine:
    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)
        self.data_engine = AShareDataEngine(db_path=self.db_path)
        self.ml_engine = AShareMLStrategyEngine(db_path=self.db_path)

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _load_market(conn, symbol, start_date, end_date):
        del start_date
        frame = pd.read_sql_query("""
            SELECT symbol, trade_date, open, close, high, low,
                   volume, amount, pct_chg
            FROM stock_daily
            WHERE symbol=? AND trade_date<=?
            ORDER BY trade_date
        """, conn, params=(symbol, end_date))
        basic = conn.execute(
            "SELECT name, pe_ttm FROM stock_basic "
            "WHERE symbol=? LIMIT 1",
            (symbol,),
        ).fetchone()
        name = str(basic[0]) if basic else symbol
        pe_ttm = (
            float(basic[1])
            if basic and basic[1] is not None else None
        )
        return frame, name, pe_ttm

    def _data_provenance(self, symbol, market_frame):
        provenance = self.data_engine.get_stock_daily_provenance(symbol)
        if provenance is not None:
            return provenance
        dates = pd.DatetimeIndex(market_frame.index)
        return {
            "symbol": str(symbol),
            "price_mode": "QFQ",
            "source": "LEGACY_UNCATALOGED",
            "start_date": dates.min().strftime("%Y-%m-%d"),
            "end_date": dates.max().strftime("%Y-%m-%d"),
            "row_count": len(market_frame),
            "updated_at": None,
        }

    def _apply_champion(self, symbol, features, predictions):
        champion = ModelRegistry(self.db_path).champion(symbol)
        if champion is None or not champion["trained_until"]:
            return predictions
        cutoff = pd.Timestamp(champion["trained_until"])
        prediction_index = features.index[features.index > cutoff]
        if prediction_index.empty:
            return predictions
        artifact_path = Path(champion["artifact_path"]).resolve()
        model_root = (
            Path(self.db_path).parent / "ml_models" / "evolution"
        ).resolve()
        if model_root not in artifact_path.parents:
            return predictions
        try:
            artifact = joblib.load(artifact_path)
            model_features = features.reindex(
                columns=artifact["feature_names"]
            ).apply(pd.to_numeric, errors="coerce").fillna(0.0)
            probability = artifact["model"].predict_proba(
                model_features.loc[prediction_index]
            )[:, 1]
        except Exception:
            return predictions
        result = predictions.copy()
        result.loc[prediction_index, "probability"] = probability
        result.loc[prediction_index, "score"] = probability * 10.0
        result.loc[prediction_index, "model_version"] = champion["version"]
        result.loc[prediction_index, "trained_until"] = cutoff
        return result

    def _build_symbol_run(self, symbol, frame, initial_capital,
                          target_fraction, run_id, start_date, end_date):
        index = pd.DatetimeIndex(pd.to_datetime(frame["trade_date"]))
        factors = self.ml_engine.pipeline.extract_factors(
            symbol, end_date=end_date
        )
        if factors is None:
            factors = pd.DataFrame(index=index)
        predictions = walk_forward_predict(frame, factors, symbol)
        close = pd.Series(frame["close"].to_numpy(dtype=float), index=index)
        ma20 = close.rolling(20).mean()
        rsi = factors.get(
            "rsi_14", pd.Series(50.0, index=index)
        ).reindex(index).fillna(50.0)
        macd = factors.get(
            "macd_hist", pd.Series(0.0, index=index)
        ).reindex(index).fillna(0.0)
        decision_features = pd.DataFrame({
            "close": close,
            "rsi_14": rsi,
            "macd_hist": macd,
            "probability": predictions["probability"],
            "ma20": ma20.fillna(0.0),
        }, index=index)
        predictions = self._apply_champion(
            symbol, decision_features, predictions
        )

        report_index = index[index >= pd.Timestamp(start_date)]
        previous_macd = macd.shift(1)
        decisions = []
        for date in report_index:
            probability = float(predictions.loc[date, "probability"])
            model_version = str(
                predictions.loc[date, "model_version"]
            )
            trend_safe = (
                pd.notna(ma20.loc[date])
                and close.loc[date] >= ma20.loc[date] * 0.95
            )
            macd_dead = (
                pd.notna(previous_macd.loc[date])
                and macd.loc[date] < 0
                and previous_macd.loc[date] >= 0
            )
            if probability >= 0.55 and trend_safe and rsi.loc[date] < 75:
                action, reason = "BUY", "CAUSAL_ML_ENTRY"
            elif probability < 0.38 or macd_dead:
                action = "SELL"
                reason = (
                    "CAUSAL_ML_EXIT"
                    if probability < 0.38 else "MACD_DEATH_CROSS"
                )
            else:
                action, reason = "HOLD", "NO_ACTION"
            features = {
                "close": float(close.loc[date]),
                "rsi_14": float(rsi.loc[date]),
                "macd_hist": float(macd.loc[date]),
                "probability": probability,
                "ma20": (
                    float(ma20.loc[date])
                    if pd.notna(ma20.loc[date]) else 0.0
                ),
            }
            decisions.append({
                "decision_id": (
                    f"backtest:{symbol}:{date.date()}:{model_version}"
                ),
                "run_id": run_id,
                "decision_time": date,
                "symbol": symbol,
                "action": action,
                "target_fraction": target_fraction,
                "desired_shares": _buy_quantity(
                    symbol,
                    initial_capital * target_fraction,
                    close.loc[date],
                )[0],
                "reason": reason,
                "model_version": model_version,
                "features": features,
                "features_json": json.dumps(features, sort_keys=True),
            })

        market_frame = frame.copy()
        market_frame.index = index
        return (
            market_frame.loc[report_index],
            decisions,
            predictions.loc[report_index],
        )

    def _persist_experiences(self, run_id, decisions, market, simulation):
        store = ExperienceStore(self.db_path)
        for decision in decisions:
            store.record_decision(decision)
        for fill in simulation.fills:
            if fill.get("model_version") != "terminal":
                store.record_order_result(
                    fill["decision_id"],
                    "FILLED",
                    fill_time=fill["fill_time"],
                    fill_price=fill["fill_price"],
                    fees=fill["fees"],
                )
        for rejected in simulation.rejected_orders:
            store.record_order_result(
                rejected["decision_id"],
                "REJECTED",
                rejection_reason=rejected["reason"],
            )

        by_symbol = {}
        for decision in decisions:
            by_symbol.setdefault(decision["symbol"], []).append(decision)
        for symbol, symbol_decisions in by_symbol.items():
            close = market[symbol]["close"].astype(float)
            for position, decision in enumerate(symbol_decisions[:-5]):
                base = float(close.iloc[position])
                window = close.iloc[position + 1:position + 6]
                store.complete_horizon(
                    decision["decision_id"],
                    float(close.iloc[position + 5] / base - 1),
                    float(window.max() / base - 1),
                    float(window.min() / base - 1),
                    close.index[position + 5],
                )
        for trade in simulation.trades:
            store.complete_trade(
                trade["decision_id"],
                trade["pnl_pct"] / 100.0,
                trade["sell_date"],
                trade["sell_price"],
            )
        with self.get_connection() as conn:
            total, completed = conn.execute("""
                SELECT COUNT(*), COALESCE(SUM(completed), 0)
                FROM experiences WHERE run_id=?
            """, (run_id,)).fetchone()
        return {"total": int(total), "completed": int(completed)}

    def _run_evolution(self, symbols, market):
        store = ExperienceStore(self.db_path)
        registry = ModelRegistry(self.db_path)
        manager = EvolutionManager(
            store,
            registry,
            Path(self.db_path).parent / "ml_models" / "evolution",
        )
        latest_market_time = max(
            frame.index.max() for frame in market.values()
        ).to_pydatetime()
        return manager.run_after_backtest(symbols, latest_market_time)

    @staticmethod
    def _trade_metrics(simulation, initial_capital):
        initial_capital = float(initial_capital)
        final_equity = float(simulation.final_equity)
        wins = [
            trade for trade in simulation.trades
            if trade["pnl_amount"] > 0
        ]
        losses = [
            trade for trade in simulation.trades
            if trade["pnl_amount"] < 0
        ]
        average_win = (
            sum(trade["pnl_amount"] for trade in wins) / len(wins)
            if wins else 0.0
        )
        average_loss = (
            sum(abs(trade["pnl_amount"]) for trade in losses) / len(losses)
            if losses else 0.0
        )
        max_drawdown = max(
            (
                float(point["drawdown"])
                for point in simulation.equity_curve
            ),
            default=0.0,
        )
        return {
            "final_equity": final_equity,
            "net_pnl": final_equity - initial_capital,
            "return": final_equity / initial_capital - 1.0,
            "wins": wins,
            "losses": losses,
            "win_rate": (
                len(wins) / len(simulation.trades)
                if simulation.trades else 0.0
            ),
            "profit_loss_ratio": (
                average_win / average_loss if average_loss else 0.0
            ),
            "max_drawdown": max_drawdown,
        }

    @staticmethod
    def _equity_curve(simulation):
        return [{
            **point,
            "date": pd.Timestamp(point["date"]).strftime("%Y-%m-%d"),
            "equity": round(float(point["equity"]), 2),
            "cash": round(float(point["cash"]), 2),
        } for point in simulation.equity_curve]

    def run_kline_backtest(self, symbol="603986",
                           start_date="2024-01-01",
                           end_date="2026-07-29",
                           initial_capital=1000000.0, skip_ai=False,
                           conn=None, persist_experiences=False,
                           run_evolution=False):
        """Generate signals at close and execute them at the next open."""
        del skip_ai
        clean_symbol = _valid_symbol(symbol)
        if clean_symbol is None:
            return {"error": "股票代码必须是6位数字"}
        if (
            not math.isfinite(float(initial_capital))
            or float(initial_capital) <= 0
        ):
            return {"error": "初始资金必须是有限正数"}

        local_connection = conn is None
        db_connection = conn or self.get_connection()
        try:
            frame, name, pe_ttm = self._load_market(
                db_connection, clean_symbol, start_date, end_date
            )
            if not frame.empty:
                frame = validate_daily_bars(frame, clean_symbol)
        except MarketDataError as exc:
            return {"error": f"行情数据质量错误: {exc}"}
        finally:
            if local_connection:
                db_connection.close()
        if frame.empty:
            return {"error": f"股票 {clean_symbol} 没有区间行情数据"}

        run_id = uuid.uuid4().hex
        market_frame, decisions, predictions = self._build_symbol_run(
            clean_symbol,
            frame,
            float(initial_capital),
            0.20,
            run_id,
            start_date,
            end_date,
        )
        if market_frame.empty:
            return {"error": f"股票 {clean_symbol} 没有区间行情数据"}
        market = {clean_symbol: market_frame}
        simulation = simulate_portfolio(
            market,
            pd.DataFrame(decisions),
            float(initial_capital),
            names={clean_symbol: name},
        )
        daily_results = build_daily_ledger(simulation)
        performance = calculate_performance(
            daily_results, float(initial_capital)
        )
        experience_stats = (
            self._persist_experiences(
                run_id, decisions, market, simulation
            )
            if persist_experiences else {"total": 0, "completed": 0}
        )
        evolution_status = (
            self._run_evolution([clean_symbol], market)
            if persist_experiences and run_evolution else []
        )
        stats = self._trade_metrics(simulation, initial_capital)
        dates = pd.DatetimeIndex(market_frame.index)
        elapsed_days = max(1, (dates[-1] - dates[0]).days)
        annualized = (
            (stats["final_equity"] / float(initial_capital))
            ** (365.0 / elapsed_days) - 1.0
            if stats["final_equity"] > 0 else -1.0
        )
        decision_by_id = {
            item["decision_id"]: item for item in decisions
        }
        trades = []
        for trade_id, trade in enumerate(simulation.trades, 1):
            decision = decision_by_id[trade["decision_id"]]
            prediction = predictions.loc[decision["decision_time"]]
            trades.append({
                "id": trade_id,
                "symbol": clean_symbol,
                "name": name,
                "buy_date": pd.Timestamp(
                    trade["buy_date"]
                ).strftime("%Y-%m-%d"),
                "buy_price": round(float(trade["buy_price"]), 2),
                "sell_date": pd.Timestamp(
                    trade["sell_date"]
                ).strftime("%Y-%m-%d"),
                "sell_price": round(float(trade["sell_price"]), 2),
                "shares": int(trade["shares"]),
                "pnl_amount": round(float(trade["pnl_amount"]), 2),
                "pnl_pct": round(float(trade["pnl_pct"]), 2),
                "ml_score_pct": round(float(prediction["score"]), 2),
                "financial_status": "历史回测未使用当前财报",
                "deepseek_reason": "历史回测未使用当前公告或AI",
                "sell_reason": trade["exit_reason"],
                "fees_detail": (
                    f"买入费用: ¥{trade['buy_fees']:.2f} | "
                    f"卖出费用: ¥{trade['sell_fees']:.2f}"
                ),
            })
        holding_days = [
            max(
                1,
                (
                    pd.Timestamp(trade["sell_date"])
                    - pd.Timestamp(trade["buy_date"])
                ).days,
            )
            for trade in simulation.trades
        ]
        model_versions = [{
            "prediction_time": date.strftime("%Y-%m-%d"),
            "model_version": row["model_version"],
            "trained_until": (
                pd.Timestamp(row["trained_until"]).strftime("%Y-%m-%d")
                if pd.notna(row["trained_until"]) else None
            ),
        } for date, row in predictions.iterrows()]

        return {
            "symbol": clean_symbol,
            "name": name,
            "pe_ttm": pe_ttm,
            "run_id": run_id,
            "metrics": {
                "initial_capital": round(float(initial_capital), 2),
                "final_equity": round(stats["final_equity"], 2),
                "net_pnl_total": round(stats["net_pnl"], 2),
                "total_return_pct": round(stats["return"] * 100, 2),
                "annualized_return_pct": round(annualized * 100, 2),
                "win_rate_pct": round(stats["win_rate"] * 100, 2),
                "total_trades": len(simulation.trades),
                "win_trades_count": len(stats["wins"]),
                "loss_trades_count": len(stats["losses"]),
                "profit_loss_ratio": round(
                    stats["profit_loss_ratio"], 2
                ),
                "avg_holding_days": (
                    round(sum(holding_days) / len(holding_days), 1)
                    if holding_days else 0.0
                ),
                "max_drawdown_pct": round(
                    stats["max_drawdown"] * 100, 2
                ),
                "backtest_period": _backtest_period(simulation),
                "friction_summary": _friction_summary(simulation),
                **performance,
            },
            "category_dates": [
                date.strftime("%Y-%m-%d") for date in dates
            ],
            "kline_chart_data": [
                [
                    float(row.open),
                    float(row.close),
                    float(row.low),
                    float(row.high),
                    float(row.volume),
                ]
                for row in market_frame.itertuples()
            ],
            "trades": trades,
            "equity_curve": self._equity_curve(simulation),
            "daily_results": daily_results,
            "rejected_orders": simulation.rejected_orders,
            "open_positions": simulation.positions,
            "model_versions": model_versions,
            "experience_stats": experience_stats,
            "evolution_status": evolution_status,
            "backtest_metadata": _backtest_metadata(
                (predictions["model_version"] == "causal-rule-v1").sum(),
                "SINGLE_USER_SELECTED",
                self._data_provenance(clean_symbol, market_frame),
            ),
        }

    def run_portfolio_backtest(self, initial_capital=200000.0,
                               start_date="2024-01-01",
                               end_date="2026-07-29", symbols=None,
                               persist_experiences=False,
                               run_evolution=False):
        """Backtest several symbols on one timeline and one cash account."""
        if (
            not math.isfinite(float(initial_capital))
            or float(initial_capital) <= 0
        ):
            return {"error": "初始资金必须是有限正数"}

        with self.get_connection() as conn:
            automatic_universe = symbols is None
            if automatic_universe:
                symbols = [
                    str(row[0]) for row in conn.execute("""
                        SELECT symbol FROM stock_daily
                        GROUP BY symbol
                        HAVING MIN(trade_date) <= ?
                        ORDER BY symbol LIMIT 12
                    """, (start_date,)).fetchall()
                ]
            else:
                symbols = [str(symbol) for symbol in symbols]
            invalid = next(
                (symbol for symbol in symbols if not _valid_symbol(symbol)),
                None,
            )
            if invalid:
                return {"error": f"股票代码格式错误: {invalid}"}

            run_id = uuid.uuid4().hex
            target_fraction = min(0.20, 0.90 / max(1, len(symbols)))
            market = {}
            names = {}
            decisions = []
            data_provenance = []
            fallback_signal_count = 0
            for symbol in symbols:
                frame, name, _ = self._load_market(
                    conn, symbol, start_date, end_date
                )
                if frame.empty:
                    continue
                try:
                    frame = validate_daily_bars(frame, symbol)
                except MarketDataError as exc:
                    return {"error": f"行情数据质量错误: {exc}"}
                market_frame, symbol_decisions, symbol_predictions = (
                    self._build_symbol_run(
                        symbol,
                        frame,
                        float(initial_capital),
                        target_fraction,
                        run_id,
                        start_date,
                        end_date,
                    )
                )
                if market_frame.empty:
                    continue
                market[symbol] = market_frame
                names[symbol] = name
                decisions.extend(symbol_decisions)
                fallback_signal_count += int(
                    (
                        symbol_predictions["model_version"]
                        == "causal-rule-v1"
                    ).sum()
                )
                data_provenance.append(
                    self._data_provenance(symbol, market_frame)
                )

        if not market:
            return {"error": "选定股票没有区间行情数据"}
        simulation = simulate_portfolio(
            market,
            pd.DataFrame(decisions),
            float(initial_capital),
            names=names,
        )
        daily_results = build_daily_ledger(simulation)
        performance = calculate_performance(
            daily_results, float(initial_capital)
        )
        experience_stats = (
            self._persist_experiences(
                run_id, decisions, market, simulation
            )
            if persist_experiences else {"total": 0, "completed": 0}
        )
        evolution_status = (
            self._run_evolution(list(market), market)
            if persist_experiences and run_evolution else []
        )
        stats = self._trade_metrics(simulation, initial_capital)
        portfolio_trades = [{
            **trade,
            "buy_date": pd.Timestamp(
                trade["buy_date"]
            ).strftime("%Y-%m-%d"),
            "sell_date": pd.Timestamp(
                trade["sell_date"]
            ).strftime("%Y-%m-%d"),
            "buy_price": round(float(trade["buy_price"]), 2),
            "sell_price": round(float(trade["sell_price"]), 2),
            "pnl_amount": round(float(trade["pnl_amount"]), 2),
            "pnl_pct": round(float(trade["pnl_pct"]), 2),
            "name": names.get(trade["symbol"], trade["symbol"]),
        } for trade in simulation.trades]
        yearly_breakdown = _yearly_equity_breakdown(simulation)
        allocations = [{
            "symbol": symbol,
            "name": names[symbol],
            "safe_allocation_pct": round(target_fraction * 100, 2),
            "recommend_capital": round(
                float(initial_capital) * target_fraction, 2
            ),
        } for symbol in market]
        risk_allocations = [{
            **item,
            "allocation_method": "FIXED_RISK_CAP",
            "allocation_pct": item["safe_allocation_pct"],
            "price": float(market[item["symbol"]].iloc[-1]["close"]),
            "recommend_shares": _buy_quantity(
                item["symbol"],
                item["recommend_capital"],
                float(market[item["symbol"]].iloc[-1]["close"]),
            )[0],
        } for item in allocations]

        return {
            "run_id": run_id,
            "portfolio_metrics": {
                "initial_capital": round(float(initial_capital), 2),
                "final_equity": round(stats["final_equity"], 2),
                "total_pnl": round(stats["net_pnl"], 2),
                "total_return_pct": round(stats["return"] * 100, 2),
                "overall_win_rate_pct": round(
                    stats["win_rate"] * 100, 1
                ),
                "total_trades_count": len(simulation.trades),
                "win_trades_count": len(stats["wins"]),
                "loss_trades_count": len(stats["losses"]),
                "overall_profit_loss_ratio": round(
                    stats["profit_loss_ratio"], 2
                ),
                "overall_max_dd_pct": round(
                    stats["max_drawdown"] * 100, 2
                ),
                "backtest_period": _backtest_period(simulation),
                "friction_summary": _friction_summary(simulation),
                **performance,
            },
            "yearly_breakdown": yearly_breakdown,
            "allocations": allocations,
            "kelly_allocations": risk_allocations,
            "portfolio_trades": portfolio_trades,
            "equity_curve": self._equity_curve(simulation),
            "daily_results": daily_results,
            "rejected_orders": simulation.rejected_orders,
            "open_positions": simulation.positions,
            "experience_stats": experience_stats,
            "evolution_status": evolution_status,
            "backtest_metadata": _backtest_metadata(
                fallback_signal_count,
                (
                    "CURRENT_SNAPSHOT"
                    if automatic_universe else "USER_SELECTED"
                ),
                data_provenance,
            ),
        }


if __name__ == "__main__":
    result = KLineBacktestEngine().run_kline_backtest("600519")
    print(result.get("metrics", result))
