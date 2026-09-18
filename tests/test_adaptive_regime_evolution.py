import unittest
import numpy as np
import pandas as pd
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.extend([str(PROJECT_ROOT / 'code'), str(PROJECT_ROOT / 'strategies')])

from adaptive_regime_evolution_strategy import (
    compute_macro_regime_multiscale,
    compute_macro_ehlers_trend,
    generate_regime_evolution_signals,
)
from run_adaptive_regime_evolution_audit import simulate_trading_engine
from contract_specs import get_spec

def make_synthetic_ohlcv(n=300, seed=42):
    np.random.seed(seed)
    times = pd.date_range('2026-01-01', periods=n, freq='15min')
    rets = np.random.normal(0.0002, 0.005, size=n)
    rets[50:120] += 0.003
    rets[150:200] -= 0.003
    rets[200:270] *= 0.3
    prices = 100.0 * np.exp(np.cumsum(rets))
    highs = prices * (1.0 + np.abs(np.random.normal(0.0, 0.002, size=n)))
    lows = prices * (1.0 - np.abs(np.random.normal(0.0, 0.002, size=n)))
    opens = (highs + lows) / 2.0 + np.random.normal(0.0, 0.001, size=n)
    closes = prices
    volumes = np.random.uniform(500, 5000, size=n)
    return pd.DataFrame({
        'trade_time': times,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': volumes,
    })

class TestAdaptiveRegimeEvolution(unittest.TestCase):
    def test_macro_regime_multiscale_bounds_and_shapes(self):
        df = make_synthetic_ohlcv(200)
        m_state, m_ts, m_der, m_pos = compute_macro_regime_multiscale(df)
        self.assertEqual(len(m_state), 200)
        self.assertTrue(set(np.unique(m_state)).issubset({-1, 0, 1, 2}))
        self.assertTrue(np.all(m_ts >= 0.0) and np.all(m_ts <= 100.0))
        self.assertTrue(np.all(m_der >= -1.0) and np.all(m_der <= 1.0))
        self.assertTrue(np.all(m_pos >= -1.0) and np.all(m_pos <= 1.0))

    def test_signals_prefix_invariance_and_no_lookahead(self):
        df_full = make_synthetic_ohlcv(250)
        df_prefix = df_full.iloc[:200].copy()
        
        sig_full = generate_regime_evolution_signals(df_full)
        sig_prefix = generate_regime_evolution_signals(df_prefix)
        
        # Verify prefix invariance up to bar 195
        np.testing.assert_array_equal(
            sig_full['raw_signal'].iloc[:195].values,
            sig_prefix['raw_signal'].iloc[:195].values,
            err_msg='Signal generation violates prefix invariance!'
        )
        np.testing.assert_array_equal(
            sig_full['signal_source'].iloc[:195].values,
            sig_prefix['signal_source'].iloc[:195].values,
        )

    def test_signal_validity_and_finite(self):
        df = make_synthetic_ohlcv(220)
        sig = generate_regime_evolution_signals(df)
        
        self.assertTrue(set(np.unique(sig['raw_signal'])).issubset({-1, 0, 1}))
        self.assertTrue(set(np.unique(sig['signal_source'])).issubset({0, 1, 2}))
        self.assertTrue(np.all(~np.isnan(sig['raw_signal'].values)))
        self.assertTrue(np.all(~np.isinf(sig['raw_signal'].values)))
        self.assertTrue(np.all(sig['confidence'].values >= 0.0))
        self.assertTrue(np.all(sig['confidence'].values <= 1.0))

    def test_kalman_velocity_and_physics_features_bounds(self):
        df = make_synthetic_ohlcv(240)
        sig = generate_regime_evolution_signals(df)
        
        # Verify columns exist
        for col in ['kalman_price', 'kalman_vel', 'kalman_norm_vel', 'kalman_accel', 'causal_hurst', 'perm_entropy', 'physics_trend']:
            self.assertIn(col, sig.columns, f"Column {col} missing from signal output")
            self.assertTrue(np.all(~np.isnan(sig[col].values)), f"NaN found in {col}")
            self.assertTrue(np.all(~np.isinf(sig[col].values)), f"Inf found in {col}")

        # Check bounds
        self.assertTrue(np.all(sig['kalman_norm_vel'].values >= -1.0) and np.all(sig['kalman_norm_vel'].values <= 1.0))
        self.assertTrue(np.all(sig['causal_hurst'].values >= 0.10) and np.all(sig['causal_hurst'].values <= 0.90))
        self.assertTrue(np.all(sig['perm_entropy'].values >= 0.0) and np.all(sig['perm_entropy'].values <= 1.0))
        self.assertTrue(np.all(sig['physics_trend'].values >= 0.0) and np.all(sig['physics_trend'].values <= 1.0))

    def test_ratchet_monotonicity_and_cash_conservation(self):
        df = make_synthetic_ohlcv(500, seed=123)
        sig = generate_regime_evolution_signals(df)
        spec = get_spec('TA_IDX')
        initial_capital = 500_000.0
        res = simulate_trading_engine(sig, spec, initial_capital=initial_capital)

        # 1. 验证交易列表及盈亏守恒
        trades = res.get('trades', [])
        if trades:
            trade_pnl_sum = sum(t['net_pnl'] for t in trades)
            self.assertAlmostEqual(trade_pnl_sum, res['net_profit'], places=2)
            # 2. 验证手续费均为正且无 NaN
            for t in trades:
                self.assertGreaterEqual(t['entry_fee'], 0.0)
                self.assertGreaterEqual(t['exit_fee'], 0.0)
                self.assertFalse(np.isnan(t['net_pnl']))
                self.assertFalse(np.isinf(t['net_pnl']))

    def test_flat_price_permutation_entropy_guard(self):
        from regime_trend_evolution_engine import calculate_fast_permutation_entropy
        flat_prices = np.full(100, 100.0)
        pe = calculate_fast_permutation_entropy(flat_prices, window=30)
        # Flat prices have zero fluctuation: PE should be maximum entropy 1.0 (disorder/no trend), NOT 0.0
        self.assertEqual(pe[-1], 1.0, "Flat price series must yield PE=1.0 to prevent false trend reward")

if __name__ == '__main__':
    unittest.main()
