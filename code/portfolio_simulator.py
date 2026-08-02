"""Deterministic A-share portfolio simulator with one cash account."""

from dataclasses import dataclass, field
import math

import pandas as pd


@dataclass(frozen=True)
class FeeSchedule:
    commission_rate: float = 0.00025
    min_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    stamp_duty_rate_before_cutover: float = 0.001
    stamp_duty_cutover: str = "2023-08-28"
    transfer_fee_rate: float = 0.00001
    transfer_fee_rate_before_cutover: float = 0.00002
    beijing_transfer_fee_rate_before_cutover: float = 0.000025
    transfer_fee_cutover: str = "2022-04-29"
    slippage_rate: float = 0.001


@dataclass(frozen=True)
class RiskLimits:
    max_position_fraction: float = 0.20
    max_gross_exposure: float = 0.90
    daily_loss_limit: float = 0.03
    max_drawdown: float = 0.10


@dataclass
class Position:
    shares: int
    average_cost: float
    entry_time: pd.Timestamp
    peak_price: float
    entry_value: float
    buy_fees: float
    decision_id: str


@dataclass
class SimulationResult:
    initial_cash: float
    final_equity: float
    fills: list = field(default_factory=list)
    rejected_orders: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    positions: dict = field(default_factory=dict)


def _is_beijing_symbol(symbol):
    return str(symbol).startswith(("4", "8", "92"))


def _transfer_fee_rate(fees, symbol, date):
    if (
        date is None
        or pd.Timestamp(date) >= pd.Timestamp(fees.transfer_fee_cutover)
    ):
        return fees.transfer_fee_rate
    return (
        fees.beijing_transfer_fee_rate_before_cutover
        if _is_beijing_symbol(symbol)
        else fees.transfer_fee_rate_before_cutover
    )


def _buy_cost(shares, raw_price, fees, max_price=None,
              symbol="", date=None):
    fill_price = raw_price * (1.0 + fees.slippage_rate)
    if max_price is not None:
        fill_price = min(fill_price, max_price)
    gross = shares * fill_price
    commission = max(fees.min_commission, gross * fees.commission_rate)
    transfer = gross * _transfer_fee_rate(fees, symbol, date)
    return fill_price, gross, commission + transfer


def _stamp_duty_rate(fees, date):
    return (
        fees.stamp_duty_rate_before_cutover
        if pd.Timestamp(date) < pd.Timestamp(fees.stamp_duty_cutover)
        else fees.stamp_duty_rate
    )


def _sell_proceeds(shares, raw_price, fees, date, min_price=None, symbol=""):
    fill_price = raw_price * (1.0 - fees.slippage_rate)
    if min_price is not None:
        fill_price = max(fill_price, min_price)
    gross = shares * fill_price
    commission = max(fees.min_commission, gross * fees.commission_rate)
    transfer = gross * _transfer_fee_rate(fees, symbol, date)
    stamp = gross * _stamp_duty_rate(fees, date)
    total_fees = commission + transfer + stamp
    return fill_price, gross, total_fees, gross - total_fees


def _limit_fraction(symbol, name):
    symbol = str(symbol)
    if _is_beijing_symbol(symbol):
        return 0.30
    if symbol.startswith(("300", "301", "688", "689")):
        return 0.20
    if "ST" in str(name).upper():
        return 0.05
    return 0.10


def _previous_close(frame, date):
    previous = frame.loc[frame.index < date, "close"]
    return float(previous.iloc[-1]) if not previous.empty else None


def _market_value(positions, market, date, price_col="close"):
    value = 0.0
    for symbol, position in positions.items():
        frame = market[symbol]
        rows = frame.loc[frame.index <= date, price_col]
        if rows.empty:
            rows = frame.loc[frame.index <= date, "close"]
        if not rows.empty:
            value += position.shares * float(rows.iloc[-1])
    return value


def _buy_quantity(symbol, budget, estimated_fill):
    shares = int(budget / estimated_fill)
    if str(symbol).startswith(("688", "689")):
        return (shares if shares >= 200 else 0), 200, 1
    if _is_beijing_symbol(symbol):
        return (shares if shares >= 100 else 0), 100, 1
    return shares // 100 * 100, 100, 100


def _position_snapshots(positions, market, date):
    snapshots = {}
    for symbol, position in positions.items():
        rows = market[symbol].loc[market[symbol].index <= date, "close"]
        mark_price = float(rows.iloc[-1])
        market_value = position.shares * mark_price
        invested = position.entry_value + position.buy_fees
        snapshots[symbol] = {
            "shares": position.shares,
            "average_cost": position.average_cost,
            "entry_time": position.entry_time.strftime("%Y-%m-%d"),
            "mark_price": mark_price,
            "market_value": market_value,
            "unrealized_pnl": market_value - invested,
            "decision_id": position.decision_id,
        }
    return snapshots


def _reject(order, date, reason):
    return {
        "decision_id": order["decision_id"],
        "symbol": order["symbol"],
        "side": order["action"],
        "decision_time": order["decision_time"],
        "execution_time": date,
        "status": "REJECTED",
        "reason": reason,
        "model_version": order.get("model_version", ""),
    }


def _normalize_market(market):
    result = {}
    for symbol, frame in market.items():
        clean = frame.copy()
        clean.index = pd.to_datetime(clean.index)
        result[str(symbol)] = clean.sort_index()
    return result


def simulate_portfolio(market, decisions, initial_cash,
                       risk_limits=None, fees=None, names=None):
    """Run decisions through a shared account and next-open order queue."""
    if not math.isfinite(float(initial_cash)) or initial_cash <= 0:
        raise ValueError("initial_cash must be finite and positive")

    market = _normalize_market(market)
    limits = risk_limits or RiskLimits()
    fee_schedule = fees or FeeSchedule()
    names = names or {}
    all_dates = sorted({
        date for frame in market.values() for date in frame.index
    })
    if not all_dates:
        return SimulationResult(float(initial_cash), float(initial_cash))

    clean_decisions = decisions.copy()
    if clean_decisions.empty:
        clean_decisions = pd.DataFrame(columns=[
            "decision_time", "symbol", "action", "target_fraction",
        ])
    clean_decisions["decision_time"] = pd.to_datetime(
        clean_decisions["decision_time"]
    )
    clean_decisions["symbol"] = clean_decisions["symbol"].astype(str)

    cash = float(initial_cash)
    positions = {}
    pending = {}
    fills = []
    rejected = []
    trades = []
    equity_curve = []
    peak_equity = cash

    for date in all_dates:
        previous_equity = (
            equity_curve[-1]["equity"] if equity_curve else initial_cash
        )
        start_shares = {
            symbol: position.shares
            for symbol, position in positions.items()
        }
        fill_start = len(fills)
        previous_peak = max(
            (point["equity"] for point in equity_curve),
            default=initial_cash,
        )
        previous_drawdown = (
            (previous_peak - previous_equity) / previous_peak
            if previous_peak else 0.0
        )
        risk_locked = previous_drawdown >= limits.max_drawdown

        for order in sorted(
                pending.pop(date, []),
                key=lambda item: (
                    item["decision_time"], item["symbol"], item["action"]
                )):
            symbol = order["symbol"]
            frame = market.get(symbol)
            if frame is None or date not in frame.index:
                rejected.append(_reject(order, date, "SUSPENDED"))
                continue
            bar = frame.loc[date]
            if float(bar.get("volume", 0) or 0) <= 0:
                rejected.append(_reject(order, date, "SUSPENDED"))
                continue

            raw_price = float(bar["open"])
            previous_close = _previous_close(frame, date)
            limit_fraction = _limit_fraction(symbol, names.get(symbol, ""))
            limit_up = limit_down = None
            if previous_close is not None:
                limit_up = round(previous_close * (1 + limit_fraction), 2)
                limit_down = round(previous_close * (1 - limit_fraction), 2)
                if (
                    order["action"] == "BUY"
                    and raw_price >= limit_up
                    and float(bar["low"]) >= limit_up
                ):
                    rejected.append(_reject(order, date, "LIMIT_UP"))
                    continue
                if (
                    order["action"] == "SELL"
                    and raw_price <= limit_down
                    and float(bar["high"]) <= limit_down
                ):
                    rejected.append(_reject(order, date, "LIMIT_DOWN"))
                    continue

            if order["action"] == "BUY":
                if risk_locked:
                    rejected.append(_reject(order, date, "RISK_LOCKED"))
                    continue
                if symbol in positions:
                    rejected.append(_reject(order, date, "ALREADY_POSITIONED"))
                    continue

                open_equity = cash + _market_value(
                    positions, market, date, "open"
                )
                gross_exposure = _market_value(
                    positions, market, date, "open"
                )
                target_fraction = min(
                    max(float(order.get("target_fraction", 0.0)), 0.0),
                    limits.max_position_fraction,
                )
                target_value = open_equity * target_fraction
                exposure_room = max(
                    0.0,
                    open_equity * limits.max_gross_exposure - gross_exposure,
                )
                budget = min(
                    target_value,
                    exposure_room / (1 + fee_schedule.slippage_rate),
                    cash,
                )
                estimated_fill = raw_price * (1 + fee_schedule.slippage_rate)
                shares, minimum_shares, share_step = _buy_quantity(
                    symbol, budget, estimated_fill
                )
                while shares >= minimum_shares:
                    fill_price, gross, buy_fees = _buy_cost(
                        shares,
                        raw_price,
                        fee_schedule,
                        limit_up,
                        symbol,
                        date,
                    )
                    if gross + buy_fees <= cash:
                        break
                    shares -= share_step
                if shares < minimum_shares:
                    rejected.append(_reject(
                        order, date, "INSUFFICIENT_CASH"
                    ))
                    continue

                total_cost = gross + buy_fees
                cash -= total_cost
                transfer_fee = gross * _transfer_fee_rate(
                    fee_schedule, symbol, date
                )
                positions[symbol] = Position(
                    shares=shares,
                    average_cost=total_cost / shares,
                    entry_time=date,
                    peak_price=fill_price,
                    entry_value=gross,
                    buy_fees=buy_fees,
                    decision_id=order["decision_id"],
                )
                fills.append({
                    "decision_id": order["decision_id"],
                    "symbol": symbol,
                    "side": "BUY",
                    "decision_time": order["decision_time"],
                    "fill_time": date,
                    "raw_price": raw_price,
                    "fill_price": fill_price,
                    "shares": shares,
                    "gross_value": gross,
                    "fees": buy_fees,
                    "commission": buy_fees - transfer_fee,
                    "transfer_fee": transfer_fee,
                    "stamp_duty": 0.0,
                    "slippage": abs(fill_price - raw_price) * shares,
                    "status": "FILLED",
                    "model_version": order.get("model_version", ""),
                })
            elif order["action"] == "SELL":
                position = positions.get(symbol)
                if position is None:
                    rejected.append(_reject(order, date, "NO_POSITION"))
                    continue
                if pd.Timestamp(date).normalize() <= (
                    pd.Timestamp(position.entry_time).normalize()
                ):
                    rejected.append(_reject(order, date, "T_PLUS_ONE"))
                    continue
                fill_price, gross, sell_fees, net_proceeds = _sell_proceeds(
                    position.shares,
                    raw_price,
                    fee_schedule,
                    date,
                    limit_down,
                    symbol,
                )
                cash += net_proceeds
                transfer_fee = gross * _transfer_fee_rate(
                    fee_schedule, symbol, date
                )
                stamp_duty = (
                    gross * _stamp_duty_rate(fee_schedule, date)
                )
                pnl = net_proceeds - (
                    position.entry_value + position.buy_fees
                )
                fills.append({
                    "decision_id": order["decision_id"],
                    "symbol": symbol,
                    "side": "SELL",
                    "decision_time": order["decision_time"],
                    "fill_time": date,
                    "raw_price": raw_price,
                    "fill_price": fill_price,
                    "shares": position.shares,
                    "gross_value": gross,
                    "fees": sell_fees,
                    "commission": (
                        sell_fees - transfer_fee - stamp_duty
                    ),
                    "transfer_fee": transfer_fee,
                    "stamp_duty": stamp_duty,
                    "slippage": (
                        abs(fill_price - raw_price) * position.shares
                    ),
                    "status": "FILLED",
                    "model_version": order.get("model_version", ""),
                })
                trades.append({
                    "decision_id": position.decision_id,
                    "symbol": symbol,
                    "buy_date": position.entry_time,
                    "buy_price": position.average_cost,
                    "sell_date": date,
                    "sell_price": fill_price,
                    "shares": position.shares,
                    "pnl_amount": pnl,
                    "pnl_pct": (
                        pnl / (position.entry_value + position.buy_fees) * 100
                    ),
                    "buy_fees": position.buy_fees,
                    "sell_fees": sell_fees,
                    "exit_reason": order.get("reason", "SIGNAL"),
                })
                del positions[symbol]

        close_value = _market_value(positions, market, date)
        equity = cash + close_value
        peak_equity = max(peak_equity, equity)
        holding_pnl = 0.0
        for symbol, shares in start_shares.items():
            frame = market[symbol]
            current_rows = frame.loc[frame.index <= date, "close"]
            previous_close = _previous_close(frame, date)
            if not current_rows.empty and previous_close is not None:
                holding_pnl += shares * (
                    float(current_rows.iloc[-1]) - previous_close
                )
        day_fills = fills[fill_start:]
        trading_pnl = sum(
            (1 if fill["side"] == "BUY" else -1)
            * fill["shares"]
            * (
                float(market[fill["symbol"]].loc[date, "close"])
                - fill["raw_price"]
            )
            for fill in day_fills
        )
        commission = sum(fill["commission"] for fill in day_fills)
        transfer_fee = sum(fill["transfer_fee"] for fill in day_fills)
        stamp_duty = sum(fill["stamp_duty"] for fill in day_fills)
        slippage = sum(fill["slippage"] for fill in day_fills)
        net_pnl = equity - previous_equity
        daily_return = (
            equity / previous_equity - 1.0 if previous_equity else 0.0
        )
        equity_curve.append({
            "date": date,
            "equity": equity,
            "cash": cash,
            "gross_exposure": close_value,
            "start_equity": previous_equity,
            "holding_pnl": holding_pnl,
            "trading_pnl": trading_pnl,
            "commission": commission,
            "transfer_fee": transfer_fee,
            "stamp_duty": stamp_duty,
            "slippage": slippage,
            "turnover": sum(
                fill["gross_value"] for fill in day_fills
            ),
            "fill_count": len(day_fills),
            "net_pnl": net_pnl,
            "daily_return": daily_return,
            "drawdown": (
                (peak_equity - equity) / peak_equity if peak_equity else 0.0
            ),
        })

        day_decisions = clean_decisions[
            clean_decisions["decision_time"] == date
        ]
        for sequence, (_, row) in enumerate(day_decisions.iterrows()):
            action = str(row["action"]).upper()
            if action not in {"BUY", "SELL"}:
                continue
            frame = market.get(row["symbol"])
            future_dates = (
                frame.index[frame.index > date]
                if frame is not None else []
            )
            next_date = future_dates[0] if len(future_dates) else None
            decision_id = str(row.get(
                "decision_id",
                f"{date.date()}-{row['symbol']}-{sequence}",
            ))
            if next_date is None:
                rejected.append({
                    "decision_id": decision_id,
                    "symbol": row["symbol"],
                    "side": action,
                    "decision_time": date,
                    "execution_time": None,
                    "status": "EXPIRED",
                    "reason": "END_OF_DATA",
                    "model_version": row.get("model_version", ""),
                })
                continue
            if (
                action == "BUY"
                and equity_curve[-1]["daily_return"]
                <= -limits.daily_loss_limit
            ):
                rejected.append({
                    "decision_id": str(row.get(
                        "decision_id", decision_id,
                    )),
                    "symbol": row["symbol"],
                    "side": action,
                    "decision_time": date,
                    "execution_time": next_date,
                    "status": "REJECTED",
                    "reason": "DAILY_LOSS_LIMIT",
                    "model_version": row.get("model_version", ""),
                })
                continue
            order = row.to_dict()
            order["action"] = action
            order["decision_id"] = decision_id
            pending.setdefault(next_date, []).append(order)

    return SimulationResult(
        initial_cash=float(initial_cash),
        final_equity=float(equity_curve[-1]["equity"]),
        fills=fills,
        rejected_orders=rejected,
        trades=trades,
        equity_curve=equity_curve,
        positions=_position_snapshots(positions, market, all_dates[-1]),
    )
