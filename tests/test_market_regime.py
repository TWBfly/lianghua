import numpy as np
import pandas as pd

import backtest_kline_engine
from backtest_kline_engine import KLineBacktestEngine
from market_regime import (
    apply_regime_overlay,
    build_regime_observations,
    state_names_from_means,
    walk_forward_regimes,
)
from test_backtest_integration import (
    build_test_db,
    deterministic_predictions,
)


class FakeHMM:
    def fit(self, values):
        self.startprob_ = np.array([0.8, 0.1, 0.1])
        self.transmat_ = np.array([
            [0.90, 0.05, 0.05],
            [0.05, 0.90, 0.05],
            [0.05, 0.05, 0.90],
        ])
        self.means_ = np.array([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
            [0.0, 0.0, 0.0],
        ])
        self.covars_ = np.ones((3, 3))
        return self


def index_bars(rows=90):
    dates = pd.bdate_range("2025-01-01", periods=rows)
    close = 100 * np.exp(
        np.sin(np.arange(rows) / 7) * 0.01
        + np.arange(rows) * 0.0003
    )
    return pd.DataFrame({
        "trade_date": dates,
        "close": close,
    })


def test_observations_are_prefix_invariant():
    short = build_regime_observations(index_bars(70))
    long = build_regime_observations(index_bars(90))

    pd.testing.assert_frame_equal(short, long.loc[short.index])


def test_walk_forward_probabilities_are_prefix_invariant_and_causal():
    short = walk_forward_regimes(
        index_bars(70), FakeHMM, training_window=30, retrain_every=5
    )
    long = walk_forward_regimes(
        index_bars(90), FakeHMM, training_window=30, retrain_every=5
    )

    pd.testing.assert_frame_equal(short, long.loc[short.index])
    available = short[short["status"] == "AVAILABLE"]
    assert not available.empty
    assert (
        pd.to_datetime(available["trained_until"]) < available.index
    ).all()


def test_state_names_follow_trend_strength_mean():
    names = state_names_from_means(np.array([
        [0.0, 0.0, 0.1],
        [0.0, 0.0, -1.2],
        [0.0, 0.0, 0.8],
    ]))

    assert names == {
        0: "RANGE",
        1: "HIGH_VOL_BEAR",
        2: "LOW_VOL_BULL",
    }


def regime(state="RANGE", status="AVAILABLE"):
    return pd.Series({
        "state": state,
        "status": status,
        "p_low_vol_bull": 0.2,
        "p_range": 0.7,
        "p_high_vol_bear": 0.1,
        "model_version": "test-hmm",
        "trained_until": pd.Timestamp("2025-01-01"),
    })


def test_overlay_scales_range_and_blocks_bear_or_unavailable_buys():
    action, reason, fraction, features = apply_regime_overlay(
        "BUY", "ENTRY", 0.2, regime()
    )

    assert (action, reason, fraction) == (
        "BUY", "ENTRY|REGIME_RANGE_HALF", 0.1
    )
    assert features["market_regime"] == "RANGE"
    assert apply_regime_overlay(
        "BUY", "ENTRY", 0.2, regime("HIGH_VOL_BEAR")
    )[:3] == ("HOLD", "REGIME_HIGH_VOL_BEAR", 0.0)
    assert apply_regime_overlay(
        "BUY",
        "ENTRY",
        0.2,
        regime(status="INSUFFICIENT_HISTORY"),
    )[:3] == ("HOLD", "REGIME_UNAVAILABLE", 0.0)


def test_overlay_never_blocks_sell():
    assert apply_regime_overlay(
        "SELL", "EXIT", 0.2, regime("HIGH_VOL_BEAR")
    )[:3] == ("SELL", "EXIT", 0.2)
    assert apply_regime_overlay(
        "SELL", "EXIT", 0.2, None
    )[:3] == ("SELL", "EXIT", 0.2)


def add_index_daily(engine):
    with engine.get_connection() as conn:
        rows = conn.execute("""
            SELECT trade_date, open, close, high, low, volume, amount,
                   pct_chg
            FROM stock_daily WHERE symbol='000001'
            ORDER BY trade_date
        """).fetchall()
        conn.executemany(
            "INSERT INTO index_daily VALUES "
            "('000300', ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def fixed_regimes(state, calls):
    def build(frame):
        calls.append(frame.copy())
        index = pd.to_datetime(frame["trade_date"])
        return pd.DataFrame({
            "state": state,
            "p_low_vol_bull": 1.0 if state == "LOW_VOL_BULL" else 0.0,
            "p_range": 1.0 if state == "RANGE" else 0.0,
            "p_high_vol_bear": (
                1.0 if state == "HIGH_VOL_BEAR" else 0.0
            ),
            "status": "AVAILABLE",
            "trained_until": index - pd.offsets.BDay(1),
            "model_version": "test-regime-v1",
        }, index=index)
    return build


def test_portfolio_builds_one_shared_regime_frame(monkeypatch, tmp_path):
    engine = KLineBacktestEngine(build_test_db(
        tmp_path, symbols=("000001", "000002")
    ))
    add_index_daily(engine)
    calls = []
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_regimes",
        fixed_regimes("RANGE", calls),
    )
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )

    result = engine.run_portfolio_backtest(
        100_000,
        "2025-01-01",
        "2025-12-31",
        symbols=["000001", "000002"],
        backtest_mode="RESEARCH_PROXY",
        regime_filter=True,
    )

    assert "error" not in result
    assert len(calls) == 1
    metadata = result["backtest_metadata"]["market_regime"]
    assert metadata["enabled"] is True
    assert metadata["scaled_buy_count"] > 0
    assert metadata["filtered_buy_count"] == 0


def test_bear_regime_blocks_buy_but_preserves_sell(
        monkeypatch, tmp_path):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    add_index_daily(engine)
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_regimes",
        fixed_regimes("HIGH_VOL_BEAR", []),
    )
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )
    original = backtest_kline_engine.simulate_portfolio
    seen = {}

    def recording_simulator(market, decisions, initial_cash, **kwargs):
        seen["decisions"] = decisions.copy()
        return original(market, decisions, initial_cash, **kwargs)

    monkeypatch.setattr(
        backtest_kline_engine, "simulate_portfolio", recording_simulator
    )

    result = engine.run_kline_backtest(
        "000001",
        "2025-01-01",
        "2025-12-31",
        100_000,
        backtest_mode="RESEARCH_PROXY",
        regime_filter=True,
    )

    assert "error" not in result
    decisions = seen["decisions"]
    assert "BUY" not in set(decisions["action"])
    assert "SELL" in set(decisions["action"])
    assert "REGIME_HIGH_VOL_BEAR" in set(decisions["reason"])
    assert result["backtest_metadata"]["market_regime"][
        "filtered_buy_count"
    ] > 0


def test_regime_filter_and_evolution_are_rejected(tmp_path):
    engine = KLineBacktestEngine(build_test_db(tmp_path))

    result = engine.run_kline_backtest(
        regime_filter=True,
        run_evolution=True,
        backtest_mode="RESEARCH_PROXY",
    )

    assert result["error_code"] == "REGIME_EVOLUTION_UNSUPPORTED"
