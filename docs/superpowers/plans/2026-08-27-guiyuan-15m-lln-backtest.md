# 归元·极值 15m 双轨大样本回测实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增可复跑的归元·极值 15m 双轨审计，让 25 个品种在合成压力轨各产生至少 1,001 笔平仓，同时如实报告真实历史轨结果。

**Architecture:** 新入口直接复用现有策略信号函数、合约规格和合成市场生成器；独立实现一个最小的因果逐 Bar 撮合器，避免修改已有且账本口径有误的研究脚本。真实与合成结果使用同一撮合器，但通过 `track` 字段、分表汇总和独立门禁保持物理与统计隔离。

**Tech Stack:** Python 3、pandas、NumPy、SQLite、pytest；不新增依赖。

## Global Constraints

- 15m 原策略参数不变；信号在 Bar `t` 收盘确认，Bar `t+1` 开盘成交。
- 开平双边计合约乘数、手续费和 1 Tick 滑点。
- 合成压力轨每品种平仓交易数必须严格大于 1,000。
- 合成结果不得进入真实历史收益汇总。
- 不修改现有用户未提交的策略、审计摘要或回测脚本。

---

### Task 1: 因果撮合器与账本

**Files:**
- Create: `code/run_guiyuan_15m_lln_audit.py`
- Create: `tests/test_guiyuan_15m_lln_audit.py`

**Interfaces:**
- Consumes: `pandas.DataFrame` OHLCV/OI、`pandas.Series` 信号、合约规格 `dict`。
- Produces: `simulate_guiyuan(df, signals, spec, ...) -> dict`，包含 `trades`、`equity`、`metrics`、`ledger_reconciled`。

- [ ] **Step 1: 写失败测试**

```python
def test_position_size_and_round_trip_costs_are_in_ledger():
    df, signals = deterministic_long_fixture()
    result = simulate_guiyuan(df, signals, SPEC, initial_capital=100_000)
    trade = result["trades"].iloc[0]
    expected_gross = (trade.exit_price - trade.entry_price) * SPEC["multiplier"] * trade.lots
    assert trade.gross_pnl == pytest.approx(expected_gross)
    assert trade.net_pnl == pytest.approx(expected_gross - trade.entry_fee - trade.exit_fee)
    assert result["ledger_reconciled"]

def test_signal_is_filled_at_next_open():
    df, signals = deterministic_long_fixture()
    trade = simulate_guiyuan(df, signals, SPEC)["trades"].iloc[0]
    assert trade.entry_time == df.index[2]
    assert trade.entry_price == pytest.approx(df.open.iloc[2] + SPEC["tick"])
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest -q tests/test_guiyuan_15m_lln_audit.py`

Expected: FAIL，因为 `run_guiyuan_15m_lln_audit` 尚不存在。

- [ ] **Step 3: 写最小实现**

```python
def simulate_guiyuan(df, signals, spec, initial_capital=1_000_000.0,
                     stop_atr_mult=2.5, breakeven_atr_mult=2.0,
                     trail_atr_mult=5.0, cost_multiplier=1.0):
    """逐 Bar 因果撮合；所有成交、手数、双边成本写入逐笔账本。"""
```

实现只覆盖单向持仓、下一柱开仓、ATR 止损/保本/追踪、期末强平、逐笔与现金对账；不添加撮合框架或抽象类。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `pytest -q tests/test_guiyuan_15m_lln_audit.py`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add code/run_guiyuan_15m_lln_audit.py tests/test_guiyuan_15m_lln_audit.py
git commit -m "feat: add causal guiyuan 15m ledger"
```

### Task 2: 双轨数据、样本门禁与统计

**Files:**
- Modify: `code/run_guiyuan_15m_lln_audit.py`
- Modify: `tests/test_guiyuan_15m_lln_audit.py`

**Interfaces:**
- Consumes: `ACTIVE_CONTRACT_SPECS`、`SyntheticMarketRegimeGenerator`、`futures_min_bars`。
- Produces: `load_real_bars(symbol) -> DataFrame`、`generate_until_lln(symbol, spec, target=1001) -> DataFrame`、`summarize_track(...) -> DataFrame`。

- [ ] **Step 1: 写失败测试**

```python
def test_lln_gate_requires_strictly_more_than_1000_trades():
    assert not lln_gate(1000)
    assert lln_gate(1001)

def test_track_summaries_never_mix():
    rows = pd.DataFrame({"track": ["real", "synthetic"], "net_pnl": [-10, 999]})
    assert summarize_portfolio(rows, "real")["net_pnl"] == -10
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest -q tests/test_guiyuan_15m_lln_audit.py`

Expected: FAIL，因为门禁与双轨汇总函数尚不存在。

- [ ] **Step 3: 写最小实现**

```python
def lln_gate(trades: int) -> bool:
    return trades > 1000

def summarize_portfolio(rows: pd.DataFrame, track: str) -> dict:
    selected = rows.loc[rows["track"].eq(track)]
    return {"track": track, "net_pnl": float(selected["net_pnl"].sum())}
```

补充真实数据质量检查、Wilson 95% 区间、Profit Factor、期望、最大回撤、Sharpe/Sortino、70/30 合成留出、16 组参数扰动和 3 倍成本压力测试。合成批次使用稳定种子并只写 `data/synthetic_sandbox/`。

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `pytest -q tests/test_guiyuan_15m_lln_audit.py`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add code/run_guiyuan_15m_lln_audit.py tests/test_guiyuan_15m_lln_audit.py
git commit -m "feat: add guiyuan dual-track lln audit"
```

### Task 3: 报告产物与全量执行

**Files:**
- Modify: `code/run_guiyuan_15m_lln_audit.py`
- Create: `data/reports/guiyuan_15m_lln_20260827/report.md`
- Create: `data/reports/guiyuan_15m_lln_20260827/report.json`
- Create: `data/reports/guiyuan_15m_lln_20260827/symbol_metrics.csv`
- Create: `data/reports/guiyuan_15m_lln_20260827/trades.csv`
- Create: `data/reports/guiyuan_15m_lln_20260827/data_quality.csv`

**Interfaces:**
- Consumes: Task 1/2 的逐品种结果。
- Produces: `run_audit(output_dir) -> dict` 及五个报告文件。

- [ ] **Step 1: 写失败测试**

```python
def test_report_labels_synthetic_results(tmp_path):
    write_report(tmp_path, fixture_audit_result())
    report = (tmp_path / "report.md").read_text()
    assert "合成压力轨，不是历史绩效" in report
    assert "INSUFFICIENT_REAL_SAMPLE" in report
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest -q tests/test_guiyuan_15m_lln_audit.py`

Expected: FAIL，因为报告函数尚不存在。

- [ ] **Step 3: 写最小实现并执行**

```python
def write_report(output_dir: Path, result: dict) -> None:
    """写 Markdown、JSON 和三个 CSV；标题与字段明确区分 real/synthetic。"""
```

Run: `python3 code/run_guiyuan_15m_lln_audit.py --output data/reports/guiyuan_15m_lln_20260827`

Expected: 25 个品种合成交易数均 `>1000`，真实轨单列，脚本退出码为 0。

- [ ] **Step 4: 完整验证**

Run: `pytest -q tests/test_guiyuan_15m_lln_audit.py tests/test_three_new_strategies.py`

Run: `python3 -m py_compile code/run_guiyuan_15m_lln_audit.py`

Run: `python3 -c "import pandas as pd; p='data/reports/guiyuan_15m_lln_20260827/symbol_metrics.csv'; d=pd.read_csv(p); s=d[d.track.eq('synthetic')]; assert len(s)==25 and (s.trade_count>1000).all(); assert set(d.track)=={'real','synthetic'}"`

Expected: 所有命令退出码为 0。

- [ ] **Step 5: 提交**

```bash
git add code/run_guiyuan_15m_lln_audit.py tests/test_guiyuan_15m_lln_audit.py data/reports/guiyuan_15m_lln_20260827
git commit -m "report: add guiyuan 15m lln backtest"
```

