# Futures ML Research Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one fail-closed, causally validated machine-learning research backtest for the imported five-minute futures weighted-index data.

**Architecture:** Extend the importer so SQLite preserves honest source fields and provenance, then add one offline `futures_research_backtest.py` path that validates/segments data, builds causal datasets, performs nested purged walk-forward selection, reconciles standardized fixed-sleeve returns, runs adversarial gates, and writes evidence. Legacy futures engines remain isolated and no Web/API or live-trading path is added.

**Tech Stack:** Python 3, standard library (`argparse`, `dataclasses`, `hashlib`, `json`, `sqlite3`), pandas, NumPy, scikit-learn, LightGBM, pytest, SQLite.

## Global Constraints

- Weighted-index data is research-only and may emit only `RESEARCH_ACCEPTED` or `RESEARCH_REJECTED`.
- Never emit lots, multipliers, margin, liquidation, RMB PnL, or live-readiness claims.
- Use signal-at-close and next-open execution; a label/trade may not cross a detected segment boundary.
- Keep the final 20% timestamp holdout locked until all development selection is complete.
- Use only the feature whitelist and the three predeclared model candidates and thresholds `0.52`, `0.55`, `0.58`.
- Run 0/2/5/10/20 bp cost checks and all predeclared adversarial gates.
- Do not register the new module in `hot_plugger` or `/api/strategies`.
- Do not repair or consume output from invalidated legacy futures/XAUUSD engines.
- Add no dependency, model family, framework, Web UI, persistence, scheduler, or automatic promotion.
- Preserve all unrelated dirty-worktree changes.
- Follow red-green TDD for every behavior and make only task-scoped commits.
- Before every task commit, run `pytest -q`; the complete suite must pass.

---

## File Map

- `code/import_futures_5m.py`: strict GB18030 parsing, source fields, idempotent schema migration, provenance, explicit replacement CLI.
- `code/futures_research_backtest.py`: the only new futures research path; contains the small data, temporal, model, ledger, adversarial, gate, and report functions listed below.
- `tests/test_import_futures_5m.py`: importer schema, provenance, transaction, and replacement behavior.
- `tests/test_futures_research_backtest.py`: causal dataset, folds, models, ledger, attacks, gates, reports, and real-database smoke behavior.
- `tests/test_web_validation.py`: keep the audited research module outside executable registries.
- `docs/research-only-ml-engines.md`: document the new audited research proxy separately from invalidated engines.
- `data/ashare_quant.db`: migrate and reimport only after an identical temporary-database import passes.

## Shared Interfaces

The new module exposes these stable interfaces; later tasks must use the exact names:

The immutable data types are `ResearchConfig`, `Candidate`, `TemporalFold`, and
`ResearchRejected`, with the fields and defaults supplied in Tasks 2, 3, and 5.
The callable signatures are:

- `load_futures_bars(db_path, timeframe="5m") -> pd.DataFrame`
- `validate_and_segment(bars, config=ResearchConfig()) -> tuple[pd.DataFrame, pd.DataFrame]`
- `build_causal_dataset(segmented, config=ResearchConfig()) -> pd.DataFrame`
- `make_temporal_partitions(dataset, config=ResearchConfig()) -> dict`
- `select_candidate(dataset, market, folds, config=ResearchConfig()) -> tuple[Candidate, pd.DataFrame]`
- `fit_predict(candidate, train, evaluation, config=ResearchConfig()) -> tuple[np.ndarray, object]`
- `simulate_standardized_ledger(scored, market, threshold, cost_bps, symbol_count) -> tuple[pd.DataFrame, pd.DataFrame]`
- `evaluate_fold(dataset, market, fold, candidate, config=ResearchConfig()) -> dict`
- `build_base_evaluation(dataset, market, partitions, config=ResearchConfig()) -> dict`
- `run_adversarial_checks(context) -> list[dict]`
- `evaluate_acceptance_gates(context) -> list[dict]`
- `build_adversarial_context(run_id, bars, segmented, quality, dataset, partitions, base, config) -> dict`
- `build_result(context, gates, status) -> dict`
- `rejected_result(run_id, config, reason) -> dict`
- `write_report(result, output_dir) -> dict[str, str]`
- `run_research(db_path, output_dir, config=ResearchConfig()) -> dict`

---

### Task 1: Make the futures import honest and transactional

**Files:**
- Modify: `code/import_futures_5m.py:1-112`
- Modify: `tests/test_import_futures_5m.py:1-55`

**Interfaces:**
- Consumes: GB18030 exports with title, header, and nine tab-separated data fields.
- Produces: `read_export(path) -> (rows, report, metadata)`, `ensure_schema(conn)`, and `import_exports(export_dir, db_path, replace_existing=False)`.

- [ ] **Step 1: Replace the permissive importer test with strict source-field and provenance tests**

Use one valid two-row export and assert explicit columns rather than table-order inserts:

```python
import hashlib
import sqlite3

import pytest

from import_futures_5m import import_exports


VALID_EXPORT = """AGL9 白银加权 5分钟线 不复权
日期\t时间\t开盘\t最高\t最低\t收盘\t成交量\t持仓量\t结算价
2026/08/12\t0905\t10\t12\t9\t11\t5\t100\t10.5
2026/08/12\t0910\t11\t13\t10\t12\t6\t101\t11.5
"""


def _write_export(directory, text=VALID_EXPORT):
    path = directory / "30#AGL9.txt"
    path.write_bytes(text.encode("gb18030"))
    return path


def test_import_preserves_source_fields_and_provenance(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    source = _write_export(export_dir)
    db_path = tmp_path / "quant.db"

    result = import_exports(export_dir, db_path)

    assert result == {
        "files": 1, "symbols": 1, "raw": 2,
        "rows": 2, "invalid": 0, "duplicates": 0,
    }
    with sqlite3.connect(db_path) as conn:
        bars = conn.execute(
            "SELECT trade_time, open, high, low, close, volume, amount, "
            "open_interest, settlement FROM futures_min_bars ORDER BY trade_time"
        ).fetchall()
        metadata = conn.execute(
            "SELECT source_file, source_title, series_type, source_encoding, "
            "source_sha256, row_count, start_time, end_time "
            "FROM futures_series_metadata WHERE symbol='AG_IDX' AND timeframe='5m'"
        ).fetchone()
    assert bars == [
        ("2026-08-12 09:05:00", 10.0, 12.0, 9.0, 11.0, 5.0, None, 100.0, 10.5),
        ("2026-08-12 09:10:00", 11.0, 13.0, 10.0, 12.0, 6.0, None, 101.0, 11.5),
    ]
    assert metadata == (
        source.name,
        "AGL9 白银加权 5分钟线 不复权",
        "WEIGHTED_INDEX",
        "gb18030",
        hashlib.sha256(source.read_bytes()).hexdigest(),
        2,
        "2026-08-12 09:05:00",
        "2026-08-12 09:10:00",
    )
```

Add separate tests proving that an invalid OHLC row, a duplicate timestamp, or
an unknown title raises `ValueError` and leaves both bar and metadata counts at
zero. Add a replacement test that imports once, rejects a second import without
`replace_existing=True`, then replaces only `AG_IDX/5m` while retaining its
`15m` row and another symbol.

- [ ] **Step 2: Run the importer tests and verify the intended red state**

Run: `pytest -q tests/test_import_futures_5m.py`

Expected: FAIL because `open_interest`, `settlement`, metadata, strict rollback,
and `replace_existing` do not exist and amount is still fabricated.

- [ ] **Step 3: Implement explicit schema, strict parsing, and provenance**

Replace positional SQL and permissive row dropping with these concrete pieces:

```python
import argparse
import hashlib
from datetime import datetime, timezone


INSERT_SQL = """
INSERT INTO futures_min_bars (
    symbol, timeframe, trade_time, open, high, low, close,
    volume, amount, open_interest, settlement
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS futures_min_bars (
            symbol TEXT, timeframe TEXT, trade_time TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, amount REAL,
            PRIMARY KEY (symbol, timeframe, trade_time)
        )
    """)
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(futures_min_bars)")
    }
    for name in ("open_interest", "settlement"):
        if name not in columns:
            conn.execute(f"ALTER TABLE futures_min_bars ADD COLUMN {name} REAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS futures_series_metadata (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_title TEXT NOT NULL,
            series_type TEXT NOT NULL CHECK (
                series_type IN (
                    'WEIGHTED_INDEX', 'MONTHLY_AVERAGE_WEIGHTED_INDEX'
                )
            ),
            source_encoding TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (symbol, timeframe)
        )
    """)


def _series_type(title):
    if "月均价加权" in title:
        return "MONTHLY_AVERAGE_WEIGHTED_INDEX"
    if "加权" in title:
        return "WEIGHTED_INDEX"
    raise ValueError(f"unsupported futures series title: {title}")
```

Implement `read_export()` so it reads the title before the CSV header, requires
exactly nine data fields, parses `fields[2:9]`, rejects the complete file at the
first malformed or duplicate row, stores `amount=None`, and returns metadata:

```python
rows.append((
    symbol, "5m", when, open_, high, low, close,
    volume, None, open_interest, settlement,
))
metadata = {
    "symbol": symbol,
    "timeframe": "5m",
    "source_file": path.name,
    "source_title": title,
    "series_type": _series_type(title),
    "source_encoding": "gb18030",
    "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "row_count": len(rows),
    "start_time": rows[0][2],
    "end_time": rows[-1][2],
    "imported_at": datetime.now(timezone.utc).isoformat(),
}
```

In `import_exports`, call `ensure_schema(conn)` once. For each file, use
`with conn:` so bars and metadata commit together. Query the existing target
count first; when it is non-zero and `replace_existing` is false, raise a
message containing `--replace-existing`. In replace mode delete only matching
`symbol/timeframe`, insert rows, and upsert its one metadata record.

Use an explicit CLI:

```python
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path, default=EXPORT_DIR)
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args(argv)
    print(import_exports(
        args.export_dir,
        args.db_path,
        replace_existing=args.replace_existing,
    ))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the importer tests and verify green**

Run: `pytest -q tests/test_import_futures_5m.py`

Expected: all importer tests pass; no warning or partial write remains.

- [ ] **Step 5: Commit the importer behavior**

```bash
git add code/import_futures_5m.py tests/test_import_futures_5m.py
git commit -m "fix: preserve honest futures source fields"
```

---

### Task 2: Add data loading, fail-closed validation, and causal segments

**Files:**
- Create: `code/futures_research_backtest.py`
- Create: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: migrated `futures_min_bars` and `futures_series_metadata`.
- Produces: `ResearchConfig`, `ResearchRejected`, `load_futures_bars`, and `validate_and_segment`.

- [ ] **Step 1: Write failing tests for loading and segment boundaries**

Create a helper that makes two symbols with valid five-minute bars. Test that
`load_futures_bars()` rejects missing metadata or a non-weighted series. Test
that `validate_and_segment()` starts a new segment for a time gap, zero volume,
previous-close/current-open gap over 3%, and adjacent close return over 3%.
Also assert BB-like data above 50% zero volume is excluded with reason
`ZERO_VOLUME_FRACTION`:

```python
def test_validation_segments_every_unusable_boundary():
    bars = make_bars(40)
    bars.loc[10, "trade_time"] += pd.Timedelta(minutes=5)
    bars.loc[20, "volume"] = 0.0
    bars.loc[30, "open"] = bars.loc[29, "close"] * 1.04
    bars.loc[30, "high"] = max(bars.loc[30, "high"], bars.loc[30, "open"])

    clean, quality = validate_and_segment(
        bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1)
    )

    changes = clean["segment_id"].ne(clean["segment_id"].shift()).to_numpy()
    assert changes[[0, 10, 20, 21, 30]].all()
    assert quality.loc["AG_IDX", "status"] == "INCLUDED"


def test_symbol_above_zero_volume_limit_is_excluded():
    bars = make_bars(20)
    bars.loc[:10, "volume"] = 0.0

    clean, quality = validate_and_segment(
        bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1)
    )

    assert clean.empty
    assert quality.loc["AG_IDX", "reason"] == "ZERO_VOLUME_FRACTION"
```

Add parametrized invalid-data cases for duplicate time, out-of-order input,
non-five-minute timestamps, non-finite prices, invalid OHLC, negative volume,
and negative open interest. Structural violations must raise
`ResearchRejected` rather than silently exclude a row.

- [ ] **Step 2: Run the focused tests and verify red**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'load or validation or segment or zero_volume'`

Expected: collection/import failure because the research module does not exist.

- [ ] **Step 3: Implement the data boundary**

Start the module with the exact config and whitelist constants from the spec:

```python
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


FEATURE_COLUMNS = (
    "ret_1", "ret_3", "ret_6", "ret_12", "vol_12", "vol_48",
    "range_pct", "body_pct", "close_pos", "ema_gap_12_48", "volume_z48",
)


@dataclass(frozen=True)
class ResearchConfig:
    horizon: int = 6
    discontinuity: float = 0.03
    max_zero_volume_fraction: float = 0.50
    min_symbol_rows: int = 1000
    min_fold_rows: int = 200
    min_symbols: int = 20
    holdout_fraction: float = 0.20
    embargo_bars: int = 6
    thresholds: tuple = (0.52, 0.55, 0.58)
    costs_bps: tuple = (0, 2, 5, 10, 20)
    seed: int = 42


class ResearchRejected(ValueError):
    pass
```

`load_futures_bars()` must join metadata, select explicit columns, parse
timestamps, require `series_type` in the two approved values, and reject an
empty result or any symbol without exactly one metadata row.

Implement `validate_and_segment()` per symbol. First validate all structural
invariants. Preserve input order only long enough to detect out-of-order data,
then sort by symbol/time. Use this boundary expression:

```python
gap = group["trade_time"].diff().ne(pd.Timedelta(minutes=5))
zero = group["volume"].eq(0)
zero_neighbor = zero | zero.shift(fill_value=False)
open_gap = group["open"].div(group["close"].shift()).sub(1).abs().gt(
    config.discontinuity
)
close_jump = group["close"].pct_change().abs().gt(config.discontinuity)
boundary = gap | zero_neighbor | open_gap | close_jump
boundary.iloc[0] = True
group["segment_id"] = group["symbol"] + ":" + boundary.cumsum().astype(str)
```

Create one quality row per symbol with raw rows, date bounds, zero-volume
fraction, segment count, status, and reason. Exclude a symbol above the zero
volume limit; do not drop individual structural violations.

- [ ] **Step 4: Verify the data tests pass**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'load or validation or segment or zero_volume'`

Expected: selected tests pass.

- [ ] **Step 5: Commit the data boundary**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: validate futures research segments"
```

---

### Task 3: Build causal features, labels, and purged temporal partitions

**Files:**
- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: segmented bars from Task 2.
- Produces: `build_causal_dataset`, `assert_feature_columns`, `TemporalFold`, `purged_training_rows`, and `make_temporal_partitions`.

- [ ] **Step 1: Write failing causal and split tests**

Use at least 100 deterministic bars per segment and assert the six-bar label
uses `open[t+1]` to `open[t+7]`, never close-to-close. Append ten future bars
and assert all pre-existing feature values and matured labels are identical.
Construct a boundary inside a potential label path and assert that decision row
is absent.

Add a whitelist test:

```python
def test_feature_whitelist_rejects_future_and_unknown_columns():
    matrix = pd.DataFrame({name: [0.0] for name in FEATURE_COLUMNS})
    assert_feature_columns(matrix)
    with pytest.raises(ResearchRejected, match="feature whitelist"):
        assert_feature_columns(matrix.assign(future_return=1.0))
    with pytest.raises(ResearchRejected, match="feature whitelist"):
        assert_feature_columns(matrix.assign(symbol_code=1.0))
```

Create a dataset with 1,500 unique timestamps and two symbols. Assert final
holdout begins at the first timestamp at or after index `floor(0.8 * n)`, the
development outer evaluation windows are contiguous/non-overlapping, and every
purged training label ends before evaluation start with six prior symbol bars
absent.

- [ ] **Step 2: Run causal/split tests and verify red**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'feature or label or prefix or partition or purge or embargo'`

Expected: FAIL because dataset and temporal functions are missing.

- [ ] **Step 3: Implement the causal dataset**

Compute features inside `groupby(["symbol", "segment_id"])` only. Use pandas
rolling/EMA operations and shifted volume baseline:

```python
def _segment_features(group):
    close = group["close"].astype(float)
    volume = group["volume"].astype(float)
    feature = pd.DataFrame(index=group.index)
    for horizon in (1, 3, 6, 12):
        feature[f"ret_{horizon}"] = close.pct_change(horizon)
    feature["vol_12"] = close.pct_change().rolling(12).std()
    feature["vol_48"] = close.pct_change().rolling(48).std()
    feature["range_pct"] = (group["high"] - group["low"]) / close
    feature["body_pct"] = (group["close"] - group["open"]) / close
    span = (group["high"] - group["low"]).replace(0.0, np.nan)
    feature["close_pos"] = (group["close"] - group["low"]) / span
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema48 = close.ewm(span=48, adjust=False).mean()
    feature["ema_gap_12_48"] = (ema12 - ema48) / ema48
    prior_mean = volume.shift(1).rolling(48).mean()
    prior_std = volume.shift(1).rolling(48).std().replace(0.0, np.nan)
    feature["volume_z48"] = (volume - prior_mean) / prior_std
    return feature
```

For each segment add decision, entry, and exit positions using shifts `-1` and
`-(horizon + 1)`. Require all shifted rows to retain the same `segment_id`.
Store `entry_time`, `entry_open`, `exit_time`, `exit_open`, `label_end_time`,
`future_return`, and binary `label`. Drop rows with incomplete or non-finite
whitelisted features; never fill them.

Implement exact whitelist equality:

```python
def assert_feature_columns(matrix):
    observed = tuple(matrix.columns)
    if observed != FEATURE_COLUMNS:
        raise ResearchRejected(
            f"feature whitelist mismatch: expected={FEATURE_COLUMNS}, observed={observed}"
        )
```

- [ ] **Step 4: Implement deterministic partitions and purge**

Add the dataclass and split helpers:

```python
@dataclass(frozen=True)
class TemporalFold:
    name: str
    train_times: pd.DatetimeIndex
    evaluation_times: pd.DatetimeIndex


def _contiguous_windows(times, count):
    return [pd.DatetimeIndex(part) for part in np.array_split(times, count)]


def purged_training_rows(dataset, train_times, evaluation_start, embargo_bars):
    train = dataset[
        dataset["decision_time"].isin(train_times)
        & (dataset["label_end_time"] < evaluation_start)
    ].copy()
    keep = pd.Series(True, index=train.index)
    for _, group in train.groupby("symbol", sort=False):
        keep.loc[group.sort_values("decision_time").tail(embargo_bars).index] = False
    return train.loc[keep]
```

`make_temporal_partitions()` must:

1. sort unique decision timestamps;
2. reserve the last 20%, using split index `floor(0.8 * n)`;
3. require at least 30 distinct dates in holdout;
4. use the first 40% of development timestamps as initial outer training;
5. split the remainder into three outer evaluation windows;
6. construct two equivalent inner folds for each outer training window and for
   the full development window;
7. derive `eligible_symbols` by requiring `min_fold_rows` in every outer and
   holdout evaluation window, and return that set with the folds;
8. reject empty windows, fewer than three outer folds, or fewer than
   `min_symbols` eligible symbols.

- [ ] **Step 5: Verify causal and temporal tests pass**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'feature or label or prefix or partition or purge or embargo'`

Expected: selected tests pass with exact prefix equality.

- [ ] **Step 6: Commit causal dataset and temporal isolation**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: add purged futures research dataset"
```

---

### Task 4: Implement the standardized non-overlapping mark-to-market ledger

**Files:**
- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: scored causal dataset rows containing decision/entry/exit times and prices.
- Produces: `simulate_standardized_ledger` and `strategy_metrics`.

- [ ] **Step 1: Write failing accounting and position tests**

Construct explicit long and short rows plus their intermediate market bars and
verify entry-notional accounting at 5 bp:

```python
def test_ledger_reconciles_long_short_and_double_sided_costs():
    scored = pd.DataFrame([
        make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0),
        make_scored("CU_IDX", "2026-01-01 09:05", 0.20, 100.0, 90.0),
    ])

    trades, daily = simulate_standardized_ledger(
        scored, make_mark_market(), threshold=0.55, cost_bps=5, symbol_count=2
    )

    c = 5 / 10_000
    expected_long = (110 / 100 - 1) - c * (1 + 110 / 100)
    expected_short = -(90 / 100 - 1) - c * (1 + 90 / 100)
    assert trades["net_sleeve_return"].tolist() == pytest.approx(
        [expected_long, expected_short]
    )
    assert daily["portfolio_return"].sum() == pytest.approx(
        (expected_long + expected_short) / 2
    )
```

Add tests proving:

- repeated or alternating decisions before a symbol's `exit_time` produce one
  position only;
- row order does not change the ledger;
- fixed `1/N` sleeves keep gross exposure at or below one;
- an adverse intermediate close appears in daily equity and maximum drawdown
  even when the trade later exits profitably;
- identical trades at 0/2/5/10/20 bp have monotonically non-increasing returns;
- a defensive row with `exit_open` missing uses supplied `terminal_open`, pays
  exit cost, and records `TERMINAL_CLOSE`;
- every trade and daily aggregate reconciles within `1e-12`.

- [ ] **Step 2: Run the ledger tests and verify red**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'ledger or overlap or sleeve or cost or terminal or order'`

Expected: FAIL because the ledger does not exist.

- [ ] **Step 3: Implement deterministic trade construction**

Use these exact return helpers:

```python
def _direction(probability, threshold):
    if probability >= threshold:
        return 1
    if probability <= 1.0 - threshold:
        return -1
    return 0


def _net_sleeve_return(direction, entry_open, exit_open, cost_bps):
    ratio = float(exit_open) / float(entry_open)
    cost = float(cost_bps) / 10_000.0
    gross = int(direction) * (ratio - 1.0)
    return gross, cost, cost * ratio, gross - cost * (1.0 + ratio)
```

`simulate_standardized_ledger()` must validate threshold `(0.5, 1.0)`, finite
positive prices/probabilities, positive `symbol_count`, required columns, and a
segmented `market` frame containing every mark timestamp. Sort decisions by
`(entry_time, symbol, decision_time)`. Track `available_after` per symbol and
skip a row whose entry is earlier than the prior exit. Assign each symbol an
initial sleeve equity of `1 / symbol_count`; compound later trades within that
same sleeve and never redistribute inactive sleeve equity.

For each accepted row record:

```python
trade = {
    "symbol": row.symbol,
    "decision_time": row.decision_time,
    "entry_time": row.entry_time,
    "exit_time": exit_time,
    "direction": direction,
    "entry_open": entry_open,
    "exit_open": exit_open,
    "gross_return": gross,
    "entry_cost": entry_cost,
    "exit_cost": exit_cost,
    "net_sleeve_return": net_return,
    "portfolio_return": net_return / symbol_count,
    "threshold": threshold,
    "cost_bps": cost_bps,
    "exit_reason": exit_reason,
}
```

At entry, record the sleeve's starting equity. Until exit, mark that sleeve on
every available bar close as:

```python
marked_sleeve = start_equity * (
    1.0 - entry_cost_rate
    + direction * (mark_close / entry_open - 1.0)
)
```

At exit, replace the mark with
`start_equity * (1 + net_sleeve_return)`, which includes both costs. Inactive
sleeves remain unchanged cash. Portfolio equity at each timestamp is the sum
of all sleeve equities; daily equity is the last timestamp mark per date and
daily return is its percentage change from the prior date, using initial equity
`1.0` for the first date. Recompute each trade, sleeve transition, timestamp
equity, and daily equity before returning; raise `ResearchRejected("ledger
mismatch")` above `1e-12`.

- [ ] **Step 4: Implement finite strategy metrics**

`strategy_metrics(trades, daily)` returns exact finite values:

```python
{
    "days": int,
    "trades": int,
    "total_return": float,
    "annualized_return": float,
    "annualized_volatility": float,
    "sharpe": float,
    "max_drawdown": float,
    "win_rate": float,
    "profit_factor": float,
    "exposure": float,
    "turnover": float,
}
```

Use 252 daily periods, sample standard deviation, compounded equity, and peak
drawdown. Use zero for undefined ratios; reject non-finite inputs rather than
converting them silently.

- [ ] **Step 5: Verify the ledger suite passes**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'ledger or overlap or sleeve or cost or terminal or order or strategy_metrics'`

Expected: selected tests pass.

- [ ] **Step 6: Commit the standardized ledger**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: reconcile futures research returns"
```

---

### Task 5: Add constrained models and inner selection

**Files:**
- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: purged training/evaluation datasets and the Task 4 ledger.
- Produces: `Candidate`, `candidate_names`, `fit_predict`, `inverse_symbol_class_weights`, and `select_candidate`.

- [ ] **Step 1: Write failing model-boundary and selection tests**

Use a deterministic dataset with more than 400 rows, both labels, and two
symbols. Assert:

- candidate names are exactly `logistic_c0.1`, `logistic_c1.0`, and
  `lightgbm_constrained`;
- probabilities are finite and within `[0, 1]`;
- adding extreme values only to evaluation rows cannot change the fitted
  logistic scaler or existing training transformation;
- inverse weights give equal total weight to each symbol and class;
- selection ignores a high-return candidate when either inner fold is
  non-positive at 5 bp;
- median return wins among eligible candidates, followed by turnover, logistic
  preference, then higher threshold.

Test the selection rule with an explicit score frame so it is independent of
model randomness:

```python
def test_selection_requires_both_inner_folds_positive():
    scores = pd.DataFrame([
        {"model_name": "lightgbm_constrained", "threshold": 0.52,
         "fold": "inner_1", "return_5bps": 0.20, "turnover": 0.4},
        {"model_name": "lightgbm_constrained", "threshold": 0.52,
         "fold": "inner_2", "return_5bps": -0.01, "turnover": 0.4},
        {"model_name": "logistic_c0.1", "threshold": 0.55,
         "fold": "inner_1", "return_5bps": 0.02, "turnover": 0.2},
        {"model_name": "logistic_c0.1", "threshold": 0.55,
         "fold": "inner_2", "return_5bps": 0.01, "turnover": 0.2},
    ])
    assert choose_from_scores(scores) == Candidate("logistic_c0.1", 0.55)
```

- [ ] **Step 2: Run model tests and verify red**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'candidate or model or weight or scaler or selection'`

Expected: FAIL because candidate fitting and selection are missing.

- [ ] **Step 3: Implement fixed candidates and balanced weights**

Add imports without changing project dependencies:

```python
from lightgbm import LGBMClassifier
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
```

Define candidates and weights:

```python
@dataclass(frozen=True)
class Candidate:
    model_name: str
    threshold: float


def candidate_names():
    return ("logistic_c0.1", "logistic_c1.0", "lightgbm_constrained")


def inverse_symbol_class_weights(frame):
    symbol_count = frame.groupby("symbol")["symbol"].transform("size")
    class_count = frame.groupby("label")["label"].transform("size")
    weights = 1.0 / symbol_count.astype(float) / class_count.astype(float)
    return weights / weights.mean()
```

Implement private `_fit_matrix(candidate, x_train, y_train, sample_weight,
x_evaluation, config)` to construct and fit the fixed estimator. Production
`fit_predict()` first calls `assert_feature_columns` on the exact incoming
feature matrices, rejects a one-class train/evaluation set, then delegates to
`_fit_matrix`. Only the isolated feature-attack path may call `_fit_matrix`
with an explicitly recorded expanded matrix. Construct only these estimators:

```python
if candidate.model_name.startswith("logistic_c"):
    c_value = float(candidate.model_name.removeprefix("logistic_c"))
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=c_value, penalty="l2", solver="liblinear",
            max_iter=1000, random_state=config.seed,
        ),
    )
elif candidate.model_name == "lightgbm_constrained":
    model = LGBMClassifier(
        n_estimators=100, learning_rate=0.03, max_depth=3,
        num_leaves=7, min_child_samples=200, subsample=0.8,
        colsample_bytree=0.8, subsample_freq=1, reg_alpha=1.0,
        reg_lambda=5.0, objective="binary", verbosity=-1,
        n_jobs=1, random_state=config.seed,
    )
else:
    raise ResearchRejected(f"unknown model candidate: {candidate.model_name}")
```

Fit with `logisticregression__sample_weight` for the `make_pipeline` result and
`sample_weight` for LightGBM. Return positive-class probability and the fitted
model; never fit a scaler outside the pipeline.

- [ ] **Step 4: Implement inner scoring and deterministic selection**

For every model and threshold, fit once per inner fold, attach probabilities to
the evaluation rows, run the 5 bp ledger, and collect predictive metrics,
return, and turnover. Implement `choose_from_scores()` exactly:

```python
def choose_from_scores(scores):
    grouped = []
    for (model_name, threshold), rows in scores.groupby(
        ["model_name", "threshold"], sort=False
    ):
        if len(rows) != 2 or not (rows["return_5bps"] > 0).all():
            continue
        grouped.append({
            "candidate": Candidate(str(model_name), float(threshold)),
            "median_return": float(rows["return_5bps"].median()),
            "turnover": float(rows["turnover"].mean()),
        })
    if not grouped:
        raise ResearchRejected("no candidate passed both inner folds")
    best_return = max(row["median_return"] for row in grouped)
    near = [
        row for row in grouped
        if best_return - row["median_return"] <= 0.001
    ]
    near.sort(key=lambda row: (
        row["turnover"],
        row["candidate"].model_name == "lightgbm_constrained",
        -row["candidate"].threshold,
    ))
    return near[0]["candidate"]
```

`select_candidate(dataset, market, folds, config)` must return the chosen
candidate and every inner score row. Report the dummy-prior probabilities and
metrics separately but never add them to `choose_from_scores`.

- [ ] **Step 5: Verify the constrained model tests pass**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'candidate or model or weight or scaler or selection'`

Expected: selected tests pass with deterministic probabilities.

- [ ] **Step 6: Commit model selection**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: constrain futures ML selection"
```

---

### Task 6: Run outer folds and the locked final holdout

**Files:**
- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: Tasks 2-5 data, splits, candidates, models, and ledger.
- Produces: `predictive_metrics`, `evaluate_fold`, `moving_block_return_interval`, and `build_base_evaluation`.

- [ ] **Step 1: Write failing end-to-end temporal evaluation tests**

Build a small deterministic multi-symbol dataset through the public causal
dataset interface. Use a config with reduced minimum row limits but unchanged
split percentages. Assert:

- exactly three outer fold results are produced;
- every outer selected candidate came only from that fold's inner scores;
- final selection is rerun once on all development data;
- final fit excludes labels reaching the locked holdout and applies embargo;
- the holdout's labels and returns are not accessed by candidate selection;
- single-class evaluation and non-finite predictions reject the run;
- 1,000 five-day moving-block samples are deterministic at seed 42.

Instrument holdout label access with a DataFrame subclass or a guard column
that raises before final evaluation; do not mock model predictions.

- [ ] **Step 2: Run temporal evaluation tests and verify red**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'outer or holdout or base_evaluation or bootstrap'`

Expected: FAIL because orchestration and bootstrap are missing.

- [ ] **Step 3: Implement predictive and fold evaluation**

`predictive_metrics(labels, probability, threshold)` returns ROC AUC, balanced
accuracy, Brier score, and Spearman rank correlation. Reject one-class labels
and all non-finite inputs.

`evaluate_fold(dataset, market, fold, candidate, config)` performs only this
order:

1. call `purged_training_rows`;
2. call `fit_predict` with the already selected candidate;
3. attach probabilities to a copy of evaluation rows;
4. compute predictive metrics;
5. call the ledger with the same segmented market independently for every
   configured cost without changing trades, probabilities, or threshold;
6. calculate holdout/outer per-symbol metrics from the same trades and fixed
   sleeve paths;
7. run dummy-prior and equal-weight long-only benchmarks on exactly the same
   eligible timestamps and costs;
8. return split cutoffs, sample counts, metrics, benchmarks, per-symbol rows,
   trades, daily frames, and the fitted model identity.

Model identity is SHA256 over model name, parameters, feature names, training
cutoff, training-row pandas hash, and target pandas hash. Store the first 16
hexadecimal characters.

- [ ] **Step 4: Implement development and locked-holdout orchestration**

`build_base_evaluation(dataset, market, partitions, config)` follows this exact
flow:

```python
outer_results = []
for fold in partitions["outer_folds"]:
    inner = partitions["inner_by_outer"][fold.name]
    chosen, inner_scores = select_candidate(dataset, market, inner, config)
    outer_results.append(evaluate_fold(dataset, market, fold, chosen, config))

final_candidate, final_inner_scores = select_candidate(
    dataset, market, partitions["development_inner_folds"], config
)
holdout_result = evaluate_fold(
    dataset, market,
    partitions["holdout_fold"],
    final_candidate,
    config,
)
return {
    "outer_results": outer_results,
    "final_candidate": final_candidate,
    "final_inner_scores": final_inner_scores,
    "holdout": holdout_result,
}
```

No function accepts holdout metrics as a selection input.

- [ ] **Step 5: Implement the locked-holdout block interval**

Use `np.random.default_rng(config.seed)`. For each of 1,000 samples, concatenate
random contiguous five-day blocks until the sample reaches the original daily
length, compound `np.prod(1 + returns) - 1`, and report 5th, 50th, and 95th
percentiles. Reject fewer than five daily observations.

- [ ] **Step 6: Verify outer and holdout tests pass**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'outer or holdout or base_evaluation or bootstrap'`

Expected: selected tests pass and repeated runs are byte-for-byte deterministic
apart from an explicitly supplied run identifier.

- [ ] **Step 7: Commit temporal evaluation**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: lock futures ML holdout evaluation"
```

---

### Task 7: Add adversarial attacks and non-negotiable gates

**Files:**
- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: complete base evaluation and its locked holdout from Task 6.
- Produces: `run_prefix_attack`, `run_label_shuffle_attack`, `run_feature_attack`, `run_adversarial_checks`, and `evaluate_acceptance_gates`.

- [ ] **Step 1: Write failing attack tests**

Add direct tests for every hostile path:

- appending future bars leaves earlier feature rows, matured labels, split
  membership, and probabilities equal within `1e-12`;
- future/unknown columns are rejected by the whitelist;
- all 20 within-symbol label permutations use seed 42, never mutate the source
  dataset, and return 20 metrics;
- five hash-derived noise columns depend only on `(seed, symbol, decision_time,
  column_number)` and repeat exactly;
- calendar attack columns contain only time-of-day sine/cosine and day-of-week
  sine/cosine;
- attack variants cannot replace the baseline candidate;
- a deliberately leaking feature attack and a profitable shuffled-label result
  each make the gate result fail.

Use a small context fixture with explicit observed values to test each gate
without fitting models:

```python
def test_any_failed_gate_rejects_status():
    context = passing_gate_context()
    context["outer_results"][1]["cost_metrics"][5]["total_return"] = -0.001

    gates = evaluate_acceptance_gates(context)

    assert any(
        gate["id"] == "positive_5bps_each_fold" and not gate["passed"]
        for gate in gates
    )
    assert research_status(gates) == "RESEARCH_REJECTED"
```

- [ ] **Step 2: Run adversarial tests and verify red**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'attack or shuffle or noise or calendar or gate or status'`

Expected: FAIL because attacks and acceptance gates are missing.

- [ ] **Step 3: Implement deterministic attack data**

Generate noise without process-dependent Python `hash()`:

```python
def _hash_noise(symbol, decision_time, column, seed):
    token = f"{seed}|{symbol}|{pd.Timestamp(decision_time).isoformat()}|{column}"
    integer = int(hashlib.sha256(token.encode()).hexdigest()[:16], 16)
    return integer / float(0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0
```

`run_prefix_attack()` rebuilds on original bars and bars plus appended future
bars, reapplies the original run's frozen partition cutoffs to both datasets,
compares only timestamps before the original cutoff, and checks features,
matured labels, split membership, and predictions with `rtol=0`, `atol=1e-12`.

`run_label_shuffle_attack()` performs 20 permutations independently within
each symbol's development training labels using `np.random.default_rng(42 +
permutation_number)`, refits the preselected final model, and evaluates the
unchanged locked holdout. Return every AUC and 5 bp return plus their maximum
and median.

`run_feature_attack(kind)` creates either five deterministic noise columns or
four calendar columns. It expands a local attack-only matrix, calls only
`_fit_matrix`, fits the same candidate on development data, and evaluates the
holdout. It must not alter `FEATURE_COLUMNS`, selection scores, candidate,
threshold, or baseline output.

- [ ] **Step 4: Implement all ten acceptance gates**

Return one record per design gate:

```python
{
    "id": "positive_5bps_each_fold",
    "passed": bool,
    "observed": object,
    "required": object,
    "affected_fold": str | None,
}
```

Implement exact predicates:

1. all structural/causal/ledger/prefix checks are true;
2. each outer and holdout AUC is greater than `0.50`;
3. each outer and holdout 5 bp total return is greater than zero;
4. holdout five-day block-bootstrap 5th percentile is greater than zero;
5. observed holdout AUC exceeds maximum shuffled AUC and median shuffled 5 bp
   return is non-positive;
6. noise and calendar attacks each improve AUC by no more than `0.01` and 5 bp
   return by no more than `0.05` absolute;
7. at least 50% of eligible symbols have positive holdout 5 bp return;
8. top-five positive symbol contributions are no more than 50% of total
   positive symbol contribution;
9. every outer/holdout 10 bp return is greater than `-0.10` and drawdown is less
   than `0.20`;
10. the identical-trade returns at 0/2/5/10/20 bp are monotonically
    non-increasing.

`research_status(gates)` returns `RESEARCH_ACCEPTED` only when every record has
`passed is True`; there is no override argument.

- [ ] **Step 5: Verify adversarial and gate tests pass**

Run: `pytest -q tests/test_futures_research_backtest.py -k 'attack or shuffle or noise or calendar or gate or status'`

Expected: selected tests pass; intentional attack fixtures are rejected.

- [ ] **Step 6: Commit adversarial gates**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: adversarially gate futures ML research"
```

---

### Task 8: Add report artifacts, CLI, and registry isolation

**Files:**
- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_futures_research_backtest.py`
- Modify: `tests/test_web_validation.py:8-20,250-275`
- Modify: `docs/research-only-ml-engines.md:1-20`

**Interfaces:**
- Consumes: base evaluation, attacks, and gates.
- Produces: `write_report`, `run_research`, and CLI `main(argv=None)`.

- [ ] **Step 1: Write failing report and isolation tests**

Create a compact rejected result fixture and assert `write_report()` creates
exactly these files with one run ID:

```python
EXPECTED_REPORT_FILES = {
    "report.md", "report.json", "data_quality.csv",
    "fold_metrics.csv", "symbol_metrics.csv", "trades.csv",
}


def test_report_artifacts_reconcile_and_preserve_rejection(tmp_path):
    result = rejected_result_fixture()

    paths = write_report(result, tmp_path)

    assert set(paths) == EXPECTED_REPORT_FILES
    payload = json.loads((tmp_path / "report.json").read_text())
    assert payload["status"] == "RESEARCH_REJECTED"
    assert payload["run_id"] == result["run_id"]
    assert "positive_5bps_each_fold" in (tmp_path / "report.md").read_text()
    assert len(pd.read_csv(tmp_path / "trades.csv")) == len(result["trades"])
```

Add a test calling `run_research()` with a tiny fixture DB and reduced minimums;
it must return a status and complete report on a gate rejection instead of
raising an unexplained exception or writing a partial directory.

Extend `test_invalidated_ml_engines_are_documented_and_not_executable` with:

```python
assert "futures_research_backtest" not in executable
assert "futures_research_backtest" not in exposed
assert "`futures_research_backtest` — `AUDITED_RESEARCH_PROXY`" in status
```

- [ ] **Step 2: Run report/isolation tests and verify red**

Run: `pytest -q tests/test_futures_research_backtest.py tests/test_web_validation.py::test_invalidated_ml_engines_are_documented_and_not_executable -k 'report or run_research or invalidated'`

Expected: FAIL because the writer, orchestrator, CLI, and audited status entry
are missing.

- [ ] **Step 3: Implement complete fail-closed orchestration**

`run_research()` executes only this dependency order:

```python
def run_research(db_path, output_dir, config=ResearchConfig()):
    run_id = uuid.uuid4().hex
    try:
        bars = load_futures_bars(db_path)
        segmented, quality = validate_and_segment(bars, config)
        dataset = build_causal_dataset(segmented, config)
        eligible = dataset.groupby("symbol").size()
        eligible = eligible[eligible >= config.min_symbol_rows].index
        dataset = dataset[dataset["symbol"].isin(eligible)].copy()
        if len(eligible) < config.min_symbols:
            raise ResearchRejected("too few eligible symbols")
        partitions = make_temporal_partitions(dataset, config)
        eligible = pd.Index(partitions["eligible_symbols"])
        dataset = dataset[dataset["symbol"].isin(eligible)].copy()
        if len(eligible) < config.min_symbols:
            raise ResearchRejected("too few fold-eligible symbols")
        base = build_base_evaluation(dataset, segmented, partitions, config)
        context = build_adversarial_context(
            run_id, bars, segmented, quality, dataset, partitions, base, config
        )
        attacks = run_adversarial_checks(context)
        context["attacks"] = attacks
        gates = evaluate_acceptance_gates(context)
        result = build_result(context, gates, research_status(gates))
    except ResearchRejected as exc:
        result = rejected_result(run_id, config, str(exc))
    result["artifacts"] = write_report(result, output_dir)
    return result
```

`build_adversarial_context()` returns one dictionary containing every source
frame, base result, and immutable config required by attacks and gates.
`build_result()` converts that context into JSON/CSV-safe records without
dropping trades or failed gates. `rejected_result()` returns the same top-level
schema with empty frames, status `RESEARCH_REJECTED`, and a `RUN_PRECONDITION`
gate containing the reason.

Do not catch `KeyboardInterrupt`, `SystemExit`, memory exhaustion, or arbitrary
programming exceptions. `ResearchRejected` represents expected fail-closed
research outcomes; unexpected defects must remain visible to tests/operators.

- [ ] **Step 4: Implement atomic report writing and CLI**

Write all artifacts to a sibling temporary directory, parse/reconcile them,
then rename the directory to the requested output path. Refuse a non-empty
output directory rather than overwrite evidence.

The Markdown begins with status and the sentence “加权指数研究回测，不代表可
成交合约或实盘收益”. Include data exclusions, split cutoffs, selected
candidate, all cost tables, per-symbol concentration, attacks, every gate, and
limitations. JSON includes source SHA256, code revision from `git rev-parse
HEAD` when available, config, features, candidates, seed, cutoffs, metrics,
attacks, gates, and status.

Add CLI:

```python
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_research(args.db_path, args.output_dir)
    print(json.dumps({
        "status": result["status"],
        "run_id": result["run_id"],
        "artifacts": result["artifacts"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "RESEARCH_ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Document the audited research-only boundary**

Keep every existing invalidated line unchanged. Add a separate section:

```markdown
## Audited offline research proxy

- `futures_research_backtest` — `AUDITED_RESEARCH_PROXY`

This module may run only as an offline weighted-index research backtest. It is
not an executable strategy, contract simulator, live-trading path, or evidence
of realizable futures PnL. Its own adversarial gates determine
`RESEARCH_ACCEPTED` or `RESEARCH_REJECTED` for each run.
```

- [ ] **Step 6: Verify reports and isolation pass**

Run: `pytest -q tests/test_futures_research_backtest.py tests/test_web_validation.py::test_invalidated_ml_engines_are_documented_and_not_executable -k 'report or run_research or invalidated'`

Expected: selected tests pass and the API registry remains unchanged.

- [ ] **Step 7: Commit reports and isolation**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py tests/test_web_validation.py docs/research-only-ml-engines.md
git commit -m "feat: report audited futures ML research"
```

---

### Task 9: Validate migration, reimport the real data, run the full adversarial backtest, and verify the repository

**Files:**
- Modify through importer: `data/ashare_quant.db`
- Generate: explicit run directory under `data/reports/futures_research/`
- Test: complete repository test suite

**Interfaces:**
- Consumes: Tasks 1-8 and the 85 source exports.
- Produces: migrated database plus one complete accepted/rejected research report.

- [ ] **Step 1: Run the complete test suite before touching the real database**

Run: `pytest -q`

Expected: all existing and new tests pass, with only explicitly documented
skips. Stop on any failure.

- [ ] **Step 2: Import all exports into a temporary database**

```bash
lianghua_import_tmp="$(mktemp -d)"
python3 code/import_futures_5m.py \
  --export-dir data/export \
  --db-path "$lianghua_import_tmp/quant.db" \
  --replace-existing
```

Expected summary: 85 files, 85 symbols, 1,116,253 rows, zero invalid rows, zero
duplicate rows.

- [ ] **Step 3: Verify the temporary database contract**

Run these read-only checks against `$lianghua_import_tmp/quant.db`:

```bash
sqlite3 "$lianghua_import_tmp/quant.db" "PRAGMA integrity_check;"
sqlite3 "$lianghua_import_tmp/quant.db" "SELECT COUNT(*), COUNT(DISTINCT symbol), SUM(amount IS NOT NULL), SUM(open_interest IS NULL), SUM(settlement IS NULL) FROM futures_min_bars WHERE timeframe='5m';"
sqlite3 "$lianghua_import_tmp/quant.db" "SELECT COUNT(*), SUM(series_type='WEIGHTED_INDEX'), SUM(series_type='MONTHLY_AVERAGE_WEIGHTED_INDEX') FROM futures_series_metadata WHERE timeframe='5m';"
```

Expected:

- integrity: `ok`;
- bars: `1116253|85|0|0|0`;
- metadata: `85|82|3`.

- [ ] **Step 4: Compare every source and temporary-database boundary**

Add a one-shot verification invocation to the importer tests or use its public
`read_export()` from `python3 -c`. For every file assert source rows equal DB
rows and source first/last timestamps equal metadata start/end. Expected:
`85/85 matched` and no mismatch list.

- [ ] **Step 5: Back up and migrate the real database explicitly**

```bash
cp data/ashare_quant.db /private/tmp/ashare_quant.pre-futures-research.db
python3 code/import_futures_5m.py \
  --export-dir data/export \
  --db-path data/ashare_quant.db \
  --replace-existing
```

Expected: the same 85-file/1,116,253-row summary. The backup path is reported
to the user and retained until final verification succeeds.

- [ ] **Step 6: Run database integrity and exact post-migration assertions**

Run the same three SQLite queries from Step 3 against
`data/ashare_quant.db`. Expected values must match exactly.

- [ ] **Step 7: Run the complete adversarial research backtest**

Choose a new explicit directory using the current timestamp, then run:

```bash
python3 code/futures_research_backtest.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/futures_research/2026-08-13-full
```

Expected process exit:

- `0` only for `RESEARCH_ACCEPTED`;
- `2` for an evidence-complete `RESEARCH_REJECTED`;
- any other exit is an implementation failure and must be debugged before
  completion.

Do not tune and rerun because the frozen holdout failed. A rejection is a valid
research conclusion when all six artifacts are complete and reconciled.

- [ ] **Step 8: Verify generated evidence**

Parse `report.json`, all four CSV files, and `report.md`. Assert:

- one shared run ID;
- finite metrics;
- exact three outer folds plus one locked holdout;
- 20 label permutations;
- 0/2/5/10/20 bp tables;
- every gate has observed/required/passed fields;
- trade count and aggregate returns reconcile to `trades.csv` within `1e-12`;
- Markdown and JSON terminal statuses match.

- [ ] **Step 9: Run final regression and syntax checks**

Run:

```bash
pytest -q
python3 -m py_compile code/import_futures_5m.py code/futures_research_backtest.py
sqlite3 data/ashare_quant.db "PRAGMA integrity_check;"
git diff --check
```

Expected: full tests pass, compilation exits zero, SQLite prints `ok`, and diff
check has no output.

- [ ] **Step 10: Commit only the migrated database after verification**

```bash
git add data/ashare_quant.db
git commit -m "data: preserve futures research provenance"
```

Leave the generated report directory available for user review. Do not add it
to a commit unless the user explicitly requests versioned research artifacts.

---

## Completion Checklist

- [ ] Every production behavior was preceded by a failing focused test.
- [ ] All focused tests were observed red for the intended reason, then green.
- [ ] The complete test suite passes after every task boundary.
- [ ] The temporary import exactly matches all 85 source files before the real
  database changes.
- [ ] The migrated real database passes integrity and schema assertions.
- [ ] The final report is complete whether accepted or rejected.
- [ ] No invalidated engine entered a registry or contributed evidence.
- [ ] No unrelated dirty-worktree change was staged or committed.
- [ ] The final response reports actual status and gate failures without
  interpreting weighted-index returns as realizable futures PnL.
