# TianJi 15M Non-Predictive Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one auditable, market-neutral, non-predictive TianJi 15-minute futures mode whose locked holdout is accepted only when its 5 bps payoff ratio, drawdown, trade-count, and return gates all pass.

**Architecture:** Preserve the current predictive path unchanged. Add an explicit `strategy_mode="tianji"` branch inside `futures_research_backtest.py` that reuses canonical loading, validation, 5m-to-15m aggregation, evidence writing, and provenance. TianJi gets frozen OHLCV scores, sector-constrained selections, a separate stateful next-open/ATR-stop ledger, and its own exact gate set so predictive labels and model attacks cannot leak into the run.

**Tech Stack:** Python 3.10, pandas, NumPy, pytest, SQLite; no new dependencies.

## Global Constraints

- Only modify `code/futures_research_backtest.py` and `tests/test_futures_research_backtest.py` for production behavior.
- Preserve the existing predictive default and all existing tests.
- TianJi requires `timeframe="15m"`, `predictive=false`, no labels, no fitting, no candidate or threshold selection, and no holdout tuning.
- Frozen score inputs: signed Kaufman efficiency, centered Donchian position, 5/20 momentum acceleration, and volume-weighted intraday intensity; worst 20% Amihud illiquidity is filtered.
- Rebalance every 16 bars; select up to four longs and four shorts; maximum two symbols per sector per side.
- Target gross exposure is at most `0.8x`, split into `0.4x` long and `0.4x` short; unfilled budget stays cash.
- Entry and signal exit occur at the next observed open. Initial stop is `1 ATR`; trailing stop is prior favorable extreme minus/plus `2.5 ATR`, never loosened; gap-through uses the worse open.
- Locked holdout is the final chronological 20% and is evaluated once.
- At 5 bps on entry and 5 bps on exit, acceptance requires payoff ratio `>= 1.8`, 15-minute maximum drawdown `<= 0.10`, at least `200` closed trades, and total return `> 0`.
- Report 10/15/20 bps stress results without substituting them for the 5 bps gate.
- Never overwrite an existing evidence directory or enable live trading.

---

### Task 1: Add the frozen TianJi research contract and causal scores

**Files:**
- Modify: `code/futures_research_backtest.py:30-91`
- Modify: `code/futures_research_backtest.py:343-380`
- Modify: `code/futures_research_backtest.py:645-720`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: canonical segmented columns `symbol`, `segment_id`, optional `feature_segment_id`, `trade_time`, `open`, `high`, `low`, `close`, `volume`.
- Produces: `build_tianji_scores(segmented) -> pd.DataFrame` with `symbol`, `segment_id`, `decision_time`, `atr`, `atr_pct`, `amihud_20`, `score`, `sector`, and the four frozen factor columns.

- [ ] **Step 1: Write failing contract and prefix-invariance tests**

Append tests that construct at least eight 15-minute symbols so cross-sectional ranks are defined:

```python
def make_tianji_market(periods=80, symbols=None):
    symbols = symbols or (
        "AG_IDX", "AU_IDX", "CU_IDX", "AL_IDX",
        "RB_IDX", "I_IDX", "MA_IDX", "M_IDX",
    )
    times = pd.date_range("2026-01-02 09:00", periods=periods, freq="15min")
    rows = []
    for number, symbol in enumerate(symbols, start=1):
        close = 100.0 + number + np.arange(periods) * (0.02 * number)
        volume = 1_000.0 + number * 10 + np.arange(periods)
        for index, time in enumerate(times):
            rows.append({
                "symbol": symbol,
                "segment_id": f"{symbol}:1",
                "feature_segment_id": f"{symbol}:features",
                "trade_time": time,
                "open": close[index] - 0.1,
                "high": close[index] + 0.5,
                "low": close[index] - 0.5,
                "close": close[index],
                "volume": volume[index],
            })
    return pd.DataFrame(rows)


def test_tianji_contract_is_non_predictive_and_15m_only():
    domain = research._research_domain(ResearchConfig(
        strategy_mode="tianji", timeframe="15m"
    ))
    assert domain["strategy_mode"] == "tianji"
    assert domain["predictive"] is False
    assert domain["selectable_models"] == []
    assert domain["thresholds"] == []
    assert domain["candidate_threshold_pairs"] == 0
    with pytest.raises(ResearchRejected, match="15m"):
        research._validate_research_config(ResearchConfig(strategy_mode="tianji"))
    with pytest.raises(ResearchRejected, match="holdout_fraction"):
        research._validate_research_config(ResearchConfig(
            strategy_mode="tianji", timeframe="15m", holdout_fraction=0.25
        ))
    with pytest.raises(ResearchRejected, match="costs_bps"):
        research._validate_research_config(ResearchConfig(
            strategy_mode="tianji", timeframe="15m", costs_bps=(5,)
        ))


def test_tianji_score_prefix_is_unchanged_by_future_bars():
    market = make_tianji_market(90)
    cutoff = market["trade_time"].sort_values().unique()[70]
    prefix = market[market["trade_time"] <= cutoff]
    expected = research.build_tianji_scores(prefix)
    actual = research.build_tianji_scores(market)
    actual = actual[actual["decision_time"] <= cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(expected.reset_index(drop=True), actual)
    assert {"label", "future_return", "probability"}.isdisjoint(actual.columns)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_contract or tianji_score_prefix'
```

Expected: FAIL because `ResearchConfig.strategy_mode` and `build_tianji_scores` do not exist.

- [ ] **Step 3: Implement the minimal frozen contract and score builder**

Add constants rather than tunable config fields:

```python
TIANJI_FEATURE_COLUMNS = (
    "signed_kaufman_efficiency_20",
    "donchian_position_20",
    "momentum_acceleration_5_20",
    "intraday_intensity_10",
)
TIANJI_REBALANCE_BARS = 16
TIANJI_SIDE_EXPOSURE = 0.40
TIANJI_TOP_K = 4
TIANJI_SECTOR_LIMIT = 2
TIANJI_INITIAL_STOP_ATR = 1.0
TIANJI_TRAIL_ATR = 2.5
TIANJI_SECTORS = {
    "AG_IDX": "PRECIOUS", "AU_IDX": "PRECIOUS",
    "CU_IDX": "BASE_METALS", "AL_IDX": "BASE_METALS",
    "ZN_IDX": "BASE_METALS", "SN_IDX": "BASE_METALS",
    "LC_IDX": "BASE_METALS", "SI_IDX": "BASE_METALS",
    "RB_IDX": "FERROUS", "HC_IDX": "FERROUS", "I_IDX": "FERROUS",
    "JM_IDX": "FERROUS", "J_IDX": "FERROUS", "FG_IDX": "FERROUS",
    "MA_IDX": "CHEMICALS", "TA_IDX": "CHEMICALS",
    "SA_IDX": "CHEMICALS", "RU_IDX": "CHEMICALS", "SC_IDX": "CHEMICALS",
    "M_IDX": "AGRI", "Y_IDX": "AGRI", "P_IDX": "AGRI",
    "C_IDX": "AGRI", "CF_IDX": "AGRI", "SR_IDX": "AGRI",
    "IF_IDX": "FINANCIAL", "IC_IDX": "FINANCIAL", "IM_IDX": "FINANCIAL",
}
```

Add `strategy_mode: str = "predictive"` to `ResearchConfig`. Validate only
`predictive` or `tianji`. For TianJi require `timeframe == "15m"`,
`holdout_fraction == 0.20`, and `costs_bps == (0, 2, 5, 10, 15, 20)` so the
locked domain cannot be changed from the CLI. Branch `_research_domain` so
TianJi reports no model/threshold domain and lists `TIANJI_FEATURE_COLUMNS`.

Implement features with only backward-looking pandas operations:

```python
def _tianji_segment_features(group):
    close = group["close"].astype(float)
    high = group["high"].astype(float)
    low = group["low"].astype(float)
    open_ = group["open"].astype(float)
    volume = group["volume"].astype(float)
    previous_close = close.shift(1).replace(0.0, np.nan)
    true_range = pd.concat([
        high - low,
        (high - previous_close).abs(),
        (low - previous_close).abs(),
    ], axis=1).max(axis=1)
    path = close.diff().abs().rolling(20).sum().replace(0.0, np.nan)
    channel_high = high.rolling(20).max()
    channel_low = low.rolling(20).min()
    channel_span = (channel_high - channel_low).replace(0.0, np.nan)
    clv = (2.0 * close - high - low) / (high - low).replace(0.0, np.nan)
    frame = pd.DataFrame(index=group.index)
    frame["signed_kaufman_efficiency_20"] = (
        np.sign(close.pct_change(20))
        * (close - close.shift(20)).abs() / path
    )
    frame["donchian_position_20"] = (
        2.0 * (close - channel_low) / channel_span - 1.0
    )
    frame["momentum_acceleration_5_20"] = (
        close.pct_change(5) - close.pct_change(20) / 4.0
    )
    frame["intraday_intensity_10"] = (
        clv * volume / volume.rolling(20).mean().replace(0.0, np.nan)
    ).rolling(10).mean()
    frame["atr"] = true_range.rolling(20).mean()
    frame["amihud_20"] = (
        close.pct_change().abs() / volume.replace(0.0, np.nan) * 1e6
    ).rolling(20).mean()
    return frame


def build_tianji_scores(segmented):
    required = {
        "symbol", "segment_id", "trade_time", "open", "high", "low",
        "close", "volume",
    }
    missing = required.difference(segmented.columns)
    if missing:
        raise ResearchRejected(
            f"missing segmented columns: {', '.join(sorted(missing))}"
        )
    if segmented.empty:
        raise ResearchRejected("no segmented bars for TianJi scores")
    ordered = segmented.sort_values(
        ["symbol", "trade_time"], kind="stable"
    ).copy()
    feature_group = (
        "feature_segment_id" if "feature_segment_id" in ordered else "segment_id"
    )
    features = pd.concat([
        _tianji_segment_features(group.sort_values("trade_time", kind="stable"))
        for _, group in ordered.groupby(["symbol", feature_group], sort=False)
    ]).sort_index().loc[ordered.index]
    frame = ordered.loc[:, ["symbol", "segment_id", "trade_time", "close"]].join(features)
    frame = frame.rename(columns={"trade_time": "decision_time"})
    finite_columns = [*TIANJI_FEATURE_COLUMNS, "atr", "amihud_20", "close"]
    frame = frame[np.isfinite(frame[finite_columns]).all(axis=1)].copy()
    frame = frame[(frame["atr"] > 0.0) & (frame["close"] > 0.0)]
    frame["atr_pct"] = frame["atr"] / frame["close"]
    illiquidity_rank = frame.groupby("decision_time")["amihud_20"].rank(
        pct=True, method="average"
    )
    frame["eligible"] = illiquidity_rank <= 0.80
    eligible = frame[frame["eligible"]].copy()
    ranks = eligible.groupby("decision_time")[list(TIANJI_FEATURE_COLUMNS)].rank(
        pct=True, method="average"
    )
    frame["score"] = np.nan
    frame.loc[eligible.index, "score"] = ranks.mean(axis=1)
    frame["sector"] = frame["symbol"].map(TIANJI_SECTORS).fillna("OTHER")
    return frame.sort_values(
        ["decision_time", "symbol"], kind="stable"
    ).reset_index(drop=True)
```

- [ ] **Step 4: Run focused and legacy feature tests and verify GREEN**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_contract or tianji_score_prefix or causal_dataset_prefix or causal_features'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: add causal tianji 15m scores"
```

---

### Task 2: Select deterministic market-neutral targets

**Files:**
- Modify: `code/futures_research_backtest.py` next to `build_tianji_scores`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: `build_tianji_scores` output.
- Produces: `build_tianji_targets(scores, holdout_start) -> tuple[pd.DataFrame, pd.DatetimeIndex]`; target rows contain `decision_time`, `symbol`, `direction`, `atr`, `atr_pct`, `score`, `sector`.

- [ ] **Step 1: Write failing selection tests**

```python
def test_tianji_targets_are_neutral_sector_capped_and_rebalance_every_16_bars():
    scores = research.build_tianji_scores(make_tianji_market(90))
    holdout_start = scores["decision_time"].sort_values().unique()[0]
    targets, rebalance_times = research.build_tianji_targets(scores, holdout_start)
    assert np.diff(rebalance_times).astype("timedelta64[m]").tolist() == [240] * (len(rebalance_times) - 1)
    for _, group in targets.groupby("decision_time"):
        assert group["direction"].eq(1).sum() <= 4
        assert group["direction"].eq(-1).sum() <= 4
        assert group["direction"].eq(1).sum() == group["direction"].eq(-1).sum()
        assert not group["symbol"].duplicated().any()
        assert group.groupby(["direction", "sector"]).size().max() <= 2


def test_tianji_target_order_is_stable_under_input_shuffle():
    scores = research.build_tianji_scores(make_tianji_market(90))
    start = scores["decision_time"].min()
    expected = research.build_tianji_targets(scores, start)
    actual = research.build_tianji_targets(
        scores.sample(frac=1, random_state=7), start
    )
    pd.testing.assert_frame_equal(expected[0], actual[0])
    assert expected[1].equals(actual[1])
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py -k 'tianji_target'
```

Expected: FAIL because `build_tianji_targets` does not exist.

- [ ] **Step 3: Implement stable sector-constrained selection**

```python
def _tianji_leg(group, direction):
    ordered = group.sort_values(
        ["score", "symbol"], ascending=[direction < 0, True], kind="stable"
    )
    rows = []
    sector_counts = {}
    for row in ordered.itertuples(index=False):
        if sector_counts.get(row.sector, 0) >= TIANJI_SECTOR_LIMIT:
            continue
        rows.append({
            "decision_time": row.decision_time,
            "symbol": row.symbol,
            "direction": direction,
            "atr": float(row.atr),
            "atr_pct": float(row.atr_pct),
            "score": float(row.score),
            "sector": row.sector,
        })
        sector_counts[row.sector] = sector_counts.get(row.sector, 0) + 1
        if len(rows) == TIANJI_TOP_K:
            break
    return rows


def build_tianji_targets(scores, holdout_start):
    if not isinstance(scores, pd.DataFrame) or scores.empty:
        raise ResearchRejected("no TianJi scores")
    times = pd.DatetimeIndex(sorted(pd.to_datetime(scores["decision_time"]).unique()))
    rebalance_times = times[::TIANJI_REBALANCE_BARS]
    rebalance_times = rebalance_times[rebalance_times >= pd.Timestamp(holdout_start)]
    rows = []
    for decision_time in rebalance_times:
        group = scores[
            scores["decision_time"].eq(decision_time)
            & scores["eligible"]
            & scores["score"].notna()
        ]
        longs = _tianji_leg(group, 1)
        long_symbols = [row["symbol"] for row in longs]
        short_pool = group[~group["symbol"].isin(long_symbols)]
        shorts = _tianji_leg(short_pool, -1)
        pair_count = min(len(longs), len(shorts))
        rows.extend(longs[:pair_count])
        rows.extend(shorts[:pair_count])
    return (
        pd.DataFrame(rows).sort_values(
            ["decision_time", "direction", "symbol"], kind="stable"
        ).reset_index(drop=True),
        rebalance_times,
    )
```

- [ ] **Step 4: Run target tests and verify GREEN**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_target or tianji_score_prefix'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: select neutral tianji futures targets"
```

---

### Task 3: Add the stateful next-open ATR ledger and 15-minute metrics

**Files:**
- Modify: `code/futures_research_backtest.py` after `simulate_standardized_ledger`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: target rows, rebalance timestamps, canonical 15-minute market bars enriched with the causal `atr` from `build_tianji_scores`, and one non-negative `cost_bps`.
- Produces: `simulate_tianji_ledger(...) -> tuple[trades, bars, daily]` and `tianji_metrics(trades, bars, daily) -> dict`.

- [ ] **Step 1: Write failing execution, stop, reconciliation, and metric tests**

Use small hand-computable fixtures and separate tests for one behavior each:

```python
def test_tianji_signal_executes_only_at_next_open():
    market = make_tianji_market(4, symbols=("AG_IDX",))
    market["atr"] = 2.0
    decision = market["trade_time"].iloc[0]
    targets = pd.DataFrame([{
        "decision_time": decision, "symbol": "AG_IDX", "direction": 1,
        "atr": 2.0, "atr_pct": 0.02, "score": 1.0, "sector": "PRECIOUS",
    }])
    trades, bars, _ = research.simulate_tianji_ledger(
        targets, pd.DatetimeIndex([decision]), market, 0
    )
    assert trades["entry_time"].iloc[0] == market["trade_time"].iloc[1]
    assert trades["entry_open"].iloc[0] == market["open"].iloc[1]
    assert bars["gross_exposure"].max() <= 0.4 + 1e-12


def test_tianji_gap_through_stop_uses_worse_open():
    market = make_tianji_market(4, symbols=("AG_IDX",))
    market["atr"] = 2.0
    market.loc[2, ["open", "high", "low", "close"]] = [95.0, 96.0, 94.0, 95.0]
    decision = market["trade_time"].iloc[0]
    targets = pd.DataFrame([{
        "decision_time": decision, "symbol": "AG_IDX", "direction": 1,
        "atr": 2.0, "atr_pct": 0.02, "score": 1.0, "sector": "PRECIOUS",
    }])
    trades, _, _ = research.simulate_tianji_ledger(
        targets, pd.DatetimeIndex([decision]), market, 5
    )
    assert trades["exit_reason"].iloc[0] == "STOP"
    assert trades["exit_open"].iloc[0] == 95.0
    assert trades["entry_cost"].iloc[0] > 0
    assert trades["exit_cost"].iloc[0] > 0


def test_tianji_trailing_stop_uses_only_prior_completed_bar():
    market = make_tianji_market(5, symbols=("AG_IDX",))
    market["atr"] = 2.0
    market.loc[2, ["high", "low", "close"]] = [110.0, 100.0, 109.0]
    market.loc[3, ["open", "high", "low", "close"]] = [109.0, 109.5, 103.0, 104.0]
    decision = market["trade_time"].iloc[0]
    targets = pd.DataFrame([{
        "decision_time": decision, "symbol": "AG_IDX", "direction": 1,
        "atr": 2.0, "atr_pct": 0.02, "score": 1.0, "sector": "PRECIOUS",
    }])
    trades, _, _ = research.simulate_tianji_ledger(
        targets, pd.DatetimeIndex([decision]), market, 0
    )
    assert trades["exit_time"].iloc[0] == market["trade_time"].iloc[3]
    assert trades["exit_open"].iloc[0] == pytest.approx(105.0)


def test_tianji_metrics_use_bar_drawdown_and_true_payoff_ratio():
    trades = pd.DataFrame({"sleeve_pnl": [0.30, -0.05, -0.15]})
    bars = pd.DataFrame({
        "equity": [1.0, 0.8, 1.1],
        "gross_exposure": [0.0, 0.8, 0.0],
        "net_exposure": [0.0, 0.0, 0.0],
        "turnover": [0.0, 0.8, 0.8],
    })
    daily = pd.DataFrame({"equity": [0.8, 1.1], "portfolio_return": [-0.2, 0.375]})
    metrics = research.tianji_metrics(trades, bars, daily)
    assert metrics["payoff_ratio"] == pytest.approx(3.0)
    assert metrics["profit_factor"] == pytest.approx(1.5)
    assert metrics["max_drawdown"] == pytest.approx(0.2)


def test_tianji_terminal_equity_reconciles_and_input_order_is_stable():
    market = make_tianji_market(4, symbols=("AG_IDX",))
    market["atr"] = 2.0
    decision = market["trade_time"].iloc[0]
    targets = pd.DataFrame([{
        "decision_time": decision, "symbol": "AG_IDX", "direction": 1,
        "atr": 2.0, "atr_pct": 0.02, "score": 1.0, "sector": "PRECIOUS",
    }])
    expected = research.simulate_tianji_ledger(
        targets, pd.DatetimeIndex([decision]), market, 5
    )
    actual = research.simulate_tianji_ledger(
        targets, pd.DatetimeIndex([decision]),
        market.sample(frac=1, random_state=11), 5,
    )
    pd.testing.assert_frame_equal(expected[0], actual[0])
    pd.testing.assert_frame_equal(expected[1], actual[1])
    assert expected[1]["equity"].iloc[-1] == pytest.approx(
        1.0 + expected[0]["sleeve_pnl"].sum()
    )
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_signal or tianji_gap or tianji_trailing or tianji_metrics'
```

Expected: FAIL because the TianJi ledger and metric functions do not exist.

- [ ] **Step 3: Implement the minimal state machine**

Use one chronological loop, one `positions` dictionary keyed by symbol, and one `pending` dictionary keyed by symbol. Do not introduce classes. The exact state is:

```python
positions[symbol] = {
    "direction": direction,
    "weight": weight,
    "entry_time": time,
    "entry_price": open_price,
    "entry_cost": weight * cost,
    "atr": atr,
    "stop": open_price - direction * atr,
    "favorable": open_price,
    "decision_time": decision_time,
}
pending[symbol] = {
    "direction": direction_or_zero,
    "weight": allocated_weight,
    "atr": atr,
    "decision_time": decision_time,
}
```

At each timestamp:

1. For each observed symbol, process a gap-through protective stop before a pending signal exit.
2. Apply pending exits, direction changes, and entries at that symbol's open.
3. Test the frozen stop against the current high/low; fill at the stop unless the open was worse.
4. Mark all observed positions at close.
5. After marking, update favorable extreme, replace the stored ATR with the
   current finite positive bar ATR, and update the stop for the next bar only.
6. At a rebalance close, retain selected same-direction positions, schedule
   exits for removed positions, and set each side's budget to `0.1` times the
   paired selection count, capped at `0.4`. Allocate the remaining equal side
   budget among new selections by normalized inverse `atr_pct`; unfilled budget
   remains cash.
7. At the final observed close, terminal-close all remaining positions, charge exit cost, and emit reconciled trade rows.

Use return-space accounting:

```python
gross_pnl = weight * direction * (exit_price / entry_price - 1.0)
entry_cost = weight * cost_bps / 10_000.0
exit_notional = weight * exit_price / entry_price
exit_cost = exit_notional * cost_bps / 10_000.0
sleeve_pnl = gross_pnl - entry_cost - exit_cost
equity = 1.0 + realized_sleeve_pnl + sum(unrealized_position_pnl)
```

Reject duplicate market timestamps, non-finite/non-positive OHLC or ATR,
invalid target directions, duplicate symbol targets, negative costs, exposure
above `0.8 + 1e-12`, and absolute net exposure above `0.4 + 1e-12`. Build
`daily` from the final bar equity per normalized date, with returns reconciled
to prior equity.

Implement `tianji_metrics` with:

```python
pnl = pd.to_numeric(trades["sleeve_pnl"], errors="coerce")
winners = pnl[pnl > 0.0]
losers = -pnl[pnl < 0.0]
payoff_ratio = (
    float(winners.mean() / losers.mean())
    if len(winners) and len(losers) else 0.0
)
profit_factor = (
    float(winners.sum() / losers.sum())
    if len(winners) and len(losers) else 0.0
)
peak = np.maximum.accumulate(np.r_[1.0, bars["equity"].to_numpy(float)])
drawdown = 1.0 - np.r_[1.0, bars["equity"].to_numpy(float)] / peak
```

Keep daily annualization identical to `strategy_metrics`; do not copy predictive metrics.

- [ ] **Step 4: Run focused ledger tests and the existing ledger suite**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_ or ledger or strategy_metrics or cost_sensitivity'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: add audited tianji execution ledger"
```

---

### Task 4: Route TianJi through holdout gates and the existing evidence bundle

**Files:**
- Modify: `code/futures_research_backtest.py:2630-2895`
- Modify: `code/futures_research_backtest.py:3023-3206`
- Modify: `code/futures_research_backtest.py:3539-3614`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Produces: `build_tianji_evaluation`, `evaluate_tianji_gates`, and a TianJi branch in `run_research`.
- Preserves: old `run_adversarial_checks`, `evaluate_acceptance_gates`, and predictive default behavior.

- [ ] **Step 1: Write failing gate, routing, and report tests**

```python
def tianji_metrics_fixture(**overrides):
    return {
        "trades": 200,
        "total_return": 0.01,
        "payoff_ratio": 1.8,
        "max_drawdown": 0.10,
        "profit_factor": 1.1,
        **overrides,
    }


@pytest.mark.parametrize(
    "name,gate_id,value",
    [
        ("payoff_ratio", "payoff_ratio_5bps", 1.7999),
        ("max_drawdown", "max_drawdown_5bps", 0.1001),
        ("trades", "minimum_trades_5bps", 199),
        ("total_return", "positive_return_5bps", 0.0),
    ],
)
def test_tianji_gate_rejects_each_failed_5bps_boundary(name, gate_id, value):
    metrics = tianji_metrics_fixture(**{name: value})
    costs = {
        0: tianji_metrics_fixture(total_return=0.03),
        2: tianji_metrics_fixture(total_return=0.02),
        5: metrics,
        10: tianji_metrics_fixture(total_return=0.005),
        15: tianji_metrics_fixture(total_return=-0.005),
        20: tianji_metrics_fixture(total_return=-0.01),
    }
    gates = research.evaluate_tianji_gates(costs, checks={
        "structural": True, "causal": True, "ledger": True,
        "prefix_invariance": True, "non_predictive": True,
    })
    assert research.tianji_status(gates) == "RESEARCH_REJECTED"
    assert next(g for g in gates if g["id"] == gate_id)["passed"] is False


def test_tianji_run_never_calls_predictive_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(
        research, "build_causal_dataset",
        lambda *_: pytest.fail("TianJi built future labels"),
    )
    monkeypatch.setattr(
        research, "fit_predict",
        lambda *_: pytest.fail("TianJi fitted a model"),
    )
    monkeypatch.setattr(
        research, "select_candidate",
        lambda *_: pytest.fail("TianJi selected a candidate"),
    )
    market = make_tianji_market(80)
    manifest = [{
        "symbol": symbol, "source_path": f"{symbol}.txt",
        "source_sha256": "a" * 64,
    } for symbol in sorted(market["symbol"].unique())]
    market.attrs["source_manifest"] = manifest
    market.attrs["source_sha256"] = {
        row["symbol"]: row["source_sha256"] for row in manifest
    }
    quality = pd.DataFrame({
        "symbol": sorted(market["symbol"].unique()),
        "status": "INCLUDED", "reason": "",
    }).set_index("symbol")
    returns = {0: 0.03, 2: 0.02, 5: 0.01, 10: 0.005, 15: 0.0, 20: -0.005}
    cost_metrics = {
        cost: tianji_metrics_fixture(total_return=value)
        for cost, value in returns.items()
    }
    trade = pd.DataFrame([{
        "symbol": "AG_IDX", "decision_time": pd.Timestamp("2026-01-02 09:00"),
        "entry_time": pd.Timestamp("2026-01-02 09:15"),
        "exit_time": pd.Timestamp("2026-01-02 09:30"),
        "direction": 1, "entry_open": 100.0, "exit_open": 101.0,
        "sleeve_pnl": 0.01,
    }])
    bars = pd.DataFrame([{
        "trade_time": pd.Timestamp("2026-01-02 09:30"), "equity": 1.01,
        "gross_exposure": 0.0, "net_exposure": 0.0, "turnover": 0.8,
    }])
    daily = pd.DataFrame([{
        "date": pd.Timestamp("2026-01-02"), "equity": 1.01,
        "portfolio_return": 0.01, "gross_exposure": 0.0, "turnover": 0.8,
    }])
    base = {
        "outer_results": [], "final_candidate": None,
        "final_inner_scores": pd.DataFrame(),
        "holdout": {
            "fold": "holdout", "model_name": "tianji_rule", "threshold": None,
            "evaluation_identity": {"id": "fixture"},
            "sample_counts": {"evaluation_rows": len(market), "symbols": 8},
            "predictive_metrics": {}, "cost_metrics": cost_metrics,
            "trades": {cost: trade.copy() for cost in returns},
            "bars": {cost: bars.copy() for cost in returns},
            "daily": {cost: daily.copy() for cost in returns},
            "symbol_metrics": pd.DataFrame(),
        },
    }
    checks = {
        "structural": True, "causal": True, "ledger": True,
        "prefix_invariance": True, "non_predictive": True,
    }
    monkeypatch.setattr(research, "load_futures_bars", lambda *_: market)
    monkeypatch.setattr(
        research, "_prepare_segmented_bars", lambda *_: (market, quality)
    )
    monkeypatch.setattr(
        research, "build_tianji_evaluation", lambda *_: (base, checks)
    )
    db_path = tmp_path / "futures.db"
    db_path.touch()

    result = research.run_research(
        db_path, tmp_path / "report",
        ResearchConfig(strategy_mode="tianji", timeframe="15m"),
    )

    assert result["status"] == "RESEARCH_ACCEPTED"
    assert result["research_domain"]["predictive"] is False
    assert result["candidates"] == []
    assert result["selection_scores"] == []
    assert set(result["artifacts"]) == EXPECTED_REPORT_FILES
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_gate or tianji_run_never'
```

Expected: FAIL because the TianJi evaluation/gate/routing functions do not exist.

- [ ] **Step 3: Implement evaluation, exact gates, and report branching**

Add exact TianJi gate IDs:

```python
TIANJI_ACCEPTANCE_GATE_IDS = (
    "integrity_checks",
    "non_predictive_contract",
    "payoff_ratio_5bps",
    "max_drawdown_5bps",
    "minimum_trades_5bps",
    "positive_return_5bps",
    "cost_monotonicity",
)
```

`build_tianji_evaluation` must:

1. count 15-minute bars per symbol, keep symbols with at least
   `config.min_symbol_rows + 30` bars for the longest rolling warm-up, require
   at least `config.min_symbols`, then build scores on only that fixed universe;
2. choose `holdout_start` from the last 20% of sorted unique score times;
3. choose the last score time before `holdout_start`, rebuild scores using only
   segmented bars through that time, and compare them exactly with the same
   prefix from the full score frame;
4. build targets with the frozen 16-bar cadence;
5. left-merge each score row's causal `atr` onto the matching
   `(symbol, trade_time)` market bar and reject missing ATR from the first
   target decision onward;
6. run the same target/market path at each configured cost;
7. assert trade identity columns are identical across costs;
8. set checks to `structural=True`, `causal=True`, `ledger=True`,
   `prefix_invariance=<exact comparison>`, and `non_predictive=True` only when
   score/target columns exclude `label`, `future_return`, and `probability` and
   the research domain contains no selectable model or threshold;
9. return a base shaped as `{"outer_results": [], "final_candidate": None,
   "final_inner_scores": empty, "holdout": ...}` with `trades`, `bars`,
   `daily`, `cost_metrics`, sample counts, and a SHA256 evaluation identity.

Implement gates directly from 5 bps metrics and strict checks:

```python
def tianji_status(gates):
    required = set(TIANJI_ACCEPTANCE_GATE_IDS)
    return (
        "RESEARCH_ACCEPTED"
        if len(gates) == len(required)
        and {gate.get("id") for gate in gates} == required
        and all(gate.get("passed") is True for gate in gates)
        else "RESEARCH_REJECTED"
    )


def evaluate_tianji_gates(cost_metrics, checks):
    primary = cost_metrics[5]
    returns = [cost_metrics[cost]["total_return"] for cost in (0, 2, 5, 10, 15, 20)]
    return [
        _gate_record("integrity_checks", all(checks.values()), checks,
                     "all checks true", None, "TianJi integrity evidence"),
        _gate_record("non_predictive_contract", checks["non_predictive"] is True,
                     checks["non_predictive"], True, None,
                     "no labels, fitting, or candidate selection"),
        _gate_record("payoff_ratio_5bps", primary["payoff_ratio"] >= 1.8,
                     primary["payoff_ratio"], ">= 1.8", "holdout",
                     "5 bp payoff-ratio gate"),
        _gate_record("max_drawdown_5bps", primary["max_drawdown"] <= 0.10,
                     primary["max_drawdown"], "<= 0.10", "holdout",
                     "5 bp 15-minute drawdown gate"),
        _gate_record("minimum_trades_5bps", primary["trades"] >= 200,
                     primary["trades"], ">= 200", "holdout",
                     "5 bp closed-trade gate"),
        _gate_record("positive_return_5bps", primary["total_return"] > 0.0,
                     primary["total_return"], "> 0", "holdout",
                     "5 bp return gate"),
        _gate_record("cost_monotonicity",
                     all(left >= right for left, right in zip(returns, returns[1:])),
                     returns, "0/2/5/10/15/20 bp non-increasing", "holdout",
                     "frozen trades decline with cost"),
    ]
```

Make `_validate_gate_bundle` accept exactly either the existing predictive ID
set or `TIANJI_ACCEPTANCE_GATE_IDS`; do not weaken field/evidence validation.
Branch `_report_tables`, `_metric_summary`, `build_result`, and
`rejected_result` on `config.strategy_mode` so TianJi reports
`TIANJI_FEATURE_COLUMNS`, empty candidates/selection scores, empty predictive
metrics, bar-level `equity_curve`, and all stress-cost rows.

In `run_research`, branch immediately after canonical segmentation:

```python
if config.strategy_mode == "tianji":
    base, checks = build_tianji_evaluation(segmented, config)
    context = build_adversarial_context(
        run_id, bars, segmented, quality,
        pd.DataFrame(), {}, base, config,
    )
    context["checks"] = checks
    context["attacks"] = []
    context["provenance"].update(provenance)
    context["research_domain"] = _research_domain(config)
    context["run_identity"] = _run_identity(
        context["research_domain"],
        base["holdout"]["evaluation_identity"],
        provenance["database_sha256"], provenance["module_sha256"],
    )
    gates = evaluate_tianji_gates(base["holdout"]["cost_metrics"], checks)
    status = tianji_status(gates)
    _validate_gate_bundle(status, gates, "official TianJi")
    result = build_result(context, gates, status)
    result["artifacts"] = write_report(result, output_dir)
    return result
```

Reuse `build_adversarial_context` exactly as shown: it only packages immutable
evidence. Pass an empty data frame and empty partitions, then replace `checks`
and set `attacks=[]`. Leave the existing predictive statements immediately
after this early-return branch unchanged.

- [ ] **Step 4: Run focused routing tests and the complete futures suite**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
```

Expected: all tests PASS with no warnings introduced by the new path.

- [ ] **Step 5: Commit Task 4**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: audit tianji holdout acceptance"
```

---

### Task 5: Run the real locked holdout once and audit the evidence

**Files:**
- Generate, do not commit: `data/reports/tianji_15m_non_predictive_20260820/`
- Verify: `data/reports/tianji_15m_non_predictive_20260820/report.json`

**Interfaces:**
- Consumes: `data/ashare_quant.db` and the committed TianJi implementation.
- Produces: immutable report bundle; acceptance or rejection is evidence, not a reason to retune.

- [ ] **Step 1: Run the full verification suite before touching the holdout**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
git diff --check
```

Expected: PASS and no whitespace errors.

- [ ] **Step 2: Run the locked holdout exactly once**

Run:

```bash
python3 code/futures_research_backtest.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/tianji_15m_non_predictive_20260820 \
  --config-json '{"strategy_mode":"tianji","timeframe":"15m","min_symbols":8,"min_symbol_rows":1000,"costs_bps":[0,2,5,10,15,20]}'
```

Expected: exit `0` only for `RESEARCH_ACCEPTED`; exit `2` for a truthful
`RESEARCH_REJECTED`. Do not change factors, weights, stops, exposure, holdout,
or gates after seeing this output.

- [ ] **Step 3: Reconcile the generated evidence**

Run:

```bash
python3 -m json.tool data/reports/tianji_15m_non_predictive_20260820/report.json >/dev/null
jq '{status,research_domain,config,metrics,gates,row_counts}' \
  data/reports/tianji_15m_non_predictive_20260820/report.json
rg -n 'TianJi|predictive|payoff|max_drawdown|RESEARCH_(ACCEPTED|REJECTED)' \
  data/reports/tianji_15m_non_predictive_20260820/report.md \
  data/reports/tianji_15m_non_predictive_20260820/report.html
```

Expected: valid JSON; `predictive=false`; 5 bps payoff, bar drawdown, trade
count, return, and exact gate reasons visible; CSV row counts reconcile.

- [ ] **Step 4: Run final regression verification**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
git status --short
```

Expected: tests PASS. Status may contain the user's pre-existing untracked
research files and the generated report directory; implementation files must be
committed and report output must remain uncommitted.

- [ ] **Step 5: Report the evidence without tuning**

If accepted, quote the four 5 bps gate values and stress returns. If rejected,
quote every failed gate and stop. In either case, explicitly state that the
weighted-index result is research-only and live trading remains disabled.

---

## Plan Self-Review Checklist

- Every approved design requirement maps to a task above.
- No new dependency, module, strategy framework, or live-trading path is added.
- Existing predictive behavior remains the default and retains its exact gate set.
- TianJi uses no future label, fit, prediction, candidate, threshold, or holdout tuning.
- Bar-level drawdown and payoff ratio are distinct from daily drawdown and profit factor.
- The locked holdout has one immutable run command and no post-result optimization step.
