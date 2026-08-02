import numpy as np
import pandas as pd

from market_regime import (
    apply_regime_overlay,
    build_regime_observations,
    state_names_from_means,
    walk_forward_regimes,
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
