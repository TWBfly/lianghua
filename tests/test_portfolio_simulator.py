import pandas as pd
import pytest

import portfolio_simulator
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


def decision(date, symbol="000001", action="BUY", fraction=0.5,
             risk_exit=None):
    return {
        "decision_time": pd.Timestamp(date),
        "symbol": symbol,
        "action": action,
        "target_fraction": fraction,
        "reason": "test",
        "model_version": "v1",
        "features_json": "{}",
        "risk_exit": risk_exit,
    }


def atr_policy(atr=1.0):
    return {
        "entry_atr": atr,
        "stop_atr_multiple": 1.25,
        "stop_floor_fraction": 0.972,
        "take_profit_atr_multiple": 2.5,
        "trailing_activation_fraction": 1.03,
        "trailing_atr_multiple": 1.0,
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


def test_buy_fill_never_exceeds_causal_volume_ceiling():
    frame = bars([10, 10, 10], volumes=[10_000, 10_000, 10_000])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0], fraction=0.9)]),
        initial_cash=100_000,
    )

    assert result.fills[0]["shares"] == 100


def test_below_lot_volume_ceiling_rejects_buy():
    frame = bars([10, 10, 10], volumes=[9_999, 9_999, 9_999])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0], fraction=0.9)]),
        initial_cash=100_000,
    )

    assert result.fills == []
    assert result.rejected_orders[0]["reason"] == "LIQUIDITY_LIMIT"


def test_oversized_exit_is_rejected_and_position_is_preserved():
    frame = bars(
        [10, 10, 10, 10],
        volumes=[1_000_000, 100, 100, 100],
    )
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], action="BUY", fraction=0.9),
            decision(frame.index[1], action="SELL"),
        ]),
        initial_cash=100_000,
        risk_limits=RiskLimits(
            max_position_fraction=0.9,
            max_gross_exposure=0.9,
        ),
    )

    assert any(
        item["side"] == "SELL" and item["reason"] == "LIQUIDITY_LIMIT"
        for item in result.rejected_orders
    )
    assert result.trades == []
    assert result.positions["000001"]["shares"] > 0


@pytest.mark.parametrize(("high", "low", "reason"), [
    (10.2, 9.6, "ATR_STOP"),
    (13.0, 10.0, "ATR_TAKE_PROFIT"),
])
def test_atr_stop_and_take_profit_use_actual_fill_state(
        high, low, reason):
    frame = bars([10, 10, 10, 10])
    frame.loc[frame.index[2], ["high", "low"]] = [high, low]
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades[0]["exit_reason"] == reason
    sell = next(fill for fill in result.fills if fill["side"] == "SELL")
    expected = _sell_proceeds(
        sell["shares"], sell["raw_price"], FeeSchedule(),
        sell["fill_time"], symbol="000001",
        daily_volume=1_000_000,
    )
    assert sell["fill_price"] == pytest.approx(expected[0])
    assert sell["fees"] == pytest.approx(expected[2])


def test_t_plus_one_prevents_entry_day_atr_exit():
    frame = bars([10, 10, 10])
    frame.loc[frame.index[1], "low"] = 1.0
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades == []
    assert "000001" in result.positions


def test_same_bar_stop_wins_over_take_profit():
    frame = bars([10, 10, 10, 10])
    frame.loc[frame.index[2], ["high", "low"]] = [20.0, 1.0]
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades[0]["exit_reason"] == "ATR_STOP"


def test_trailing_exit_uses_prior_peak_not_current_bar_high():
    frame = bars([10, 10, 10])
    frame.loc[frame.index[2], ["high", "low"]] = [12.0, 10.0]
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades == []
    assert result.positions["000001"]["shares"] > 0


def test_atr_trailing_stop_uses_peak_from_previous_bar():
    frame = bars([10, 10, 10, 10])
    frame.loc[frame.index[2], ["high", "low"]] = [12.0, 10.0]
    frame.loc[frame.index[3], ["high", "low"]] = [11.5, 10.5]
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades[0]["exit_reason"] == "ATR_TRAILING_STOP"


def test_missing_atr_policy_leaves_signal_exit_available():
    frame = bars([10, 10, 10, 10])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], action="BUY"),
            decision(frame.index[1], action="SELL"),
        ]),
        initial_cash=100_000,
    )

    assert result.trades[0]["exit_reason"] == "test"


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
    assert reasons["000001"] == "SUSPENDED"
    assert reasons["000002"] in {"LIMIT_UP", "LIMIT_UP_LOCKED"}


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


@pytest.mark.parametrize(("symbol", "name", "expected"), [
    ("920001", "北交所样本", 0.30),
    ("689001", "科创板样本", 0.20),
    ("300001", "*ST创业", 0.20),
    ("301001", "ST创业", 0.20),
    ("600001", "*ST主板", 0.05),
])
def test_board_limit_fraction_precedes_generic_st_rule(
        symbol, name, expected):
    assert portfolio_simulator._limit_fraction(symbol, name) == expected


def test_beijing_market_uses_100_share_minimum_then_one_share_steps():
    assert portfolio_simulator._buy_quantity(
        "920001", 1_010, 10
    ) == (101, 100, 1)
    assert portfolio_simulator._buy_quantity(
        "920001", 990, 10
    ) == (0, 100, 1)


def test_star_689_uses_200_share_minimum_then_one_share_steps():
    assert portfolio_simulator._buy_quantity(
        "689001", 2_010, 10
    ) == (201, 200, 1)


@pytest.mark.parametrize(("symbol", "expected_before"), [
    ("600001", 0.00002),
    ("000001", 0.00002),
    ("920001", 0.000025),
])
def test_transfer_fee_changes_on_2022_04_29(symbol, expected_before):
    fees = FeeSchedule()

    before = portfolio_simulator._transfer_fee_rate(
        fees, symbol, pd.Timestamp("2022-04-28")
    )
    after = portfolio_simulator._transfer_fee_rate(
        fees, symbol, pd.Timestamp("2022-04-29")
    )

    assert before == expected_before
    assert after == 0.00001


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


def test_dynamic_slippage_with_market_impact():
    from portfolio_simulator import _buy_cost, FeeSchedule

    # Small order relative to volume: low impact
    low_impact_price, _, _ = _buy_cost(100, 10.0, FeeSchedule(slippage_rate=0.001), daily_volume=1_000_000)
    # Large order relative to volume: high impact
    high_impact_price, _, _ = _buy_cost(100_000, 10.0, FeeSchedule(slippage_rate=0.001), daily_volume=1_000_000)

    assert high_impact_price > low_impact_price


def test_one_word_limit_lock_rejection():
    dates = pd.bdate_range("2026-01-05", periods=3)

    # One-word limit up bar: open == high == low == close == 11.0 (limit up from 10.0)
    limit_up_frame = pd.DataFrame({
        "open": [10.0, 11.0, 11.0],
        "high": [10.0, 11.0, 11.0],
        "low": [10.0, 11.0, 11.0],
        "close": [10.0, 11.0, 11.0],
        "volume": [1_000_000, 100, 1_000_000],
    }, index=dates)

    decisions = pd.DataFrame([decision(dates[0], "000001", action="BUY")])

    result = simulate_portfolio({"000001": limit_up_frame}, decisions, initial_cash=100_000)

    assert any(
        item["symbol"] == "000001" and item["reason"] in {"LIMIT_UP_LOCKED", "LIMIT_UP"}
        for item in result.rejected_orders
    )
