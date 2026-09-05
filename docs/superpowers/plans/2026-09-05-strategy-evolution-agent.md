# 策略自动进化 Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个无需 API Key、只允许 Codex 修改候选策略、由冻结 evaluator 自动裁决并可安全晋级 Shadow 虚拟盘的 RC-LSR 自动研究闭环。

**Architecture:** 先把当前 RC-LSR 严格撮合器参数化并冻结，再由单个 Controller 为每个 Trial 创建仅含候选策略的隔离 Git 工作区，通过 `codex exec` 生成结构化提案和补丁。静态检查、因果测试、Purged Walk-Forward、成本压力、密封盲测和 Shadow 晋级全部由确定性代码执行，AI 无权修改或覆盖裁决。

**Tech Stack:** Python 3.11+、stdlib（`ast`、`hashlib`、`json`、`sqlite3`、`subprocess`、`tempfile`）、NumPy、pandas、pytest、Codex CLI、现有 SQLite 行情库。

## Global Constraints

- AI 只能修改每个 Trial 工作区中的 `strategy.py`；任何其他文件变化立即拒绝。
- evaluator、行情数据、合约规格、费用、滑点、数据切分和晋级门禁以 SHA-256 冻结。
- 策略必须保持均值回归：极端偏离后反向入场，并要求衰竭/吸收/回归确认。
- 禁止负 shift、center rolling、`bfill`/`backfill`、未来标签、日期分支和品种白名单。
- 最早 70% 为开发池；最新 30% 为密封盲测；盲测只运行一次且结果不回传 Codex。
- 每个 Campaign 最多回测 24 个候选，连续 6 个有效候选无改进即停止。
- 每轮最多新增 1 个因子族、2 个自由参数、40 行逻辑；禁止新增依赖。
- 通过盲测后只能进入 Shadow；任何路径不得接入真实资金账户。
- 保留用户当前工作区改动；实施时使用独立 worktree，禁止清理或覆盖现有脏工作树。

---

## 文件结构

**创建：**

- `config/rc_lsr_constitution.json`：策略身份、修改预算和全部硬门禁。
- `schemas/strategy_proposal.schema.json`：Codex 结构化提案协议。
- `code/strategy_evolution_gate.py`：策略静态检查、manifest、时间切分和确定性晋级门禁。
- `code/strategy_evolution_agent.py`：Trial 账本、Codex 调用、Campaign Controller、密封审计和 Shadow 周期。
- `tests/test_rc_lsr_evaluator.py`：冻结 evaluator 契约和成交语义测试。
- `tests/test_strategy_evolution_gate.py`：隔离、因果、切分和门禁测试。
- `tests/test_strategy_evolution_agent.py`：账本、Codex adapter、循环、盲测和 Shadow 生命周期测试。

**修改：**

- `strategies/rc_lsr_strategy.py`：增加通用策略元数据、标准因子列和受限执行政策。
- `code/run_rc_lsr_deep_audit.py`：从策略政策读取参数，保持成交语义集中于 evaluator。
- `.gitignore`：忽略 `.superpowers/`、`data/strategy_evolution.db` 和 `data/evolution_runs/`。

---

### Task 1: 固定 RC-LSR 策略契约和 evaluator 语义

**Files:**
- Modify: `strategies/rc_lsr_strategy.py:26-290`
- Modify: `code/run_rc_lsr_deep_audit.py:129-410`
- Create: `tests/test_rc_lsr_evaluator.py`
- Test: `tests/test_rc_lsr_strategy.py`

**Interfaces:**
- Consumes: 现有 `calculate_factors(df)`、`calculate_signal(df, cooldown_bars=8)`、`simulate_single_symbol(df, signals, factors, symbol, friction_mult=1.0, risk_pct=0.015, initial_capital=1_000_000.0)`。
- Produces: `STRATEGY_FAMILY: str`、`ENTRY_DIRECTION: str`、`EXECUTION_POLICY: dict[str, float | int]`、`validate_execution_policy(policy) -> dict`、`simulate_single_symbol(df, signals, factors, symbol, friction_mult=1.0, risk_pct=0.015, initial_capital=1_000_000.0, execution_policy=None) -> dict`。

- [ ] **Step 1: 写入失败测试，锁定策略契约**

```python
import numpy as np
import pandas as pd

from strategies import rc_lsr_strategy


def make_bars(n=80):
    index = pd.date_range("2026-01-01 09:00", periods=n, freq="30min")
    close = 100.0 + np.sin(np.arange(n) / 4.0)
    return pd.DataFrame({
        "open": close - 0.1,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.full(n, 1_000.0),
        "open_interest": np.full(n, 10_000.0),
    }, index=index)


def test_rc_lsr_declares_mean_reversion_contract():
    assert rc_lsr_strategy.STRATEGY_FAMILY == "mean_reversion"
    assert rc_lsr_strategy.ENTRY_DIRECTION == "contrarian"
    assert rc_lsr_strategy.EXECUTION_POLICY == {
        "initial_stop_atr": 0.85,
        "breakeven_trigger_atr": 0.75,
        "breakeven_lock_atr": 0.10,
        "chandelier_trigger_atr": 1.40,
        "chandelier_distance_atr": 1.20,
        "structural_break_atr": 3.50,
        "max_hold_bars": 24,
    }


def test_factor_contract_exposes_fair_value_and_deviation():
    frame = make_bars()
    factors = rc_lsr_strategy.calculate_factors(frame)
    np.testing.assert_allclose(factors["fair_value"], factors["ema_base"])
    np.testing.assert_allclose(
        factors["normalized_deviation"], factors["close_deviation"]
    )
```

- [ ] **Step 2: 运行契约测试并确认失败**

Run: `python3 -m pytest -q tests/test_rc_lsr_evaluator.py::test_rc_lsr_declares_mean_reversion_contract tests/test_rc_lsr_evaluator.py::test_factor_contract_exposes_fair_value_and_deviation`

Expected: FAIL，提示缺少 `STRATEGY_FAMILY` 或 `fair_value`。

- [ ] **Step 3: 在策略文件增加最小契约**

```python
STRATEGY_FAMILY = "mean_reversion"
ENTRY_DIRECTION = "contrarian"
EXECUTION_POLICY = {
    "initial_stop_atr": 0.85,
    "breakeven_trigger_atr": 0.75,
    "breakeven_lock_atr": 0.10,
    "chandelier_trigger_atr": 1.40,
    "chandelier_distance_atr": 1.20,
    "structural_break_atr": 3.50,
    "max_hold_bars": 24,
}
```

在 `calculate_factors()` 返回 DataFrame 中加入：

```python
"fair_value": ema_base,
"normalized_deviation": close_deviation,
```

- [ ] **Step 4: 写入失败测试，锁定政策白名单和类型**

```python
import pytest
from code.run_rc_lsr_deep_audit import validate_execution_policy


def test_execution_policy_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown execution policy"):
        validate_execution_policy({"future_fill_price": 1.0})


def test_execution_policy_rejects_invalid_ordering():
    with pytest.raises(ValueError, match="chandelier trigger"):
        validate_execution_policy({
            "initial_stop_atr": 0.85,
            "breakeven_trigger_atr": 0.75,
            "breakeven_lock_atr": 0.10,
            "chandelier_trigger_atr": 0.50,
            "chandelier_distance_atr": 1.20,
            "structural_break_atr": 3.50,
            "max_hold_bars": 24,
        })
```

- [ ] **Step 5: 运行政策测试并确认失败**

Run: `python3 -m pytest -q tests/test_rc_lsr_evaluator.py::test_execution_policy_rejects_unknown_key tests/test_rc_lsr_evaluator.py::test_execution_policy_rejects_invalid_ordering`

Expected: FAIL，提示无法导入 `validate_execution_policy`。

- [ ] **Step 6: 实现政策校验并参数化 evaluator**

在 `code/run_rc_lsr_deep_audit.py` 增加：

```python
POLICY_KEYS = {
    "initial_stop_atr",
    "breakeven_trigger_atr",
    "breakeven_lock_atr",
    "chandelier_trigger_atr",
    "chandelier_distance_atr",
    "structural_break_atr",
    "max_hold_bars",
}


def validate_execution_policy(policy):
    merged = dict(rc_lsr_mod.EXECUTION_POLICY)
    unknown = set(policy or {}) - POLICY_KEYS
    if unknown:
        raise ValueError(f"unknown execution policy: {sorted(unknown)}")
    merged.update(policy or {})
    numeric = POLICY_KEYS - {"max_hold_bars"}
    if any(float(merged[key]) <= 0 for key in numeric):
        raise ValueError("execution policy values must be positive")
    if int(merged["max_hold_bars"]) < 1:
        raise ValueError("max_hold_bars must be positive")
    if merged["chandelier_trigger_atr"] <= merged["breakeven_trigger_atr"]:
        raise ValueError("chandelier trigger must exceed breakeven trigger")
    return merged
```

把函数签名改为：

```python
def simulate_single_symbol(
    df,
    signals,
    factors,
    symbol,
    friction_mult=1.0,
    risk_pct=0.015,
    initial_capital=1_000_000.0,
    execution_policy=None,
):
    policy = validate_execution_policy(execution_policy)
```

将字面量按下列映射替换，不得移动成交判断顺序：

```python
initial_stop_atr = float(policy["initial_stop_atr"])
breakeven_trigger_atr = float(policy["breakeven_trigger_atr"])
breakeven_lock_atr = float(policy["breakeven_lock_atr"])
chandelier_trigger_atr = float(policy["chandelier_trigger_atr"])
chandelier_distance_atr = float(policy["chandelier_distance_atr"])
structural_break_atr = float(policy["structural_break_atr"])
max_hold_bars = int(policy["max_hold_bars"])
```

入场止损使用 `initial_stop_atr`；保本判断和锁定价使用 `breakeven_trigger_atr`、`breakeven_lock_atr`；吊灯判断和距离使用 `chandelier_trigger_atr`、`chandelier_distance_atr`；结构破裂和时间退出分别使用 `structural_break_atr`、`max_hold_bars`。

- [ ] **Step 7: 增加成交语义回归测试**

测试直接构造 signals/factors，并加入以下完整 helper：

```python
from code import run_rc_lsr_deep_audit as evaluator


def run_execution_fixture(kind):
    bars = make_bars()
    bars.loc[:, ["open", "high", "low", "close"]] = [100.0, 101.0, 99.0, 100.0]
    signals = pd.Series(0, index=bars.index, dtype=int)
    factors = pd.DataFrame({
        "atr": np.full(len(bars), 10.0),
        "close_deviation": np.zeros(len(bars)),
    }, index=bars.index)
    if kind == "terminal":
        signals.iloc[-2] = 1
    else:
        signals.iloc[48] = 1
    if kind == "structural":
        factors.iloc[49, factors.columns.get_loc("close_deviation")] = -4.0
        bars.iloc[50, bars.columns.get_loc("open")] = 97.0
    if kind == "gap":
        bars.iloc[50, bars.columns.get_loc("open")] = 90.0
        bars.iloc[50, bars.columns.get_loc("low")] = 89.0
    evaluator.ACTIVE_CONTRACT_SPECS["TEST"] = {
        "name": "test", "sector": "test", "multiplier": 1.0,
        "tick": 0.0, "fee_rate": 0.0, "margin_rate": 0.1,
    }
    try:
        return evaluator.simulate_single_symbol(
            bars, signals, factors, "TEST", risk_pct=0.0001
        ), bars
    finally:
        evaluator.ACTIVE_CONTRACT_SPECS.pop("TEST", None)


def test_close_confirmed_exit_fills_next_open():
    result, bars = run_execution_fixture("structural")
    trade = result["trades"][0]
    assert trade["reason"] == "STRUCTURAL_RUPTURE"
    assert trade["exit_time"] == str(bars.index[50].to_datetime64())
    assert trade["exit_price"] == 97.0


def test_gap_through_stop_fills_at_worse_open():
    result, _ = run_execution_fixture("gap")
    trade = result["trades"][0]
    assert trade["reason"] == "GAP_STOP_LOSS"
    assert trade["exit_price"] == 90.0


def test_terminal_position_is_settled_and_reconciled():
    result, _ = run_execution_fixture("terminal")
    assert result["total_trades"] == 1
    assert result["ledger_reconciled"] is True
    assert result["equity_curve"][-1] == result["final_equity"]
```

- [ ] **Step 8: 运行 RC-LSR 全部契约和因果测试**

Run: `python3 -m pytest -q tests/test_rc_lsr_strategy.py tests/test_rc_lsr_evaluator.py`

Expected: PASS，且现有 4 个策略测试不回归。

- [ ] **Step 9: 提交 Task 1**

```bash
git add strategies/rc_lsr_strategy.py code/run_rc_lsr_deep_audit.py tests/test_rc_lsr_evaluator.py
git commit -m "refactor: freeze RC-LSR strategy contract"
```

---

### Task 2: 增加策略宪法、提案 Schema 和静态安全门禁

**Files:**
- Create: `config/rc_lsr_constitution.json`
- Create: `schemas/strategy_proposal.schema.json`
- Create: `code/strategy_evolution_gate.py`
- Create: `tests/test_strategy_evolution_gate.py`

**Interfaces:**
- Consumes: Task 1 的策略元数据和执行政策。
- Produces: `load_constitution(path) -> dict`、`validate_proposal(proposal, schema) -> list[str]`、`scan_strategy_source(source, constitution) -> list[str]`、`validate_strategy_module(module, bars) -> list[str]`。

- [ ] **Step 1: 创建失败测试，覆盖未来函数与策略漂移**

```python
import json
from pathlib import Path

from code.strategy_evolution_gate import scan_strategy_source


def constitution():
    path = Path("config/rc_lsr_constitution.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "family": "mean_reversion",
        "entry_direction": "contrarian",
        "forbidden_methods": ["bfill", "backfill"],
        "forbidden_string_patterns": [
            "_IDX", "20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
        ],
        "max_changed_logical_lines": 40,
        "max_new_factor_families": 1,
        "max_new_parameters": 2,
    }


def test_static_guard_rejects_future_and_specialization():
    source = '''
STRATEGY_FAMILY = "momentum"
SYMBOL = "AU_IDX"
def calculate_signal(df):
    return df.close.shift(-1).bfill()
'''
    reasons = scan_strategy_source(source, constitution())
    assert "STRATEGY_FAMILY_MISMATCH" in reasons
    assert "NEGATIVE_SHIFT" in reasons
    assert "BACKWARD_FILL" in reasons
    assert "SYMBOL_SPECIALIZATION" in reasons


def test_static_guard_accepts_minimal_causal_strategy():
    source = '''
STRATEGY_FAMILY = "mean_reversion"
ENTRY_DIRECTION = "contrarian"
def calculate_signal(df):
    return (df.close < df.close.rolling(20).mean()).astype(int)
'''
    assert scan_strategy_source(source, constitution()) == []
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_gate.py::test_static_guard_rejects_future_and_specialization`

Expected: FAIL，提示模块不存在。

- [ ] **Step 3: 创建宪法 JSON**

`config/rc_lsr_constitution.json` 必须完整包含：

```json
{
  "strategy_id": "rc_lsr_strategy",
  "family": "mean_reversion",
  "entry_direction": "contrarian",
  "allowed_changed_files": ["strategy.py"],
  "forbidden_methods": ["bfill", "backfill"],
  "forbidden_string_patterns": ["_IDX", "20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]"],
  "max_changed_logical_lines": 40,
  "max_new_factor_families": 1,
  "max_new_parameters": 2,
  "max_complexity_ratio": 1.20,
  "trial_budget": 24,
  "stale_limit": 6,
  "development_ratio": 0.70,
  "folds": 5,
  "embargo_bars": 24,
  "development_gates": {
    "min_trades": 500,
    "min_profit_factor": 1.20,
    "max_drawdown": 0.10,
    "max_fold_drawdown": 0.12,
    "min_positive_folds": 4,
    "min_profitable_symbol_rate": 0.60,
    "min_neighbor_profitable_rate": 0.70,
    "min_two_x_net_pnl": 0.0,
    "min_three_x_profit_factor": 0.90
  },
  "sealed_gates": {
    "min_profit_factor": 1.10,
    "max_drawdown": 0.10,
    "min_profitable_symbol_rate": 0.50
  },
  "shadow_gates": {
    "min_calendar_days": 30,
    "max_calendar_days": 180,
    "min_closed_trades": 100,
    "min_profit_factor": 1.10,
    "max_drawdown": 0.10
  }
}
```

- [ ] **Step 4: 创建完整 proposal JSON Schema**

Schema 根对象设置 `additionalProperties: false`，并要求以下字段：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": [
    "trial_id", "failure_mechanism", "hypothesis", "change_type",
    "economic_rationale", "expected_metric_effect",
    "mean_reversion_invariants", "falsification_test",
    "rollback_condition", "new_factors", "new_parameters",
    "removed_components", "changed_files", "complexity_delta"
  ],
  "properties": {
    "trial_id": {"type": "string", "minLength": 1},
    "failure_mechanism": {"type": "string", "minLength": 20},
    "hypothesis": {"type": "string", "minLength": 20},
    "change_type": {"enum": ["REMOVE", "ADD", "CHANGE", "TUNE"]},
    "economic_rationale": {"type": "string", "minLength": 20},
    "expected_metric_effect": {"type": "string", "minLength": 10},
    "mean_reversion_invariants": {
      "type": "array", "minItems": 3, "items": {"type": "string"}
    },
    "falsification_test": {"type": "string", "minLength": 10},
    "rollback_condition": {"type": "string", "minLength": 10},
    "new_factors": {"type": "array", "maxItems": 1, "items": {"type": "string"}},
    "new_parameters": {
      "type": "object", "maxProperties": 2,
      "additionalProperties": {"type": ["number", "integer", "boolean"]}
    },
    "removed_components": {"type": "array", "items": {"type": "string"}},
    "changed_files": {"const": ["strategy.py"]},
    "complexity_delta": {"type": "integer", "maximum": 40}
  },
  "additionalProperties": false
}
```

- [ ] **Step 5: 实现 AST 扫描和动态均值回归检查**

```python
def validate_strategy_module(module, bars):
    reasons = []
    if module.STRATEGY_FAMILY != "mean_reversion":
        reasons.append("STRATEGY_FAMILY_MISMATCH")
    if module.ENTRY_DIRECTION != "contrarian":
        reasons.append("ENTRY_DIRECTION_MISMATCH")
    factors = module.calculate_factors(bars.copy())
    signals = module.calculate_signal(bars.copy()).astype(int)
    required = {"fair_value", "normalized_deviation"}
    if not required.issubset(factors.columns):
        reasons.append("FACTOR_CONTRACT_MISSING")
        return reasons
    entries = signals.ne(0)
    if entries.any():
        products = signals.loc[entries] * factors.loc[entries, "normalized_deviation"]
        if not products.lt(0).all():
            reasons.append("NON_CONTRARIAN_ENTRY")
    return reasons
```

`scan_strategy_source()` 使用 `ast.parse()`；检查负数 `shift()` 参数、`rolling(center=True)`、禁止方法调用、日期字符串、`*_IDX` 字符串以及 `STRATEGY_FAMILY`/`ENTRY_DIRECTION` 常量。

- [ ] **Step 6: 增加 proposal schema 测试并实现校验**

不添加 `jsonschema` 依赖。用 stdlib 逐字段检查必需字段、动作枚举、文件列表、因子/参数/复杂度上限。测试一个合法 proposal 返回空列表，一个含两个 changed_files 的 proposal 返回 `UNAUTHORIZED_CHANGED_FILES`。

- [ ] **Step 7: 运行门禁测试**

Run: `python3 -m pytest -q tests/test_strategy_evolution_gate.py`

Expected: PASS。

- [ ] **Step 8: 提交 Task 2**

```bash
git add config/rc_lsr_constitution.json schemas/strategy_proposal.schema.json code/strategy_evolution_gate.py tests/test_strategy_evolution_gate.py
git commit -m "feat: add strategy constitution and static gates"
```

---

### Task 3: 冻结 evaluator/data manifest 与 Purged Walk-Forward 切分

**Files:**
- Modify: `code/strategy_evolution_gate.py`
- Modify: `tests/test_strategy_evolution_gate.py`

**Interfaces:**
- Consumes: Task 2 宪法配置。
- Produces: `sha256_path(path) -> str`、`build_campaign_manifest(campaign_id, strategy_id, evaluator_path, immutable_paths, split_manifest, gate_config) -> dict`、`verify_campaign_manifest(manifest) -> list[str]`、`build_time_splits(index, development_ratio, folds, embargo_bars) -> dict`。

- [ ] **Step 1: 写入失败测试，锁定时间边界**

```python
def test_time_split_seals_latest_thirty_percent():
    index = pd.date_range("2020-01-01", periods=1000, freq="30min")
    split = build_time_splits(index, 0.70, folds=5, embargo_bars=24)
    assert split["development_end"] == str(index[699])
    assert split["holdout_start"] == str(index[700])
    assert len(split["folds"]) == 5
    for fold in split["folds"]:
        train_end = pd.Timestamp(fold["train_end"])
        valid_start = pd.Timestamp(fold["validation_start"])
        assert index.get_loc(valid_start) - index.get_loc(train_end) >= 24


def test_manifest_detects_evaluator_mutation(tmp_path):
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text("VALUE = 1\n")
    manifest = build_campaign_manifest(
        "campaign-1", "rc_lsr_strategy", evaluator, [evaluator], {}, {}
    )
    evaluator.write_text("VALUE = 2\n")
    assert "IMMUTABLE_HASH_MISMATCH" in verify_campaign_manifest(manifest)
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_gate.py -k 'time_split or manifest'`

Expected: FAIL，提示函数未定义。

- [ ] **Step 3: 实现确定性切分**

```python
def build_time_splits(index, development_ratio=0.70, folds=5, embargo_bars=24):
    ordered = pd.DatetimeIndex(index).sort_values().unique()
    if len(ordered) < (folds + 2) * embargo_bars:
        raise ValueError("not enough bars for purged walk-forward")
    development_size = int(len(ordered) * development_ratio)
    holdout_start = development_size
    validation_size = max(embargo_bars, development_size // (folds + 2))
    first_validation = development_size - folds * validation_size
    fold_rows = []
    for number in range(folds):
        validation_start = first_validation + number * validation_size
        validation_end = min(development_size, validation_start + validation_size)
        train_end = validation_start - embargo_bars
        fold_rows.append({
            "fold": number + 1,
            "train_start": str(ordered[0]),
            "train_end": str(ordered[train_end - 1]),
            "validation_start": str(ordered[validation_start]),
            "validation_end": str(ordered[validation_end - 1]),
        })
    return {
        "development_start": str(ordered[0]),
        "development_end": str(ordered[development_size - 1]),
        "holdout_start": str(ordered[holdout_start]),
        "holdout_end": str(ordered[-1]),
        "folds": fold_rows,
    }
```

- [ ] **Step 4: 实现 manifest 哈希与原子保存**

`sha256_path()` 对文件流式读取，对目录按相对路径排序后组合文件哈希。Manifest 至少保存 evaluator、行情数据库、合约规格、constitution、proposal schema 和 split JSON 的哈希。使用 `tempfile.NamedTemporaryFile(dir=target.parent)` 后 `Path.replace()` 原子写入。

- [ ] **Step 5: 运行测试并检查重复构建稳定**

Run: `python3 -m pytest -q tests/test_strategy_evolution_gate.py`

Expected: PASS；同一输入连续两次 manifest hash 完全相同。

- [ ] **Step 6: 提交 Task 3**

```bash
git add code/strategy_evolution_gate.py tests/test_strategy_evolution_gate.py
git commit -m "feat: freeze evaluator manifests and time splits"
```

---

### Task 4: 实现开发区指标、诊断包和硬门禁

**Files:**
- Modify: `code/run_rc_lsr_deep_audit.py`
- Modify: `code/strategy_evolution_gate.py`
- Modify: `tests/test_rc_lsr_evaluator.py`
- Modify: `tests/test_strategy_evolution_gate.py`

**Interfaces:**
- Consumes: Task 1 evaluator、Task 3 split manifest。
- Produces: `evaluate_candidate(strategy_path, data, splits, specs) -> dict`、`build_research_packet(report, history) -> dict`、`development_gate(report, constitution) -> tuple[bool, list[str]]`。

- [ ] **Step 1: 写入失败测试，证明硬门禁不可被总收益绕过**

```python
def test_development_gate_requires_every_hard_condition():
    report = passing_report()
    report["profitable_symbol_rate"] = 0.59
    passed, reasons = development_gate(report, constitution())
    assert passed is False
    assert reasons == ["CROSS_MARKET_PASS_RATE"]


def test_positive_return_cannot_hide_bad_cost_stress():
    report = passing_report()
    report["two_x"]["net_pnl"] = -1.0
    passed, reasons = development_gate(report, constitution())
    assert passed is False
    assert "TWO_X_FRICTION_FAILED" in reasons
```

- [ ] **Step 2: 运行门禁测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_gate.py -k development_gate`

Expected: FAIL，提示 `development_gate` 未定义。

- [ ] **Step 3: 实现 Trial 报告结构和硬门禁**

`evaluate_candidate()` 必须返回以下稳定字段：

```python
{
    "strategy_hash": "sha256",
    "folds": [],
    "symbols": {},
    "sectors": {},
    "sides": {},
    "regimes": {},
    "exit_reasons": {},
    "signal_funnel": {},
    "mfe": {},
    "mae": {},
    "holding_bars": {},
    "standard": {},
    "two_x": {},
    "three_x": {},
    "delay_one_bar": {},
    "neighbors": [],
    "ablations": [],
    "profitable_symbol_rate": 0.0,
    "positive_fold_count": 0,
    "complexity_ratio": 1.0,
    "ledger_reconciled": True,
}
```

`development_gate()` 按宪法逐项追加明确 reason，不计算可抵消失败的总分。只有 `reasons == []` 返回通过。

- [ ] **Step 4: 增加 evaluator 全交易输出**

确保 `simulate_single_symbol()` 返回完整 `trades`、`equity_curve`、`final_equity`、`ledger_reconciled`，而不是只有 `trades_sample`。每笔交易增加 `entry_time`、`exit_time`、`entry_atr`、`mfe_atr`、`mae_atr`、`fees`、`slippage_cost` 和 `reason`。

- [ ] **Step 5: 实现研究诊断包裁剪**

```python
def build_research_packet(report, history):
    allowed = {
        "folds", "symbols", "sectors", "sides", "regimes",
        "exit_reasons", "signal_funnel", "mfe", "mae",
        "holding_bars", "standard", "two_x", "three_x",
        "delay_one_bar", "neighbors", "ablations",
        "profitable_symbol_rate", "positive_fold_count",
        "complexity_ratio",
    }
    packet = {key: report[key] for key in sorted(allowed)}
    packet["trial_history"] = history
    forbidden = {"holdout", "sealed", "holdout_start", "holdout_end"}
    if forbidden.intersection(packet):
        raise ValueError("sealed data leaked into research packet")
    return packet
```

- [ ] **Step 6: 添加消融和邻域固定规则**

策略契约增加可选 `COMPONENTS` 和 `PARAMETER_NEIGHBORS` 元数据。消融只允许关闭一个声明组件；邻域只能使用策略声明的固定上下界，Controller 不根据结果扩张搜索范围。

- [ ] **Step 7: 运行 evaluator 与 gate 测试**

Run: `python3 -m pytest -q tests/test_rc_lsr_evaluator.py tests/test_strategy_evolution_gate.py`

Expected: PASS，且研究诊断 JSON 中不存在任何 sealed/holdout 字段。

- [ ] **Step 8: 提交 Task 4**

```bash
git add code/run_rc_lsr_deep_audit.py code/strategy_evolution_gate.py tests/test_rc_lsr_evaluator.py tests/test_strategy_evolution_gate.py
git commit -m "feat: add deterministic strategy evaluation gates"
```

---

### Task 5: 建立独立 Campaign/Trial/Champion 账本

**Files:**
- Create: `code/strategy_evolution_agent.py`
- Create: `tests/test_strategy_evolution_agent.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 3 manifest、Task 4 report/verdict。
- Produces: `EvolutionLedger`，包含 `create_campaign()`、`record_trial()`、`set_campaign_status()`、`save_champion()`、`trial_history()`、`campaign()`。

- [ ] **Step 1: 写入失败测试，覆盖失败记录不可丢失**

```python
def test_ledger_records_failed_trials(tmp_path):
    ledger = EvolutionLedger(tmp_path / "evolution.db")
    ledger.create_campaign("c1", "rc_lsr_strategy", manifest())
    ledger.record_trial(
        campaign_id="c1",
        trial_no=1,
        status="INVALID_STRATEGY",
        parent_hash="base",
        candidate_hash="bad",
        proposal={"hypothesis": "forbidden negative shift"},
        verdict={"reasons": ["NEGATIVE_SHIFT"]},
        artifacts={},
    )
    rows = ledger.trial_history("c1")
    assert len(rows) == 1
    assert rows[0]["status"] == "INVALID_STRATEGY"
    assert rows[0]["verdict"]["reasons"] == ["NEGATIVE_SHIFT"]


def test_trial_number_is_unique_per_campaign(tmp_path):
    ledger = EvolutionLedger(tmp_path / "evolution.db")
    ledger.create_campaign("c1", "rc_lsr_strategy", manifest())
    ledger.record_trial("c1", 1, "FAILED", "a", "b", {}, {}, {})
    with pytest.raises(sqlite3.IntegrityError):
        ledger.record_trial("c1", 1, "FAILED", "a", "c", {}, {}, {})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k ledger`

Expected: FAIL，提示 `EvolutionLedger` 未定义。

- [ ] **Step 3: 实现最小 SQLite schema**

在 `EvolutionLedger.__init__()` 中创建：

```sql
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    status TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS trials (
    campaign_id TEXT NOT NULL,
    trial_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    parent_hash TEXT NOT NULL,
    candidate_hash TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    verdict_json TEXT NOT NULL,
    artifacts_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (campaign_id, trial_no),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
);
CREATE TABLE IF NOT EXISTS champions (
    campaign_id TEXT PRIMARY KEY,
    strategy_hash TEXT NOT NULL,
    strategy_path TEXT NOT NULL,
    development_report_json TEXT NOT NULL,
    sealed_report_json TEXT,
    shadow_report_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
);
```

连接时执行 `PRAGMA foreign_keys=ON` 和 `PRAGMA journal_mode=WAL`。所有 JSON 使用 `sort_keys=True`。

- [ ] **Step 4: 实现原子状态迁移**

允许状态：`BASELINE`、`RESEARCHING`、`DEVELOPMENT_CHAMPION`、`SEALED_AUDIT`、`CAMPAIGN_FAILED`、`SHADOW`、`SHADOW_FAILED`、`PAPER_APPROVED`、`SAFETY_STOP`、`NO_ROBUST_STRATEGY_FOUND`。在一个 `BEGIN IMMEDIATE` 事务中验证旧状态和新状态合法后更新。

- [ ] **Step 5: 更新 gitignore**

追加：

```gitignore
.superpowers/
data/strategy_evolution.db
data/strategy_evolution.db-shm
data/strategy_evolution.db-wal
data/evolution_runs/
```

- [ ] **Step 6: 运行账本测试**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k ledger`

Expected: PASS。

- [ ] **Step 7: 提交 Task 5**

```bash
git add code/strategy_evolution_agent.py tests/test_strategy_evolution_agent.py .gitignore
git commit -m "feat: add strategy evolution experiment ledger"
```

---

### Task 6: 接入已登录 Codex CLI 和隔离 Trial 工作区

**Files:**
- Modify: `code/strategy_evolution_agent.py`
- Modify: `tests/test_strategy_evolution_agent.py`

**Interfaces:**
- Consumes: proposal schema、constitution、研究诊断包、父策略路径。
- Produces: `CodexResearcher.check_login() -> bool`、`CodexResearcher.run(prompt, workspace, schema_path, output_path) -> dict`、`create_trial_workspace(parent_strategy, root) -> Path`、`validate_workspace_diff(workspace) -> list[str]`。

- [ ] **Step 1: 写入失败测试，锁定命令和认证边界**

```python
def test_codex_command_uses_saved_login_and_schema(tmp_path):
    researcher = CodexResearcher(codex_bin="codex")
    command = researcher.build_command(
        tmp_path, tmp_path / "proposal.schema.json", tmp_path / "proposal.json"
    )
    assert command[:2] == ["codex", "exec"]
    assert "--json" in command
    assert "--output-schema" in command
    assert "--sandbox" in command
    assert "workspace-write" in command
    assert "--ignore-user-config" in command
    assert all("API_KEY" not in part for part in command)


def test_workspace_diff_rejects_second_file(tmp_path):
    workspace = initialized_workspace(tmp_path)
    (workspace / "strategy.py").write_text("VALUE = 2\n")
    (workspace / "evaluator.py").write_text("VALUE = 2\n")
    assert validate_workspace_diff(workspace) == ["UNAUTHORIZED_CHANGED_FILES"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k 'codex or workspace'`

Expected: FAIL，提示 `CodexResearcher` 未定义。

- [ ] **Step 3: 实现一次性 Git 工作区**

```python
def create_trial_workspace(parent_strategy, root):
    workspace = Path(root).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    shutil.copy2(parent_strategy, workspace / "strategy.py")
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "strategy.py"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Strategy Agent", "-c",
         "user.email=strategy-agent@local", "commit", "-qm", "baseline"],
        cwd=workspace,
        check=True,
    )
    return workspace
```

工作区内不得复制 evaluator、数据库、`.env` 或认证文件。

- [ ] **Step 4: 实现 Codex 非交互调用**

```python
class CodexResearcher:
    def __init__(self, codex_bin="codex", timeout_seconds=900):
        self.codex_bin = codex_bin
        self.timeout_seconds = timeout_seconds

    def build_command(self, workspace, schema_path, output_path):
        return [
            self.codex_bin, "exec", "--json",
            "--output-schema", str(Path(schema_path).resolve()),
            "--sandbox", "workspace-write",
            "--ignore-user-config",
            "-o", str(Path(output_path).resolve()),
            "-",
        ]

    def check_login(self):
        result = subprocess.run(
            [self.codex_bin, "login", "status"],
            text=True, capture_output=True, timeout=30,
        )
        return result.returncode == 0 and "Logged in" in result.stdout

    def run(self, prompt, workspace, schema_path, output_path):
        env = dict(os.environ)
        env.pop("OPENAI_API_KEY", None)
        env.pop("CODEX_API_KEY", None)
        result = subprocess.run(
            self.build_command(workspace, schema_path, output_path),
            cwd=workspace,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "codex exec failed")
        return json.loads(Path(output_path).read_text(encoding="utf-8"))
```

- [ ] **Step 5: 实现 Prompt，禁止 AI 访问盲测和裁判**

Prompt 固定包含策略宪法、单一假设要求、研究诊断 JSON、历史 Trial 摘要、允许文件 `strategy.py`，并明确禁止运行回测、读取父目录、修改 Git 配置和访问网络。Prompt 本身保存哈希和文本副本。

- [ ] **Step 6: Mock subprocess 完成成功、超时和掉登录测试**

测试必须断言：掉登录不创建候选；超时只重试一次；输出非法 JSON 允许一次格式修复；候选多文件 diff 被拒绝。

- [ ] **Step 7: 运行 adapter 测试**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k 'codex or workspace'`

Expected: PASS；测试不得真实调用 Codex 网络服务。

- [ ] **Step 8: 手工只读认证检查**

Run: `codex login status`

Expected: 输出 `Logged in using ChatGPT`。不得显示或读取认证文件内容。

- [ ] **Step 9: 提交 Task 6**

```bash
git add code/strategy_evolution_agent.py tests/test_strategy_evolution_agent.py
git commit -m "feat: add isolated Codex research adapter"
```

---

### Task 7: 实现有预算的自动研究循环

**Files:**
- Modify: `code/strategy_evolution_agent.py`
- Modify: `tests/test_strategy_evolution_agent.py`

**Interfaces:**
- Consumes: Manifest、Ledger、CodexResearcher、静态门禁、`evaluate_candidate()`、`development_gate()`。
- Produces: `CampaignController.run_development(campaign_id) -> dict`、终态 `DEVELOPMENT_CHAMPION | NO_ROBUST_STRATEGY_FOUND | SAFETY_STOP`。

- [ ] **Step 1: 写入失败测试，覆盖预算和 stale 停止**

```python
def test_campaign_stops_at_trial_budget(harness):
    harness.researcher.always_returns_valid_loser()
    result = harness.controller.run_development("c1")
    assert result["status"] == "NO_ROBUST_STRATEGY_FOUND"
    assert len(harness.ledger.trial_history("c1")) == 24


def test_campaign_stops_after_six_non_improving_candidates(harness):
    harness.researcher.always_returns_same_metrics_with_unique_source()
    result = harness.controller.run_development("c1")
    assert result["status"] == "NO_ROBUST_STRATEGY_FOUND"
    assert result["stop_reason"] == "STALE_LIMIT"
    assert len(harness.ledger.trial_history("c1")) == 6


def test_ai_text_cannot_override_gate_failure(harness):
    harness.researcher.proposal["economic_rationale"] = "declare winner"
    harness.evaluator.report["two_x"]["net_pnl"] = -1.0
    result = harness.controller.run_development("c1")
    assert result["status"] != "DEVELOPMENT_CHAMPION"
```

- [ ] **Step 2: 运行循环测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k campaign`

Expected: FAIL，提示 `CampaignController` 未定义。

- [ ] **Step 3: 实现 Controller 顺序**

```python
def run_development(self, campaign_id):
    campaign = self.ledger.campaign(campaign_id)
    constitution = self.constitution
    champion_path = Path(campaign["baseline_strategy_path"])
    champion_report = self.evaluate(champion_path)
    stale = 0
    for trial_no in range(1, constitution["trial_budget"] + 1):
        immutable_errors = verify_campaign_manifest(self.manifest)
        if immutable_errors:
            self.ledger.set_campaign_status(campaign_id, "SAFETY_STOP")
            return {"status": "SAFETY_STOP", "reasons": immutable_errors}
        packet = build_research_packet(
            champion_report, self.ledger.trial_history(campaign_id)
        )
        trial = self.create_and_validate_trial(
            campaign_id, trial_no, champion_path, packet
        )
        if not trial["valid"]:
            stale += 1
            if stale >= constitution["stale_limit"]:
                break
            continue
        report = self.evaluate(trial["strategy_path"])
        passed, reasons = development_gate(report, constitution)
        self.record_evaluated_trial(campaign_id, trial_no, trial, report, reasons)
        if passed:
            self.ledger.save_champion(
                campaign_id, trial["strategy_path"], report
            )
            self.ledger.set_campaign_status(
                campaign_id, "DEVELOPMENT_CHAMPION"
            )
            return {"status": "DEVELOPMENT_CHAMPION", "report": report}
        if self.on_pareto_frontier(report, champion_report):
            champion_path = Path(trial["strategy_path"])
            champion_report = report
            stale = 0
        else:
            stale += 1
        if stale >= constitution["stale_limit"]:
            break
    self.ledger.set_campaign_status(campaign_id, "NO_ROBUST_STRATEGY_FOUND")
    return {"status": "NO_ROBUST_STRATEGY_FOUND", "stop_reason": "STALE_OR_BUDGET"}
```

非法 proposal 计入提案预算；只有完成回测的 candidate 计入 24 个 backtest 预算。Controller 另设最多 36 个 proposal 的硬上限，防止连续生成非法补丁形成无限循环。

- [ ] **Step 4: 实现 Pareto 比较**

候选只有在标准净收益更高且 `max_drawdown`、`turnover`、`complexity_ratio` 至少不恶化其中三项中的两项时，才能成为中间冠军。硬门禁通过时优先终止循环，不继续搜索更漂亮的历史曲线。

- [ ] **Step 5: 实现重复哈希跳过**

在调用 evaluator 前计算策略源、参数和 AST 归一化哈希；与 Ledger 中历史重复时记录 `DUPLICATE`，不消耗 backtest 预算，但消耗 proposal 预算。

- [ ] **Step 6: 运行完整循环单测**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py`

Expected: PASS，测试全部使用 fake researcher/evaluator，不发起真实 Codex 或长回测。

- [ ] **Step 7: 提交 Task 7**

```bash
git add code/strategy_evolution_agent.py tests/test_strategy_evolution_agent.py
git commit -m "feat: add bounded autonomous research loop"
```

---

### Task 8: 实现一次性密封盲测

**Files:**
- Modify: `code/strategy_evolution_gate.py`
- Modify: `code/strategy_evolution_agent.py`
- Modify: `tests/test_strategy_evolution_gate.py`
- Modify: `tests/test_strategy_evolution_agent.py`

**Interfaces:**
- Consumes: `DEVELOPMENT_CHAMPION`、冻结 champion hash、holdout manifest。
- Produces: `sealed_gate(report, constitution)`、`CampaignController.run_sealed_audit(campaign_id)`，终态 `SHADOW | CAMPAIGN_FAILED | SAFETY_STOP`。

- [ ] **Step 1: 写入失败测试，证明盲测只能运行一次**

```python
def test_sealed_audit_is_one_shot(harness):
    harness.promote_development_champion()
    first = harness.controller.run_sealed_audit("c1")
    assert first["status"] == "SHADOW"
    with pytest.raises(RuntimeError, match="sealed audit already consumed"):
        harness.controller.run_sealed_audit("c1")


def test_sealed_failure_is_terminal(harness):
    harness.promote_development_champion()
    harness.sealed_evaluator.report["net_pnl"] = -1.0
    result = harness.controller.run_sealed_audit("c1")
    assert result["status"] == "CAMPAIGN_FAILED"
    assert harness.researcher.call_count == 0
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k sealed`

Expected: FAIL，提示 `run_sealed_audit` 未定义。

- [ ] **Step 3: 实现 sealed gate**

```python
def sealed_gate(report, constitution):
    gate = constitution["sealed_gates"]
    reasons = []
    if report["net_pnl"] <= 0:
        reasons.append("SEALED_NON_POSITIVE_RETURN")
    if report["profit_factor"] < gate["min_profit_factor"]:
        reasons.append("SEALED_PROFIT_FACTOR")
    if report["max_drawdown"] > gate["max_drawdown"]:
        reasons.append("SEALED_DRAWDOWN")
    if report["profitable_symbol_rate"] < gate["min_profitable_symbol_rate"]:
        reasons.append("SEALED_CROSS_MARKET_RATE")
    if not report["ledger_reconciled"]:
        reasons.append("SEALED_LEDGER_MISMATCH")
    if report.get("hit_kill_switch", False):
        reasons.append("SEALED_KILL_SWITCH")
    return not reasons, reasons
```

- [ ] **Step 4: 实现一次性事务和零反馈**

Ledger 在同一事务中把 `sealed_consumed=1`、保存报告、设置终态。Research packet builder 必须拒绝含 `sealed_report`、`sealed_reasons` 或 holdout 日期的输入。失败后任何 `run_development()` 调用都抛出 terminal-state 错误。

- [ ] **Step 5: 运行盲测和泄漏测试**

Run: `python3 -m pytest -q tests/test_strategy_evolution_gate.py tests/test_strategy_evolution_agent.py -k 'sealed or holdout'`

Expected: PASS。

- [ ] **Step 6: 提交 Task 8**

```bash
git add code/strategy_evolution_gate.py code/strategy_evolution_agent.py tests/test_strategy_evolution_gate.py tests/test_strategy_evolution_agent.py
git commit -m "feat: add one-shot sealed strategy audit"
```

---

### Task 9: 实现无报单权限的 Shadow 虚拟盘生命周期

**Files:**
- Modify: `code/strategy_evolution_agent.py`
- Modify: `tests/test_strategy_evolution_agent.py`

**Interfaces:**
- Consumes: `SHADOW` champion、密封结束时间后新增的本地 30m Bars、冻结 evaluator。
- Produces: `run_shadow_cycle(campaign_id, as_of) -> dict`、状态 `SHADOW | SHADOW_FAILED | PAPER_APPROVED`。

- [ ] **Step 1: 写入失败测试，证明 Shadow 不能触达交易 API**

```python
def test_shadow_cycle_has_no_broker_or_order_dependency():
    source = Path("code/strategy_evolution_agent.py").read_text()
    forbidden = {"TqApi", "TqAccount", "insert_order", "TargetPosTask", "ctp"}
    assert forbidden.isdisjoint(source.split())


def test_shadow_requires_days_and_trades(harness):
    harness.set_status("SHADOW")
    harness.shadow_report.update({
        "calendar_days": 29,
        "closed_trades": 120,
        "net_pnl": 1000.0,
        "profit_factor": 1.20,
        "max_drawdown": 0.05,
        "signal_parity": 1.0,
        "hit_kill_switch": False,
    })
    result = harness.controller.run_shadow_cycle("c1", "2026-12-01")
    assert result["status"] == "SHADOW"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k shadow`

Expected: FAIL，提示 `run_shadow_cycle` 未定义。

- [ ] **Step 3: 实现只读新 Bar Shadow 周期**

`run_shadow_cycle()` 只查询 `holdout_end` 之后、`as_of` 之前的本地 `futures_min_bars`。使用冻结策略和 evaluator 增量重放，输出写入独立 Evolution Ledger；禁止导入或调用任何券商、TqSim、CTP、TargetPosTask 或订单接口。

- [ ] **Step 4: 实现 Shadow gate**

```python
def shadow_passes(report, gate):
    return (
        report["calendar_days"] >= gate["min_calendar_days"]
        and report["closed_trades"] >= gate["min_closed_trades"]
        and report["net_pnl"] > 0
        and report["profit_factor"] >= gate["min_profit_factor"]
        and report["max_drawdown"] <= gate["max_drawdown"]
        and report["signal_parity"] == 1.0
        and not report["hit_kill_switch"]
    )
```

超过 180 天仍未满足时设置 `SHADOW_FAILED`。达到门禁设置 `PAPER_APPROVED`，但只生成批准报告，不启动其他进程。

- [ ] **Step 5: 运行 Shadow 生命周期测试**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k shadow`

Expected: PASS，并确认源码无报单依赖。

- [ ] **Step 6: 提交 Task 9**

```bash
git add code/strategy_evolution_agent.py tests/test_strategy_evolution_agent.py
git commit -m "feat: add no-order shadow strategy lifecycle"
```

---

### Task 10: 增加 CLI、端到端演练和完整验证

**Files:**
- Modify: `code/strategy_evolution_agent.py`
- Modify: `tests/test_strategy_evolution_agent.py`
- Modify: `README.md` if present, otherwise Create: `docs/strategy-evolution-agent.md`

**Interfaces:**
- Consumes: Tasks 1-9 全部接口。
- Produces: `python3 code/strategy_evolution_agent.py` 的 `init`、`develop`、`sealed-audit`、`shadow-step`、`status` 子命令。

- [ ] **Step 1: 写入 CLI 失败测试**

```python
def test_cli_status_outputs_json(tmp_path, capsys):
    code = main([
        "--db", str(tmp_path / "evolution.db"),
        "status", "--campaign", "c1",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["campaign_id"] == "c1"


def test_cli_has_no_real_trade_command():
    parser = build_parser()
    help_text = parser.format_help()
    assert "live" not in help_text.lower()
    assert "real-trade" not in help_text.lower()
```

- [ ] **Step 2: 运行 CLI 测试并确认失败**

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py -k cli`

Expected: FAIL，提示 `build_parser` 或 `main` 未定义。

- [ ] **Step 3: 实现 argparse 子命令**

```python
def build_parser():
    parser = argparse.ArgumentParser(description="Isolated strategy evolution agent")
    parser.add_argument("--db", default="data/strategy_evolution.db")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--campaign", required=True)
    init.add_argument("--strategy", required=True)
    develop = sub.add_parser("develop")
    develop.add_argument("--campaign", required=True)
    sealed = sub.add_parser("sealed-audit")
    sealed.add_argument("--campaign", required=True)
    shadow = sub.add_parser("shadow-step")
    shadow.add_argument("--campaign", required=True)
    shadow.add_argument("--as-of", required=True)
    status = sub.add_parser("status")
    status.add_argument("--campaign", required=True)
    return parser
```

`main(argv=None)` 返回进程码；JSON 结果写 stdout，日志写 stderr。任何子命令都不接受 real account、broker、order 或 API key 参数。

- [ ] **Step 4: 创建文档，给出安全运行顺序**

文档必须包含以下实际命令：

```bash
codex login status
python3 code/strategy_evolution_agent.py init --campaign rc-lsr-20260905-001 --strategy strategies/rc_lsr_strategy.py
python3 code/strategy_evolution_agent.py status --campaign rc-lsr-20260905-001
python3 code/strategy_evolution_agent.py develop --campaign rc-lsr-20260905-001
python3 code/strategy_evolution_agent.py sealed-audit --campaign rc-lsr-20260905-001
python3 code/strategy_evolution_agent.py shadow-step --campaign rc-lsr-20260905-001 --as-of 2026-12-31T15:00:00
```

同时明确：只有 `DEVELOPMENT_CHAMPION` 才允许 sealed-audit；只有 `SHADOW` 才允许 shadow-step；`PAPER_APPROVED` 不是实盘授权。

- [ ] **Step 5: 运行不联网的端到端 fake 演练**

使用 fake researcher 和小型合成数据，验证：一个非法未来函数候选被拒；一个合法均值回归候选成为开发冠军；盲测通过后进入 Shadow；Shadow 达到天数和交易数后成为 `PAPER_APPROVED`。

Run: `python3 -m pytest -q tests/test_strategy_evolution_agent.py::test_end_to_end_fake_campaign`

Expected: PASS，无网络、无 Codex 真调用、无券商依赖。

- [ ] **Step 6: 运行全量相关测试**

Run: `python3 -m pytest -q tests/test_rc_lsr_strategy.py tests/test_rc_lsr_evaluator.py tests/test_strategy_evolution_gate.py tests/test_strategy_evolution_agent.py tests/test_learning_loop.py`

Expected: PASS。

- [ ] **Step 7: 运行静态和工作区验证**

Run: `python3 -m compileall -q code/strategy_evolution_agent.py code/strategy_evolution_gate.py strategies/rc_lsr_strategy.py`

Expected: exit 0。

Run: `git diff --check`

Expected: 无输出，exit 0。

Run: `git status --short`

Expected: 只显示本计划所列文件；现有用户脏改动保持原样且未被暂存。

- [ ] **Step 8: 进行一次最小真实 Codex 开发区演练**

建立新的测试 Campaign，将 proposal budget 设为 1、backtest budget 设为 1，只开放开发池。运行：

```bash
python3 code/strategy_evolution_agent.py develop --campaign rc-lsr-smoke-001
```

Expected: Codex 使用已登录 ChatGPT 账号生成一个结构化 proposal；只有 `strategy.py` 变化；密封盲测未运行；Trial Ledger 保存 prompt、proposal、diff、测试与 verdict。

- [ ] **Step 9: 复核安全产物**

运行 `status` 并人工确认：manifest hash 未变化；research packet 无 holdout 字段；未产生 `.env`、auth、broker 或订单文件；测试 Campaign 不处于 `SEALED_AUDIT`、`SHADOW` 或 `PAPER_APPROVED`。

- [ ] **Step 10: 提交 Task 10**

```bash
git add code/strategy_evolution_agent.py tests/test_strategy_evolution_agent.py docs/strategy-evolution-agent.md
git commit -m "docs: add strategy evolution operator workflow"
```

---

## 完成定义

- 相关测试全绿，且没有改写用户原有未提交文件。
- Codex CLI 在没有 API Key 环境变量时能通过已登录 ChatGPT 账号生成候选。
- 候选工作区越权、未来函数、策略漂移和重复试验均被确定性拒绝。
- evaluator/data/split/gate 任一哈希变化都会停止 Campaign。
- 开发循环有明确成功、stale、预算耗尽和安全终态。
- 密封盲测只能运行一次，结果不进入研究诊断包。
- Shadow 无券商或订单依赖，任何代码路径都不能自动实盘。
- 首次 RC-LSR 正式 Campaign 只能在人工复核 Task 10 最小演练产物后启动。
