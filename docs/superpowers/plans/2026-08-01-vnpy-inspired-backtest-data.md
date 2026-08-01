# vn.py-Inspired Backtest, Indicator, and Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add validated market-data contracts, causal standardized indicators, a reconciled daily backtest ledger, and richer risk metrics without changing the existing Web API contract.

**Architecture:** Keep SQLite/Pandas, `KLineBacktestEngine`, and `simulate_portfolio` as the production path. Add two pure modules for market-data validation/indicators and one pure module for ledger/statistics; wire them into the existing engines without adding vn.py, TA-Lib, Backtrader, or a generic event framework.

**Tech Stack:** Python 3, Pandas, NumPy, SQLite, pytest, existing vanilla JavaScript frontend.

## Global Constraints

- Existing Web API request parameters, response keys, field names, defaults, and units remain compatible.
- New response data is additive only: `daily_results`, new metric fields, and `backtest_metadata.data_provenance`.
- Production `code/` and `web/` must not import vn.py, TA-Lib, or Backtrader.
- Indicators and DRL normalization must be prefix invariant and never backfill future values.
- QFQ replacement and its provenance update must commit atomically.
- Existing research limitations remain reported.
- The project directory is not a Git repository, so replace every commit step with a test checkpoint and do not initialize Git.

## File Structure

- Create `code/market_data.py`: pure daily-bar normalization and validation.
- Create `code/technical_indicators.py`: pure indicator, label, and causal normalization functions.
- Create `code/backtest_metrics.py`: pure daily-ledger validation and performance calculations.
- Modify `code/ashare_data_engine.py`: provenance table and atomic catalog update.
- Modify `code/ashare_factor_pipeline.py`: parameterized reads and shared indicator functions.
- Modify `code/portfolio_simulator.py`: fee components, daily PnL fields, and terminal order expiry.
- Modify `code/backtest_kline_engine.py`: market validation, ledger/metrics integration, provenance output, and error mapping.
- Create `tests/test_market_data.py`, `tests/test_technical_indicators.py`, and `tests/test_backtest_metrics.py`.
- Modify existing data, simulator, integration, and Web validation tests only where additive output requires coverage.

---

### Task 1: Canonical Daily-Bar Contract

**Files:**
- Create: `code/market_data.py`
- Create: `tests/test_market_data.py`

**Interfaces:**
- Consumes: a `pd.DataFrame` with daily OHLCV data and optional `symbol` column.
- Produces: `MarketDataError(ValueError)` and `validate_daily_bars(frame: pd.DataFrame, symbol: str | None = None) -> pd.DataFrame`.

- [ ] **Step 1: Write failing contract tests**

```python
import numpy as np
import pandas as pd
import pytest

from market_data import MarketDataError, validate_daily_bars


def valid_bars():
    return pd.DataFrame({
        "trade_date": ["2026-01-06", "2026-01-05"],
        "open": [10.5, 10.0],
        "high": [10.8, 10.2],
        "low": [10.4, 9.9],
        "close": [10.7, 10.1],
        "volume": [1200, 1000],
        "amount": [12_840, 10_100],
        "symbol": ["000001", "000001"],
    })


def test_valid_daily_bars_are_sorted_and_indexed():
    result = validate_daily_bars(valid_bars(), "000001")
    assert result["trade_date"].tolist() == [
        pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")
    ]


@pytest.mark.parametrize("mutation", [
    lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
    lambda frame: frame.assign(high=[10.0, 10.2]),
    lambda frame: frame.assign(close=[np.inf, 10.1]),
    lambda frame: frame.assign(volume=[-1, 1000]),
    lambda frame: frame.assign(symbol=["000001", "000002"]),
])
def test_invalid_daily_bars_raise(mutation):
    with pytest.raises(MarketDataError):
        validate_daily_bars(mutation(valid_bars()), "000001")
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_market_data.py`

Expected: collection fails because `market_data` does not exist.

- [ ] **Step 3: Implement the smallest validation module**

```python
"""Canonical validation for daily A-share bar frames."""

import numpy as np
import pandas as pd


REQUIRED_BAR_COLUMNS = (
    "trade_date", "open", "high", "low", "close", "volume", "amount"
)


class MarketDataError(ValueError):
    pass


def validate_daily_bars(frame: pd.DataFrame,
                        symbol: str | None = None) -> pd.DataFrame:
    missing = [column for column in REQUIRED_BAR_COLUMNS
               if column not in frame.columns]
    if missing:
        raise MarketDataError(f"missing bar columns: {', '.join(missing)}")

    clean = frame.copy()
    try:
        clean["trade_date"] = pd.to_datetime(clean["trade_date"], errors="raise")
        numeric = ["open", "high", "low", "close", "volume", "amount"]
        clean[numeric] = clean[numeric].apply(pd.to_numeric, errors="raise")
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"invalid bar value: {exc}") from exc

    if clean["trade_date"].duplicated().any():
        raise MarketDataError("duplicate trade_date")
    if not np.isfinite(clean[numeric].to_numpy(dtype=float)).all():
        raise MarketDataError("non-finite bar value")
    if (clean[["open", "high", "low", "close"]] <= 0).any().any():
        raise MarketDataError("prices must be positive")
    if (clean[["volume", "amount"]] < 0).any().any():
        raise MarketDataError("volume and amount must be non-negative")
    if (
        (clean["low"] > clean[["open", "close"]].min(axis=1)).any()
        or (clean["high"] < clean[["open", "close"]].max(axis=1)).any()
        or (clean["low"] > clean["high"]).any()
    ):
        raise MarketDataError("invalid OHLC relationship")
    if symbol is not None and "symbol" in clean:
        values = set(clean["symbol"].astype(str))
        if values != {str(symbol)}:
            raise MarketDataError("mixed or unexpected symbol")
    return clean.sort_values("trade_date").reset_index(drop=True)
```

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/test_market_data.py`

Expected: all tests pass.

- [ ] **Step 5: Checkpoint**

Run: `python3 -m compileall -q code/market_data.py tests/test_market_data.py`

Expected: exit code 0.

---

### Task 2: QFQ Provenance and Parameterized Factor Reads

**Files:**
- Modify: `code/ashare_data_engine.py`
- Modify: `code/ashare_factor_pipeline.py`
- Modify: `tests/test_data_engine.py`
- Modify: `tests/test_market_data.py`

**Interfaces:**
- Consumes: `validate_daily_bars` from Task 1.
- Produces: `AShareDataEngine.get_stock_daily_provenance(symbol: str) -> dict | None` and catalog table `stock_daily_catalog`.

- [ ] **Step 1: Add failing provenance and SQL-boundary tests**

```python
def test_qfq_refresh_updates_provenance_atomically(tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    monkeypatch.setattr(
        ashare_data_engine.ak,
        "stock_zh_a_hist",
        lambda **_: history("000001", [10.0, 11.0]),
    )
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    engine.sync_stock_daily(
        symbols=["000001"], start_date="20240101", end_date="20240103"
    )

    provenance = engine.get_stock_daily_provenance("000001")
    assert {key: provenance[key] for key in (
        "symbol", "price_mode", "source", "start_date", "end_date",
        "row_count",
    )} == {
        "symbol": "000001",
        "price_mode": "QFQ",
        "source": "AKSHARE_STOCK_ZH_A_HIST",
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
        "row_count": 2,
    }
    assert provenance["updated_at"]


def test_qfq_catalog_failure_rolls_back_price_replacement(tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    with sqlite3.connect(engine.db_path) as conn:
        insert_bar(conn, "000001", "2024-01-01", 99.0)
        conn.execute("""
            INSERT INTO stock_daily_catalog VALUES (
                '000001', 'QFQ', 'OLD', '2024-01-01', '2024-01-01', 1,
                '2024-01-02 00:00:00'
            )
        """)
        conn.execute("""
            CREATE TRIGGER fail_catalog BEFORE UPDATE ON stock_daily_catalog
            BEGIN SELECT RAISE(ABORT, 'catalog failure'); END
        """)
    monkeypatch.setattr(
        ashare_data_engine.ak,
        "stock_zh_a_hist",
        lambda **_: history("000001", [10.0, 11.0]),
    )
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    engine.sync_stock_daily(
        symbols=["000001"], start_date="20240101", end_date="20240103"
    )

    with sqlite3.connect(engine.db_path) as conn:
        assert conn.execute(
            "SELECT close FROM stock_daily WHERE symbol='000001'"
        ).fetchall() == [(99.0,)]
        assert conn.execute(
            "SELECT source FROM stock_daily_catalog WHERE symbol='000001'"
        ).fetchone()[0] == "OLD"


def test_factor_query_treats_symbol_as_data(tmp_path, monkeypatch):
    import ashare_factor_pipeline
    from ashare_data_engine import AShareDataEngine
    from ashare_factor_pipeline import AShareFactorPipeline

    calls = []

    def read_sql(query, _conn, params=None):
        calls.append((query, params))
        return pd.DataFrame()

    monkeypatch.setattr(ashare_factor_pipeline.pd, "read_sql_query", read_sql)
    engine = AShareDataEngine(tmp_path / "quant.db")
    pipeline = AShareFactorPipeline(engine.db_path)
    assert pipeline.extract_factors("000001' OR 1=1 --") is None
    assert "symbol=?" in calls[0][0]
    assert calls[0][1][0] == "000001' OR 1=1 --"
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_data_engine.py::test_qfq_refresh_updates_provenance_atomically tests/test_data_engine.py::test_qfq_catalog_failure_rolls_back_price_replacement tests/test_market_data.py::test_factor_query_treats_symbol_as_data`

Expected: provenance method is absent and the interpolated query does not satisfy the new boundary.

- [ ] **Step 3: Add the catalog schema and atomic upsert**

Add this table to `_init_db`:

```sql
CREATE TABLE IF NOT EXISTS stock_daily_catalog (
    symbol TEXT PRIMARY KEY,
    price_mode TEXT NOT NULL,
    source TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Validate `df_clean` with `validate_daily_bars(df_clean, sym)` before converting
it to insert tuples. In the existing replacement transaction, after inserting
`rows`, execute:

```python
conn.execute("""
    INSERT INTO stock_daily_catalog (
        symbol, price_mode, source, start_date, end_date, row_count, updated_at
    ) VALUES (?, 'QFQ', 'AKSHARE_STOCK_ZH_A_HIST', ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(symbol) DO UPDATE SET
        price_mode=excluded.price_mode,
        source=excluded.source,
        start_date=excluded.start_date,
        end_date=excluded.end_date,
        row_count=excluded.row_count,
        updated_at=CURRENT_TIMESTAMP
""", (
    sym,
    df_clean["trade_date"].min(),
    df_clean["trade_date"].max(),
    len(df_clean),
))
```

Add:

```python
def get_stock_daily_provenance(self, symbol):
    with self.get_connection() as conn:
        row = conn.execute("""
            SELECT symbol, price_mode, source, start_date, end_date, row_count,
                   updated_at
            FROM stock_daily_catalog WHERE symbol=?
        """, (str(symbol),)).fetchone()
    if row is None:
        return None
    keys = ("symbol", "price_mode", "source", "start_date", "end_date",
            "row_count", "updated_at")
    return dict(zip(keys, row))
```

- [ ] **Step 4: Parameterize `extract_factors` and validate its frame**

Build clauses and parameters rather than interpolating values:

```python
clauses = ["symbol=?"]
params = [str(symbol)]
if start_date:
    clauses.append("trade_date>=?")
    params.append(str(start_date))
if end_date:
    clauses.append("trade_date<=?")
    params.append(str(end_date))
query = (
    "SELECT * FROM stock_daily WHERE "
    + " AND ".join(clauses)
    + " ORDER BY trade_date"
)
with self.get_connection() as conn:
    df = pd.read_sql_query(query, conn, params=params)
if not df.empty:
    df = validate_daily_bars(df, str(symbol))
```

- [ ] **Step 5: Verify GREEN and rollback preservation**

Run: `pytest -q tests/test_data_engine.py tests/test_market_data.py`

Expected: all tests pass, including existing empty-refresh preservation tests.

---

### Task 3: Causal Standardized Indicators

**Files:**
- Create: `code/technical_indicators.py`
- Create: `tests/test_technical_indicators.py`
- Modify: `code/ashare_factor_pipeline.py`

**Interfaces:**
- Consumes: validated daily bars from Task 1.
- Produces:
  - `calculate_technical_indicators(frame: pd.DataFrame) -> pd.DataFrame`
  - `build_forward_return_target(close: pd.Series, periods: int = 5) -> pd.Series`
  - `causal_expanding_zscore(frame: pd.DataFrame) -> pd.DataFrame`

- [ ] **Step 1: Write failing formula and causality tests**

```python
import numpy as np
import pandas as pd
import pytest

from technical_indicators import (
    calculate_technical_indicators,
    causal_expanding_zscore,
)


def indicator_bars(length=40):
    close = pd.Series(np.arange(10, length + 10, dtype=float))
    return pd.DataFrame({
        "trade_date": pd.bdate_range("2026-01-01", periods=length),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000.0,
        "amount": close * 1000,
    })


def test_wilder_rsi_atr_and_population_bollinger():
    result = calculate_technical_indicators(indicator_bars())
    assert result["rsi_14"].iloc[-1] == 100.0
    assert result["atr_14"].iloc[-1] == 2.0
    assert result["boll_upper"].iloc[19] == pytest.approx(
        19.5 + 2 * np.std(np.arange(10, 30), ddof=0)
    )


def test_indicators_are_prefix_invariant():
    bars = indicator_bars(80)
    short = calculate_technical_indicators(bars.iloc[:50])
    long = calculate_technical_indicators(bars)
    pd.testing.assert_frame_equal(short, long.iloc[:50])


def test_expanding_normalization_is_prefix_invariant():
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 100.0]})
    short = causal_expanding_zscore(frame.iloc[:3])
    long = causal_expanding_zscore(frame)
    pd.testing.assert_frame_equal(short, long.iloc[:3])
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_technical_indicators.py`

Expected: collection fails because `technical_indicators` does not exist.

- [ ] **Step 3: Implement pure formulas**

```python
"""Causal technical indicators used by factors and backtests."""

import numpy as np
import pandas as pd


def _wilder_average(values: pd.Series, periods: int) -> pd.Series:
    return values.ewm(
        alpha=1 / periods, adjust=False, min_periods=periods
    ).mean()


def calculate_technical_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    result = pd.DataFrame(index=frame.index)

    result["return_1d"] = close.pct_change(1)
    result["return_5d"] = close.pct_change(5)
    result["return_20d"] = close.pct_change(20)
    result["log_return"] = np.log(close / close.shift(1))
    for periods in (5, 10, 20, 60):
        average = close.rolling(periods).mean()
        result[f"ma_{periods}"] = average
        result[f"bias_{periods}"] = (close - average) / average

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    result["macd_dif"] = ema12 - ema26
    result["macd_dea"] = result["macd_dif"].ewm(
        span=9, adjust=False
    ).mean()
    result["macd_hist"] = (
        result["macd_dif"] - result["macd_dea"]
    ) * 2

    delta = close.diff()
    average_gain = _wilder_average(delta.clip(lower=0), 14)
    average_loss = _wilder_average(-delta.clip(upper=0), 14)
    rs = average_gain / average_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    result["rsi_14"] = rsi.where(average_loss.ne(0), 100.0)

    true_range = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    result["atr_14"] = _wilder_average(true_range, 14)
    result["norm_atr"] = result["atr_14"] / close

    std20 = close.rolling(20).std(ddof=0)
    result["boll_upper"] = result["ma_20"] + 2 * std20
    result["boll_lower"] = result["ma_20"] - 2 * std20
    width = result["boll_upper"] - result["boll_lower"]
    result["boll_pct_b"] = (close - result["boll_lower"]) / width
    result["vol_ma_5"] = volume.rolling(5).mean()
    result["vol_ma_20"] = volume.rolling(20).mean()
    result["vol_ratio"] = volume / result["vol_ma_20"]
    return result


def build_forward_return_target(close: pd.Series,
                                periods: int = 5) -> pd.Series:
    return np.log(close.shift(-periods) / close)


def causal_expanding_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    mean = frame.expanding(min_periods=2).mean().shift(1)
    std = frame.expanding(min_periods=2).std(ddof=0).shift(1)
    return ((frame - mean) / std.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)
```

- [ ] **Step 4: Replace duplicate factor formulas without changing columns**

In `extract_factors`, set `trade_date` as the index, calculate indicators,
copy every returned column onto the validated bar frame, then attach the
compatibility label:

```python
df = df.set_index("trade_date")
indicators = calculate_technical_indicators(df)
for column in indicators:
    df[column] = indicators[column]
df["target_5d_return"] = build_forward_return_target(df["close"])
return df
```

In `prepare_drl_environment_matrix`, replace full-dataset mean/std with:

```python
normalized = causal_expanding_zscore(df_factors[feature_cols].astype(float))
features = normalized.to_numpy(dtype=float)
```

- [ ] **Step 5: Verify GREEN and factor compatibility**

Run: `pytest -q tests/test_technical_indicators.py tests/test_causal_ml.py tests/test_backtest_integration.py`

Expected: all tests pass and existing factor column names remain available.

---

### Task 4: Execution Audit and Reconciled Daily PnL

**Files:**
- Modify: `code/portfolio_simulator.py`
- Modify: `tests/test_portfolio_simulator.py`

**Interfaces:**
- Consumes: existing market frames and decision DataFrame.
- Produces: additive fill fee components and additive equity-curve daily fields.

- [ ] **Step 1: Add failing order-expiry and reconciliation tests**

```python
def test_terminal_action_is_expired_instead_of_silently_dropped():
    frame = bars([10, 10, 10])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[-1], action="BUY")]),
        initial_cash=100_000,
    )
    assert any(
        item["status"] == "EXPIRED"
        and item["reason"] == "END_OF_DATA"
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
    assert sum(point["net_pnl"] for point in result.equity_curve) == (
        pytest.approx(result.final_equity - result.initial_cash)
    )
    assert all(
        "holding_pnl" in point and "trading_pnl" in point
        for point in result.equity_curve
    )
```

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_portfolio_simulator.py::test_terminal_action_is_expired_instead_of_silently_dropped tests/test_portfolio_simulator.py::test_daily_pnl_and_costs_reconcile_to_equity`

Expected: no terminal audit item and no daily PnL fields.

- [ ] **Step 3: Add fee components to fills**

For each fill, preserve `fees` and add; use the existing `buy_fees` or
`sell_fees` value as `recorded_fees`:

```python
transfer_fee = gross * fee_schedule.transfer_fee_rate
stamp_duty = (
    gross * _stamp_duty_rate(fee_schedule, date)
    if side == "SELL" else 0.0
)
commission = recorded_fees - transfer_fee - stamp_duty
fill.update({
    "commission": commission,
    "transfer_fee": transfer_fee,
    "stamp_duty": stamp_duty,
    "slippage": abs(fill_price - raw_price) * shares,
})
```

Use `stamp_duty = 0.0` for buys.

- [ ] **Step 4: Calculate daily result fields inside the shared simulator**

At the start of each date, snapshot `start_shares`. After fills and close marks,
calculate:

```python
def close_at(symbol):
    return float(market[symbol].loc[date, "close"])


holding_pnl = sum(
    shares * (close_at(symbol) - _previous_close(market[symbol], date))
    for symbol, shares in start_shares.items()
    if _previous_close(market[symbol], date) is not None
)
day_fills = fills[fill_start:]
trading_pnl = sum(
    (1 if fill["side"] == "BUY" else -1)
    * fill["shares"]
    * (close_at(fill["symbol"]) - fill["raw_price"])
    for fill in day_fills
)
commission = sum(fill["commission"] for fill in day_fills)
transfer_fee = sum(fill["transfer_fee"] for fill in day_fills)
stamp_duty = sum(fill["stamp_duty"] for fill in day_fills)
slippage = sum(fill["slippage"] for fill in day_fills)
net_pnl = equity - previous_equity
```

Append these additive fields to each existing equity point:

```python
{
    "start_equity": previous_equity,
    "holding_pnl": holding_pnl,
    "trading_pnl": trading_pnl,
    "commission": commission,
    "transfer_fee": transfer_fee,
    "stamp_duty": stamp_duty,
    "slippage": slippage,
    "turnover": sum(fill["gross_value"] for fill in day_fills),
    "fill_count": len(day_fills),
    "net_pnl": net_pnl,
}
```

Assert in the test that
`holding_pnl + trading_pnl - commission - transfer_fee - stamp_duty - slippage`
matches `net_pnl` within one cent.

- [ ] **Step 5: Record terminal actionable decisions as expired**

Before skipping scheduling on the final date, convert final-date BUY/SELL rows
to audit records:

```python
{
    "decision_id": decision_id,
    "symbol": str(row["symbol"]),
    "side": action,
    "decision_time": date,
    "execution_time": None,
    "status": "EXPIRED",
    "reason": "END_OF_DATA",
    "model_version": row.get("model_version", ""),
}
```

- [ ] **Step 6: Verify GREEN**

Run: `pytest -q tests/test_portfolio_simulator.py`

Expected: all simulator tests pass.

---

### Task 5: Daily Ledger and Performance Statistics

**Files:**
- Create: `code/backtest_metrics.py`
- Create: `tests/test_backtest_metrics.py`

**Interfaces:**
- Consumes: `SimulationResult` with enriched equity curve from Task 4.
- Produces:
  - `build_daily_ledger(simulation) -> list[dict]`
  - `calculate_performance(daily_results: list[dict], initial_capital: float, annual_days: int = 252) -> dict`

- [ ] **Step 1: Write failing ledger/statistics tests**

```python
import numpy as np
import pandas as pd
import pytest

from backtest_metrics import build_daily_ledger, calculate_performance
from portfolio_simulator import simulate_portfolio


def sample_simulation():
    dates = pd.bdate_range("2026-01-05", periods=4)
    market = pd.DataFrame({
        "open": [10.0, 10.5, 12.0, 11.5],
        "high": [10.2, 10.7, 12.2, 11.7],
        "low": [9.8, 10.3, 11.8, 11.3],
        "close": [10.0, 10.6, 12.0, 11.5],
        "volume": [1_000_000] * 4,
    }, index=dates)
    decisions = pd.DataFrame([{
        "decision_time": dates[0],
        "symbol": "000001",
        "action": "BUY",
        "target_fraction": 0.2,
        "reason": "test",
        "model_version": "v1",
    }])
    return simulate_portfolio(
        {"000001": market}, decisions, initial_cash=100_000
    )


def test_daily_ledger_reconciles_simulation():
    simulation = sample_simulation()
    ledger = build_daily_ledger(simulation)
    assert ledger[-1]["end_equity"] == simulation.final_equity
    assert sum(row["net_pnl"] for row in ledger) == pytest.approx(
        simulation.final_equity - simulation.initial_cash,
        abs=0.01,
    )


def test_performance_metrics_are_finite():
    simulation = sample_simulation()
    metrics = calculate_performance(
        build_daily_ledger(simulation), simulation.initial_cash,
    )
    assert set(metrics) == {
        "annualized_volatility_pct", "sharpe_ratio", "sortino_ratio",
        "calmar_ratio", "max_drawdown_duration_days",
        "total_turnover_cny", "turnover_ratio",
    }
    assert all(np.isfinite(value) for value in metrics.values())
```

Create `sample_simulation` locally in this test file by calling the existing
`simulate_portfolio`; do not add a global fixture.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_backtest_metrics.py`

Expected: collection fails because `backtest_metrics` does not exist.

- [ ] **Step 3: Implement ledger conversion**

```python
import numpy as np
import pandas as pd


def build_daily_ledger(simulation):
    ledger = [{
        "date": pd.Timestamp(point["date"]).strftime("%Y-%m-%d"),
        "start_equity": float(point["start_equity"]),
        "end_equity": float(point["equity"]),
        "cash": float(point["cash"]),
        "market_value": float(point["gross_exposure"]),
        "holding_pnl": float(point["holding_pnl"]),
        "trading_pnl": float(point["trading_pnl"]),
        "commission": float(point["commission"]),
        "transfer_fee": float(point["transfer_fee"]),
        "stamp_duty": float(point["stamp_duty"]),
        "slippage": float(point["slippage"]),
        "turnover": float(point["turnover"]),
        "fill_count": int(point["fill_count"]),
        "net_pnl": float(point["net_pnl"]),
        "daily_return": float(point["daily_return"]),
        "drawdown": float(point["drawdown"]),
    } for point in simulation.equity_curve]

    equity_change = simulation.final_equity - simulation.initial_cash
    if abs(sum(row["net_pnl"] for row in ledger) - equity_change) > 0.01:
        raise ValueError("daily ledger does not reconcile")
    for field in ("commission", "transfer_fee", "stamp_duty", "slippage"):
        daily_total = sum(row[field] for row in ledger)
        fill_total = sum(float(fill[field]) for fill in simulation.fills)
        if abs(daily_total - fill_total) > 0.01:
            raise ValueError("daily ledger costs do not reconcile")
    return ledger
```

The returned values remain unrounded so summing a long ledger cannot introduce
cent-level drift. The Web renderer may format them without changing the JSON
units.

- [ ] **Step 4: Implement finite aggregate metrics**

Use daily decimal returns. Annual volatility is standard deviation times
`sqrt(annual_days)`. Sharpe is annualized mean divided by annualized standard
deviation. Sortino uses the square root of the mean squared negative returns.
Calmar uses the compounded annual return divided by absolute maximum drawdown.
Maximum drawdown duration is the maximum calendar-day distance from the last
equity high to recovery or the end date. Turnover ratio is total turnover
divided by average equity.

Return `0.0` for undefined ratios and sanitize every result with
`np.nan_to_num`.

```python
def calculate_performance(daily_results, initial_capital, annual_days=252):
    zero = {
        "annualized_volatility_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "max_drawdown_duration_days": 0,
        "total_turnover_cny": 0.0,
        "turnover_ratio": 0.0,
    }
    if not daily_results:
        return zero

    frame = pd.DataFrame(daily_results)
    returns = frame["daily_return"].astype(float)
    deviation = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    volatility = deviation * np.sqrt(annual_days)
    sharpe = (
        float(returns.mean()) / deviation * np.sqrt(annual_days)
        if deviation else 0.0
    )
    downside = np.sqrt(np.mean(np.minimum(returns.to_numpy(), 0.0) ** 2))
    sortino = (
        float(returns.mean()) * annual_days
        / (downside * np.sqrt(annual_days))
        if downside else 0.0
    )

    dates = pd.to_datetime(frame["date"])
    elapsed_days = max(1, (dates.iloc[-1] - dates.iloc[0]).days)
    final_equity = float(frame["end_equity"].iloc[-1])
    annual_return = (
        (final_equity / float(initial_capital)) ** (365 / elapsed_days) - 1
        if final_equity > 0 else -1.0
    )
    max_drawdown = float(frame["drawdown"].max())
    calmar = annual_return / max_drawdown if max_drawdown else 0.0

    peak_date = dates.iloc[0]
    peak_equity = float(frame["end_equity"].iloc[0])
    max_duration = 0
    for date, equity in zip(dates, frame["end_equity"].astype(float)):
        if equity >= peak_equity:
            peak_equity = equity
            peak_date = date
        else:
            max_duration = max(max_duration, (date - peak_date).days)

    turnover = float(frame["turnover"].sum())
    average_equity = float(frame["end_equity"].mean())
    result = {
        "annualized_volatility_pct": volatility * 100,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "max_drawdown_duration_days": max_duration,
        "total_turnover_cny": turnover,
        "turnover_ratio": turnover / average_equity if average_equity else 0.0,
    }
    return {
        key: int(value) if key == "max_drawdown_duration_days" else float(
            np.nan_to_num(value, nan=0.0, posinf=0.0, neginf=0.0)
        )
        for key, value in result.items()
    }
```

- [ ] **Step 5: Verify GREEN**

Run: `pytest -q tests/test_backtest_metrics.py`

Expected: all tests pass.

---

### Task 6: Backtest and API Integration

**Files:**
- Modify: `code/backtest_kline_engine.py`
- Modify: `tests/test_backtest_integration.py`
- Modify: `tests/test_web_validation.py`

**Interfaces:**
- Consumes: Tasks 1, 2, and 5 interfaces.
- Produces: additive `daily_results`, metrics, and `data_provenance` in both backtest response shapes.

- [ ] **Step 1: Add failing compatibility integration tests**

Use this assertion helper for both `run_kline_backtest` and
`run_portfolio_backtest`:

```python
def assert_enriched_backtest(result, metrics_key):
    metrics = result[metrics_key]
    assert len(result["daily_results"]) == len(result["equity_curve"])
    assert result["daily_results"][-1]["end_equity"] == pytest.approx(
        metrics["final_equity"]
    )
    for field in (
        "annualized_volatility_pct", "sharpe_ratio", "sortino_ratio",
        "calmar_ratio", "max_drawdown_duration_days",
        "total_turnover_cny", "turnover_ratio",
    ):
        assert field in metrics
    assert result["backtest_metadata"]["data_provenance"]


```

Call `assert_enriched_backtest(result, "metrics")` at the end of the existing
`test_single_stock_backtest_is_causal_and_closes_positions`, and call
`assert_enriched_backtest(result, "portfolio_metrics")` at the end of the
existing `test_portfolio_engine_uses_one_account_and_real_drawdown`.

Keep the existing exact metadata assertions by extending their expected
dictionary; do not weaken them to subset assertions.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/test_backtest_integration.py`

Expected: new keys are absent.

- [ ] **Step 3: Validate loaded market frames at the backtest boundary**

After `_load_market`, call `validate_daily_bars(frame, clean_symbol)`. Because
the query currently omits `symbol`, either add `symbol` to the SELECT or pass
`None`; prefer adding it so mixed-symbol validation remains active. Catch
`MarketDataError` in both public run methods and return:

```python
{"error": f"行情数据质量错误: {exc}"}
```

- [ ] **Step 4: Add ledger and performance fields**

After simulation:

```python
daily_results = build_daily_ledger(simulation)
performance = calculate_performance(daily_results, float(initial_capital))
```

Merge `performance` into the existing metrics dictionary and add
`"daily_results": daily_results` at the response root. Do not remove
`equity_curve`.

- [ ] **Step 5: Add dataset provenance**

Extend `_backtest_metadata` to accept a provenance value. For a single symbol,
pass its catalog record or this explicit fallback:

```python
{
    "symbol": symbol,
    "price_mode": "QFQ",
    "source": "LEGACY_UNCATALOGED",
    "start_date": market.index.min().strftime("%Y-%m-%d"),
    "end_date": market.index.max().strftime("%Y-%m-%d"),
    "row_count": len(market),
}
```

For a portfolio, return a list in input symbol order.

- [ ] **Step 6: Verify API compatibility**

Run: `pytest -q tests/test_backtest_integration.py tests/test_web_validation.py`

Expected: all existing and new assertions pass.

---

### Task 7: Full Regression and Commercial Boundary

**Files:**
- Modify only files implicated by failures.

**Interfaces:**
- Consumes: completed Tasks 1-6.
- Produces: verified implementation with no new runtime dependency.

- [ ] **Step 1: Run the full suite**

Run: `pytest -q`

Expected: at least 54 tests pass, plus all tests added by this plan.

- [ ] **Step 2: Run syntax checks**

Run: `python3 -m compileall -q code tests`

Expected: exit code 0.

Run: `node --check web/app.js`

Expected: exit code 0.

- [ ] **Step 3: Scan production licensing boundary**

Run: `rg -n "import (vnpy|talib|backtrader)|from (vnpy|talib|backtrader)|GPL-3\\.0|GNU GENERAL PUBLIC LICENSE" code web`

Expected: no matches and `rg` exit code 1.

- [ ] **Step 4: Run the existing isolated Backtrader differential oracle**

Run:

```bash
PYTHONPATH=/private/tmp/lianghua-backtrader-oracle:$PWD/code \
python3 /private/tmp/verify_lianghua_backtrader.py
```

Expected: `native_final_equity` exactly equals `backtrader_final_equity`.

- [ ] **Step 5: Independent review checkpoint**

Review only for Critical/Important findings in:

- causal indicator and DRL normalization;
- atomic data/provenance refresh;
- daily PnL and cost reconciliation;
- event ordering and terminal expiry;
- Web API backward compatibility;
- commercial dependency boundary.

Fix confirmed findings with one focused failing regression test each, then
repeat Steps 1-4.
