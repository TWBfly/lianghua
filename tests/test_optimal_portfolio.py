import numpy as np
import pandas as pd
from optimal_portfolio_engine import SymbolAutoTuner, OptimalPortfolioEngine


def test_symbol_auto_tuner():
    tuner = SymbolAutoTuner()
    df_kline = pd.DataFrame({
        "close": 10.0 + np.arange(150) * 0.05 + np.sin(np.arange(150) / 4)
    })
    params = tuner.find_robust_parameters(df_kline)
    assert params["is_optimized"] is True
    assert "pt_mult" in params
    assert "sl_mult" in params
    assert "min_buy_prob" in params


def test_theoretical_portfolio_benefit():
    benefit = OptimalPortfolioEngine.calculate_theoretical_portfolio_benefit(n_assets=12, avg_corr=0.20)
    assert benefit["sharpe_boost_factor"] > 1.5
    assert benefit["drawdown_reduction_pct"] > 40.0
