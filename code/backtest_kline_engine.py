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
from market_regime import (
    INDEX_CODE as REGIME_INDEX_CODE,
    N_STATES as REGIME_STATES,
    POLICY_VERSION as REGIME_POLICY_VERSION,
    RETRAIN_EVERY as REGIME_RETRAIN_EVERY,
    TRAINING_WINDOW as REGIME_TRAINING_WINDOW,
    apply_regime_overlay,
    walk_forward_regimes,
)
from ml_ensemble import (
    HOLDOUT_SIZE,
    LABEL_HORIZON,
    RETRAIN_EVERY,
    TRAINING_WINDOW,
    ml_policy_action,
    walk_forward_predict,
)
from ml_strategy_engine import AShareMLStrategyEngine
from portfolio_simulator import _buy_quantity, simulate_portfolio
from strategy_signal_library import SIGNAL_FUNCTIONS


BACKTEST_MODES = {"STRICT", "RESEARCH_PROXY"}
EXECUTABLE_STRATEGIES = ("causal_ml", *SIGNAL_FUNCTIONS)


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


def _benchmark_comparison(db_path, simulation, strategy_return_pct,
                          benchmark_code="000300"):
    unknown = {
        "status": "UNKNOWN",
        "benchmark_code": benchmark_code,
        "start_date": None,
        "end_date": None,
        "return_pct": None,
        "excess_return_pct": None,
    }
    if not simulation.equity_curve:
        return unknown
    reporting_dates = {
        pd.Timestamp(point["date"]).strftime("%Y-%m-%d")
        for point in simulation.equity_curve
    }
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("""
                SELECT trade_date, close FROM index_daily
                WHERE index_code=? AND trade_date>=? AND trade_date<=?
                ORDER BY trade_date
            """, (
                benchmark_code,
                min(reporting_dates),
                max(reporting_dates),
            )).fetchall()
    except sqlite3.Error:
        return unknown
    common = [row for row in rows if row[0] in reporting_dates]
    if len(common) < 2 or not common[0][1]:
        return unknown
    benchmark_return = (
        float(common[-1][1]) / float(common[0][1]) - 1.0
    ) * 100.0
    return {
        "status": "AVAILABLE",
        "benchmark_code": benchmark_code,
        "start_date": common[0][0],
        "end_date": common[-1][0],
        "return_pct": round(benchmark_return, 2),
        "excess_return_pct": round(
            float(strategy_return_pct) - benchmark_return, 2
        ),
    }


def _price_semantics(data_provenance):
    items = (
        data_provenance
        if isinstance(data_provenance, list) else [data_provenance]
    )
    if any(
        item.get("verification_status") != "VERIFIED"
        or item.get("price_mode") == "UNKNOWN"
        for item in items
    ):
        return "LEGACY_UNVERIFIED"
    if all(item.get("price_mode") == "RAW" for item in items):
        return "RAW_EXECUTION"
    return "ADJUSTED_PROXY"


def _provenance_error(provenance, backtest_mode):
    if backtest_mode != "STRICT":
        return None
    if provenance.get("verification_status") != "VERIFIED":
        return {
            "error": "严格回测拒绝未验证的数据血缘",
            "error_code": "UNVERIFIED_DATA_PROVENANCE",
        }
    if provenance.get("price_mode") != "RAW":
        return {
            "error": "严格回测需要原始价格与完整公司行为数据",
            "error_code": "RAW_EXECUTION_UNAVAILABLE",
        }
    return None


def _backtest_metadata(fallback_signal_count, universe_mode,
                       data_provenance, backtest_mode, strategy,
                       insufficient_history_count=0,
                       market_regime=None):
    price_semantics = _price_semantics(data_provenance)
    limitations = [
        "NO_POINT_IN_TIME_UNIVERSE",
        "NO_HISTORICAL_ST_STATUS",
        "NO_HISTORICAL_IPO_LIMIT_STATUS",
        "NO_CORPORATE_ACTION_CASH_LEDGER",
        "TRANSACTION_RULES_APPROXIMATE",
    ]
    if market_regime is not None:
        limitations.append("UNVERIFIED_MARKET_REGIME_DATA")
    metadata = {
        "engine": "NATIVE_A_SHARE_EVENT_V2",
        "price_mode": (
            "QFQ_ADJUSTED_PROXY"
            if price_semantics == "ADJUSTED_PROXY"
            else price_semantics
        ),
        "price_semantics": price_semantics,
        "backtest_mode": backtest_mode,
        "strategy_name": strategy,
        "ai_used": False,
        "data_license_status": "UNVERIFIED_FOR_COMMERCIAL_USE",
        "universe_mode": universe_mode,
        "fallback_signal_count": int(fallback_signal_count),
        "training_mode": "FIXED_WINDOW_WALK_FORWARD",
        "training_window": TRAINING_WINDOW,
        "retrain_every": RETRAIN_EVERY,
        "label_horizon": LABEL_HORIZON,
        "holdout_size": HOLDOUT_SIZE,
        "insufficient_history_count": int(insufficient_history_count),
        "data_provenance": data_provenance,
        "research_limitations": limitations,
    }
    if market_regime is not None:
        metadata["market_regime"] = market_regime
    return metadata


def _regime_at(regimes, date):
    if regimes is None:
        return None
    if date in regimes.index:
        return regimes.loc[date]
    return pd.Series({"status": "REGIME_DATA_UNAVAILABLE"})


def _regime_metadata(regimes, decisions):
    decision_dates = pd.DatetimeIndex(sorted({
        pd.Timestamp(item["decision_time"]) for item in decisions
    }))
    aligned = regimes.reindex(decision_dates)
    status = aligned.get(
        "status", pd.Series(index=decision_dates, dtype=object)
    )
    state = aligned.get(
        "state", pd.Series(index=decision_dates, dtype=object)
    )
    state_counts = state.value_counts().to_dict()
    fits = regimes.attrs.get("fits", [])
    return {
        "enabled": True,
        "policy_version": REGIME_POLICY_VERSION,
        "index_code": REGIME_INDEX_CODE,
        "state_count": REGIME_STATES,
        "training_window": REGIME_TRAINING_WINDOW,
        "retrain_every": REGIME_RETRAIN_EVERY,
        "coverage_count": int((status == "AVAILABLE").sum()),
        "unavailable_count": int((status != "AVAILABLE").sum()),
        "state_day_counts": {
            name: int(state_counts.get(name, 0))
            for name in (
                "LOW_VOL_BULL", "RANGE", "HIGH_VOL_BEAR"
            )
        },
        "filtered_buy_count": sum(
            item["reason"] in {
                "REGIME_HIGH_VOL_BEAR", "REGIME_UNAVAILABLE"
            }
            for item in decisions
        ),
        "scaled_buy_count": sum(
            "REGIME_RANGE_HALF" in item["reason"]
            for item in decisions
        ),
        "model_fit_count": len(fits),
        "latest_fit": fits[-1] if fits else None,
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

    @staticmethod
    def _load_market_regimes(conn, end_date):
        try:
            frame = pd.read_sql_query("""
                SELECT trade_date, close FROM index_daily
                WHERE index_code=? AND trade_date<=?
                ORDER BY trade_date
            """, conn, params=(REGIME_INDEX_CODE, end_date))
        except sqlite3.Error:
            frame = pd.DataFrame(columns=["trade_date", "close"])
        return walk_forward_regimes(frame)

    def _data_provenance(self, symbol, market_frame):
        provenance = self.data_engine.get_stock_daily_provenance(symbol)
        if provenance is not None:
            return provenance
        dates = pd.DatetimeIndex(pd.to_datetime(
            market_frame["trade_date"]
            if "trade_date" in market_frame else market_frame.index
        ))
        return {
            "symbol": str(symbol),
            "price_mode": "UNKNOWN",
            "source": "LEGACY_UNCATALOGED",
            "start_date": dates.min().strftime("%Y-%m-%d"),
            "end_date": dates.max().strftime("%Y-%m-%d"),
            "row_count": len(market_frame),
            "updated_at": None,
            "verification_status": "UNVERIFIED",
        }

    def _apply_champion(self, symbol, features, predictions):
        champion = ModelRegistry(self.db_path).champion(symbol)
        if champion is None or not champion["trained_until"]:
            return predictions
        cutoff = pd.Timestamp(
            champion["evaluated_until"] or champion["trained_until"]
        )
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
                          target_fraction, run_id, start_date, end_date,
                          strategy, regimes=None):
        index = pd.DatetimeIndex(pd.to_datetime(frame["trade_date"]))
        report_index = index[index >= pd.Timestamp(start_date)]
        close = pd.Series(frame["close"].to_numpy(dtype=float), index=index)
        if strategy != "causal_ml":
            signal_frame = frame.copy()
            signal_frame.index = index
            signal = SIGNAL_FUNCTIONS[strategy](signal_frame).fillna(0).astype(int)
            model_version = f"mechanical:{strategy}:v1"
            predictions = pd.DataFrame({
                "probability": signal.map({-1: 0.0, 0: 0.5, 1: 1.0}),
                "score": signal.astype(float),
                "model_version": model_version,
                "trained_until": pd.NaT,
            }, index=index)
            decisions = []
            for date in report_index:
                value = int(signal.loc[date])
                action = {1: "BUY", -1: "SELL"}.get(value, "HOLD")
                reason = (
                    f"MECHANICAL_{strategy.upper()}_{action}"
                    if action != "HOLD" else "NO_ACTION"
                )
                action, reason, effective_fraction, regime_features = (
                    apply_regime_overlay(
                        action,
                        reason,
                        target_fraction,
                        _regime_at(regimes, date),
                    )
                )
                features = {"signal": value, **regime_features}
                decisions.append({
                    "decision_id": f"backtest:{symbol}:{date.date()}:{model_version}",
                    "run_id": run_id,
                    "decision_time": date,
                    "symbol": symbol,
                    "action": action,
                    "target_fraction": effective_fraction,
                    "desired_shares": _buy_quantity(
                        symbol,
                        initial_capital * effective_fraction,
                        close.loc[date],
                    )[0],
                    "reason": reason,
                    "model_version": model_version,
                    "features": features,
                    "features_json": json.dumps(
                        features, sort_keys=True
                    ),
                })
            market_frame = frame.copy()
            market_frame.index = index
            return (
                market_frame.loc[report_index],
                decisions,
                predictions.loc[report_index],
            )

        factors = self.ml_engine.pipeline.extract_factors(
            symbol, end_date=end_date
        )
        if factors is None:
            factors = pd.DataFrame(index=index)
        predictions = walk_forward_predict(frame, factors, symbol)
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

        previous_macd = macd.shift(1)
        decisions = []
        for date in report_index:
            model_version = str(
                predictions.loc[date, "model_version"]
            )
            raw_probability = predictions.loc[date, "probability"]
            if pd.isna(raw_probability):
                probability = None
                action, reason = "HOLD", model_version
            else:
                probability = float(raw_probability)
                action, reason = ml_policy_action(
                    probability,
                    close.loc[date],
                    ma20.loc[date],
                    rsi.loc[date],
                    macd.loc[date],
                    previous_macd.loc[date],
                )
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
            action, reason, effective_fraction, regime_features = (
                apply_regime_overlay(
                    action,
                    reason,
                    target_fraction,
                    _regime_at(regimes, date),
                )
            )
            features.update(regime_features)
            decisions.append({
                "decision_id": (
                    f"backtest:{symbol}:{date.date()}:{model_version}"
                ),
                "run_id": run_id,
                "decision_time": date,
                "symbol": symbol,
                "action": action,
                "target_fraction": effective_fraction,
                "desired_shares": _buy_quantity(
                    symbol,
                    initial_capital * effective_fraction,
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
        return manager.run_after_backtest(
            symbols, latest_market_time, market
        )

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
                           run_evolution=False,
                           backtest_mode="STRICT",
                           strategy="causal_ml",
                           regime_filter=False):
        """Generate signals at close and execute them at the next open."""
        del skip_ai
        if regime_filter and run_evolution:
            return {
                "error": "市场状态过滤暂不支持模型进化",
                "error_code": "REGIME_EVOLUTION_UNSUPPORTED",
            }
        clean_symbol = _valid_symbol(symbol)
        if clean_symbol is None:
            return {"error": "股票代码必须是6位数字"}
        if (
            not math.isfinite(float(initial_capital))
            or float(initial_capital) <= 0
        ):
            return {"error": "初始资金必须是有限正数"}
        backtest_mode = str(backtest_mode).upper()
        if backtest_mode not in BACKTEST_MODES:
            return {
                "error": "回测模式必须是 STRICT 或 RESEARCH_PROXY",
                "error_code": "INVALID_BACKTEST_MODE",
            }
        strategy = str(strategy)
        if strategy not in EXECUTABLE_STRATEGIES:
            return {
                "error": f"策略不可执行: {strategy}",
                "error_code": "UNKNOWN_STRATEGY",
            }

        local_connection = conn is None
        db_connection = conn or self.get_connection()
        try:
            frame, name, pe_ttm = self._load_market(
                db_connection, clean_symbol, start_date, end_date
            )
            if not frame.empty:
                frame = validate_daily_bars(frame, clean_symbol)
            regimes = (
                self._load_market_regimes(db_connection, end_date)
                if regime_filter else None
            )
        except MarketDataError as exc:
            return {"error": f"行情数据质量错误: {exc}"}
        finally:
            if local_connection:
                db_connection.close()
        if frame.empty:
            return {"error": f"股票 {clean_symbol} 没有区间行情数据"}

        data_provenance = self._data_provenance(clean_symbol, frame)
        provenance_error = _provenance_error(
            data_provenance, backtest_mode
        )
        if provenance_error:
            return provenance_error

        run_id = uuid.uuid4().hex
        market_frame, decisions, predictions = self._build_symbol_run(
            clean_symbol,
            frame,
            float(initial_capital),
            0.20,
            run_id,
            start_date,
            end_date,
            strategy,
            regimes,
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
        benchmark = _benchmark_comparison(
            self.db_path, simulation, stats["return"] * 100.0
        )
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
                "benchmark": benchmark,
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
                data_provenance,
                backtest_mode,
                strategy,
                predictions["model_version"].astype(str).str.startswith(
                    "INSUFFICIENT_"
                ).sum(),
                (
                    _regime_metadata(regimes, decisions)
                    if regime_filter else None
                ),
            ),
        }

    def run_portfolio_backtest(self, initial_capital=200000.0,
                               start_date="2024-01-01",
                               end_date="2026-07-29", symbols=None,
                               persist_experiences=False,
                               run_evolution=False,
                               backtest_mode="STRICT",
                               strategy="causal_ml",
                               regime_filter=False):
        """Backtest several symbols on one timeline and one cash account."""
        if regime_filter and run_evolution:
            return {
                "error": "市场状态过滤暂不支持模型进化",
                "error_code": "REGIME_EVOLUTION_UNSUPPORTED",
            }
        if (
            not math.isfinite(float(initial_capital))
            or float(initial_capital) <= 0
        ):
            return {"error": "初始资金必须是有限正数"}
        backtest_mode = str(backtest_mode).upper()
        if backtest_mode not in BACKTEST_MODES:
            return {
                "error": "回测模式必须是 STRICT 或 RESEARCH_PROXY",
                "error_code": "INVALID_BACKTEST_MODE",
            }
        strategy = str(strategy)
        if strategy not in EXECUTABLE_STRATEGIES:
            return {
                "error": f"策略不可执行: {strategy}",
                "error_code": "UNKNOWN_STRATEGY",
            }

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
            regimes = (
                self._load_market_regimes(conn, end_date)
                if regime_filter else None
            )
            target_fraction = min(0.20, 0.90 / max(1, len(symbols)))
            market = {}
            names = {}
            decisions = []
            data_provenance = []
            fallback_signal_count = 0
            insufficient_history_count = 0
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
                provenance = self._data_provenance(symbol, frame)
                provenance_error = _provenance_error(
                    provenance, backtest_mode
                )
                if provenance_error:
                    return provenance_error
                market_frame, symbol_decisions, symbol_predictions = (
                    self._build_symbol_run(
                        symbol,
                        frame,
                        float(initial_capital),
                        target_fraction,
                        run_id,
                        start_date,
                        end_date,
                        strategy,
                        regimes,
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
                insufficient_history_count += int(
                    symbol_predictions["model_version"].astype(str)
                    .str.startswith("INSUFFICIENT_").sum()
                )
                data_provenance.append(provenance)

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
        benchmark = _benchmark_comparison(
            self.db_path, simulation, stats["return"] * 100.0
        )
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
                "benchmark": benchmark,
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
                backtest_mode,
                strategy,
                insufficient_history_count,
                (
                    _regime_metadata(regimes, decisions)
                    if regime_filter else None
                ),
            ),
        }


if __name__ == "__main__":
    result = KLineBacktestEngine().run_kline_backtest("600519")
    print(result.get("metrics", result))
