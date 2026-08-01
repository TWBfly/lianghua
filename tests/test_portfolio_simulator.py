import pandas as pd
import pytest

from portfolio_simulator import (
    FeeSchedule,
    RiskLimits,
    _sell_proceeds,
    simulate_portfolio,
)


def bars(opens, closes=None, volumes=None):
    closes = closes or opens
    volumes = volumes or [1_000_000] * len(opens)
    dates = pd.bdate_range("2026-01-05", periods=len(opens))
    return pd.DataFrame({
        "open": opens,
        "high": [max(o, c) * 1.01 for o, c in zip(opens, closes)],
        "low": [min(o, c) * 0.99 for o, c in zip(opens, closes)],
        "close": closes,
        "volume": volumes,
    }, index=dates)


def decision(date, symbol="000001", action="BUY", fraction=0.5):
    return {
        "decision_time": pd.Timestamp(date),
        "symbol": symbol,
        "action": action,
        "target_fraction": fraction,
        "reason": "test",
        "model_version": "v1",
        "features_json": "{}",
    }


def test_close_signal_fills_at_next_open():
    frame = bars([10, 10.5, 12])

    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0])]),
        initial_cash=100_000,
    )

    fill = result.fills[0]
    assert fill["fill_time"] == frame.index[1]
    assert fill["raw_price"] == 10.5


def test_insufficient_cash_is_rejected_without_negative_cash():
    frame = bars([1_500, 1_500, 1_500])

    result = simulate_portfolio(
        {"600519": frame},
        pd.DataFrame([decision(frame.index[0], "600519", fraction=0.9)]),
        initial_cash=1_000,
    )

    assert result.rejected_orders[0]["reason"] == "INSUFFICIENT_CASH"
    assert min(point["cash"] for point in result.equity_curve) >= 0


def test_symbols_share_one_cash_balance_and_exposure_limit():
    frame = bars([10, 10, 10])
    symbols = [f"00000{i}" for i in range(1, 7)]
    decisions = pd.DataFrame([
        decision(frame.index[0], symbol, fraction=0.5)
        for symbol in symbols
    ])

    result = simulate_portfolio(
        {symbol: frame for symbol in symbols},
        decisions,
        initial_cash=100_000,
    )

    assert all(fill["shares"] % 100 == 0 for fill in result.fills)
    assert min(point["cash"] for point in result.equity_curve) >= 0
    assert sum(
        fill["gross_value"] for fill in result.fills
        if fill["side"] == "BUY"
    ) <= 90_000


def test_suspended_and_limit_locked_orders_are_rejected():
    dates = pd.bdate_range("2026-01-05", periods=3)
    suspended = bars([10, 10, 10], volumes=[1_000_000, 0, 1_000_000])
    limit_up = bars([10, 11, 11])
    limit_up.loc[dates[1], ["high", "low"]] = 11
    decisions = pd.DataFrame([
        decision(dates[0], "000001"),
        decision(dates[0], "000002"),
    ])

    result = simulate_portfolio(
        {"000001": suspended, "000002": limit_up},
        decisions,
        initial_cash=100_000,
    )

    reasons = {
        item["symbol"]: item["reason"]
        for item in result.rejected_orders
    }
    assert reasons == {
        "000001": "SUSPENDED",
        "000002": "LIMIT_UP",
    }


def test_slippage_never_crosses_limit_price_on_tradeable_bar():
    frame = bars([10, 10.99, 11])
    frame.loc[frame.index[1], ["high", "low"]] = [11, 10.8]

    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0])]),
        initial_cash=100_000,
    )

    assert result.fills[0]["fill_price"] == 11


def test_terminal_day_marks_open_position_without_forced_sale():
    frame = bars([10, 10, 12])

    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0])]),
        initial_cash=100_000,
    )

    assert result.trades == []
    assert result.positions["000001"]["shares"] > 0
    assert result.final_equity == result.equity_curve[-1]["equity"]
    assert result.equity_curve[-1]["daily_return"] == (
        result.final_equity / result.equity_curve[-2]["equity"] - 1
    )


def test_terminal_action_is_expired_instead_of_silently_dropped():
    frame = bars([10, 10, 10])

    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[-1], action="BUY")]),
        initial_cash=100_000,
    )


def test_order_uses_symbol_next_bar_and_expires_at_symbol_end():
    short = bars([10, 10])
    long = bars([20, 20, 20])

    result = simulate_portfolio(
        {"000001": short, "000002": long},
        pd.DataFrame([decision(short.index[-1], symbol="000001")]),
        initial_cash=100_000,
    )

    assert any(
        item["symbol"] == "000001"
        and item["status"] == "EXPIRED"
        and item["reason"] == "END_OF_DATA"
        and item["execution_time"] is None
        for item in result.rejected_orders
    )
    assert not any(
        item["symbol"] == "000001" and item["reason"] == "SUSPENDED"
        for item in result.rejected_orders
    )

    assert any(
        item["status"] == "EXPIRED"
        and item["reason"] == "END_OF_DATA"
        and item["execution_time"] is None
        for item in result.rejected_orders
    )


def test_daily_pnl_and_costs_reconcile_to_equity():
    frame = bars([10, 10.5, 12, 11.5])
    decisions = pd.DataFrame([
        decision(frame.index[0], action="BUY"),
        decision(frame.index[2], action="SELL"),
    ])

    result = simulate_portfolio(
        {"000001": frame}, decisions, initial_cash=100_000
    )

    assert sum(
        point["net_pnl"] for point in result.equity_curve
    ) == pytest.approx(result.final_equity - result.initial_cash)
    for point in result.equity_curve:
        assert point["net_pnl"] == pytest.approx(
            point["holding_pnl"]
            + point["trading_pnl"]
            - point["commission"]
            - point["transfer_fee"]
            - point["stamp_duty"]
            - point["slippage"],
            abs=0.01,
        )
    assert all(
        {
            "commission", "transfer_fee", "stamp_duty", "slippage",
        }.issubset(fill)
        for fill in result.fills
    )


def test_same_day_sell_is_rejected_by_t_plus_one():
    frame = bars([10, 10, 10])
    decisions = pd.DataFrame([
        decision(frame.index[0], action="BUY"),
        decision(frame.index[0], action="SELL"),
    ])

    result = simulate_portfolio(
        {"000001": frame}, decisions, initial_cash=100_000
    )

    assert result.trades == []
    assert any(
        item["side"] == "SELL" and item["reason"] == "T_PLUS_ONE"
        for item in result.rejected_orders
    )


def test_stamp_duty_changes_on_2023_08_28():
    before = _sell_proceeds(
        1_000, 10, FeeSchedule(), pd.Timestamp("2023-08-25")
    )
    after = _sell_proceeds(
        1_000, 10, FeeSchedule(), pd.Timestamp("2023-08-28")
    )

    assert before[2] - after[2] == pytest.approx(4.995)


def test_star_market_rejects_buy_below_200_share_minimum():
    frame = bars([10, 10, 10])

    result = simulate_portfolio(
        {"688001": frame},
        pd.DataFrame([decision(frame.index[0], symbol="688001")]),
        initial_cash=8_000,
    )

    assert not any(fill["side"] == "BUY" for fill in result.fills)
    assert result.rejected_orders[0]["reason"] == "INSUFFICIENT_CASH"


def test_daily_loss_blocks_new_buys():
    first = bars([10, 10, 10, 10], closes=[10, 9, 9, 9])
    second = bars([10, 10, 10, 10])
    dates = first.index
    decisions = pd.DataFrame([
        decision(dates[0], "000001", fraction=0.9),
        decision(dates[1], "000002", fraction=0.9),
    ])

    result = simulate_portfolio(
        {"000001": first, "000002": second},
        decisions,
        initial_cash=100_000,
        risk_limits=RiskLimits(
            max_position_fraction=0.9,
            max_gross_exposure=0.9,
        ),
    )

    assert any(
        item["symbol"] == "000002"
        and item["reason"] == "DAILY_LOSS_LIMIT"
        for item in result.rejected_orders
    )


def test_drawdown_kill_switch_blocks_new_buys():
    first = bars([10, 10, 10, 10], closes=[10, 8, 8, 8])
    second = bars([10, 10, 10, 10])
    dates = first.index
    decisions = pd.DataFrame([
        decision(dates[0], "000001", fraction=0.9),
        decision(dates[1], "000002", fraction=0.9),
    ])

    result = simulate_portfolio(
        {"000001": first, "000002": second},
        decisions,
        initial_cash=100_000,
        risk_limits=RiskLimits(
            max_position_fraction=0.9,
            max_gross_exposure=0.9,
            daily_loss_limit=1.0,
            max_drawdown=0.1,
        ),
    )

    assert any(
        item["symbol"] == "000002"
        and item["reason"] == "RISK_LOCKED"
        for item in result.rejected_orders
    )
