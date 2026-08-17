# Data Contract, Backtest, and Qlib Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent mixed or unprovenanced stock/futures data from entering backtests, make price semantics explicit, and keep Qlib as a fail-closed model-only component.

**Architecture:** Add one small `data_contract.py` module for asset classification, catalog verification, and read-only database auditing. Make `KLineBacktestEngine` call that contract before model work, preserve the existing futures research authority, and make the Qlib adapter reject dependency failures instead of silently changing model paths.

**Tech Stack:** Python 3.10, SQLite, pandas, NumPy, pytest, existing scikit-learn/LightGBM/Qlib stack.

## Global Constraints

- Do not delete or rewrite existing database rows.
- Existing catalog rows without explicit `asset_type` become `LEGACY_UNVERIFIED`.
- `STRICT` stock backtests require verified `RAW`; `RESEARCH_PROXY` may use verified `QFQ` only.
- `_IDX` symbols are never valid stock/ETF assets.
- Uncataloged symbols never enter a stock portfolio automatically.
- Futures remain a provenance-approved 5m-to-15m weighted-index research proxy.
- Qlib receives only validated in-memory matrices and has no silent native fallback.
- No new dependency and no live/TqSim re-enable.
- Every behavior change follows a failing test first.

---

### Task 1: Create the shared asset/data contract and read-only audit

**Files:**

- Create: `code/data_contract.py`
- Modify: `code/ashare_data_engine.py:108-117,225-430,463-490`
- Create: `tests/test_data_contract.py`
- Modify: `tests/test_data_engine.py` catalog INSERT statements

**Interfaces:**

- Produces: `DataContractError`, `ensure_asset_type_column(conn)`, `validate_stock_contract(conn, symbol, start_date, end_date, backtest_mode) -> dict`, `validate_stock_universe(conn, symbols, start_date, end_date, backtest_mode) -> list[dict]`, `audit_database(db_path) -> dict`.
- Consumes: `stock_daily`, `stock_daily_catalog`, `stock_basic`, `futures_min_bars`, and `futures_series_metadata`.

- [ ] **Step 1: Add failing contract tests**

```python
# tests/test_data_contract.py
import sqlite3

import pytest

from data_contract import (
    DataContractError,
    audit_database,
    ensure_asset_type_column,
    validate_stock_contract,
    validate_stock_universe,
)


def make_db(tmp_path, *, catalog=True, asset_type="STOCK", price_mode="QFQ"):
    db_path = tmp_path / "contract.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE stock_daily (
            symbol TEXT, trade_date TEXT, open REAL, close REAL, high REAL,
            low REAL, volume REAL, amount REAL, amplitude REAL, pct_chg REAL,
            change_amount REAL, turnover_rate REAL,
            PRIMARY KEY(symbol, trade_date)
        );
        CREATE TABLE stock_daily_catalog (
            symbol TEXT PRIMARY KEY, price_mode TEXT NOT NULL, source TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, row_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE stock_basic (symbol TEXT, name TEXT);
        """)
        for day in ("2025-01-02", "2025-01-03"):
            conn.execute(
                "INSERT INTO stock_daily VALUES (?, ?, 10, 10, 11, 9, 100, 1000, 2, 0, 0, 1)",
                ("000001", day),
            )
        conn.execute("INSERT INTO stock_basic VALUES ('000001', 'sample')")
        if catalog:
            conn.execute("""
                INSERT INTO stock_daily_catalog
                (symbol, price_mode, source, start_date, end_date, row_count, updated_at)
                VALUES ('000001', ?, 'TEST', '2025-01-02', '2025-01-03', 2, 'now')
            """, (price_mode,))
        ensure_asset_type_column(conn)
        conn.execute(
            "UPDATE stock_daily_catalog SET asset_type=? WHERE symbol='000001'",
            (asset_type,),
        )
    return db_path


def test_qfq_proxy_is_verified_but_strict_raw_is_rejected(tmp_path):
    db_path = make_db(tmp_path, price_mode="QFQ")

    with sqlite3.connect(db_path) as conn:
        proxy = validate_stock_contract(
            conn, "000001", "2025-01-02", "2025-01-03", "RESEARCH_PROXY"
        )
        assert proxy["price_semantics"] == "ADJUSTED_PROXY"
        with pytest.raises(DataContractError, match="RAW"):
            validate_stock_contract(
                conn, "000001", "2025-01-02", "2025-01-03", "STRICT"
            )


def test_idx_and_uncataloged_symbols_are_rejected(tmp_path):
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(DataContractError, match="asset"):
            validate_stock_contract(
                conn, "AG_IDX", "2025-01-02", "2025-01-03", "RESEARCH_PROXY"
            )
        with pytest.raises(DataContractError, match="catalog"):
            validate_stock_contract(
                conn, "000002", "2025-01-02", "2025-01-03", "RESEARCH_PROXY"
            )


def test_universe_validation_rejects_any_invalid_member(tmp_path):
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(DataContractError, match="000002"):
            validate_stock_universe(
                conn, ["000001", "000002"],
                "2025-01-02", "2025-01-03", "RESEARCH_PROXY"
            )


def test_audit_is_read_only_and_reports_mixed_domains(tmp_path):
    db_path = make_db(tmp_path)
    before = db_path.read_bytes()

    audit = audit_database(db_path)

    assert audit["stock"]["catalog_mismatch_count"] == 0
    assert "uncataloged_symbols" in audit["stock"]
    assert db_path.read_bytes() == before
```

- [ ] **Step 2: Run the new tests and verify RED**

```bash
python3 -m pytest -q tests/test_data_contract.py
```

Expected: import failure because `data_contract.py` and `asset_type` support do not exist.

- [ ] **Step 3: Add the idempotent catalog migration**

In `AShareDataEngine.ensure_schema`, after creating `stock_daily_catalog`, add:

```python
columns = {
    row[1] for row in cursor.execute(
        "PRAGMA table_info(stock_daily_catalog)"
    )
}
if "asset_type" not in columns:
    cursor.execute(
        "ALTER TABLE stock_daily_catalog ADD COLUMN "
        "asset_type TEXT NOT NULL DEFAULT 'LEGACY_UNVERIFIED'"
    )
```

Update every catalog write in `sync_stock_daily` to use an explicit column list
including `asset_type`, with the sync method's stock default set to `STOCK`.
Update the existing tests' catalog INSERT statements to include
`asset_type='STOCK'` or the intended test value. Do not infer asset type from a
suffix inside the write path.

- [ ] **Step 4: Implement `code/data_contract.py`**

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

from market_data import MarketDataError


class DataContractError(MarketDataError):
    def __init__(self, message, error_code="DATA_CONTRACT_INVALID"):
        super().__init__(message)
        self.error_code = error_code


def ensure_asset_type_column(conn):
    columns = {
        row[1] for row in conn.execute(
            "PRAGMA table_info(stock_daily_catalog)"
        )
    }
    if "asset_type" not in columns:
        conn.execute(
            "ALTER TABLE stock_daily_catalog ADD COLUMN "
            "asset_type TEXT NOT NULL DEFAULT 'LEGACY_UNVERIFIED'"
        )


def _reject_symbol(symbol):
    value = str(symbol).strip().upper()
    if value.endswith("_IDX"):
        raise DataContractError(
            f"{value} is a futures index, not a stock asset",
            "ASSET_TYPE_MISMATCH",
        )
    return value


def validate_stock_contract(conn, symbol, start_date, end_date, backtest_mode):
    value = _reject_symbol(symbol)
    if backtest_mode not in {"STRICT", "RESEARCH_PROXY"}:
        raise DataContractError("invalid stock backtest mode", "INVALID_BACKTEST_MODE")
    ensure_asset_type_column(conn)
    catalog = conn.execute("""
        SELECT symbol, asset_type, price_mode, source, start_date, end_date,
               row_count, updated_at
        FROM stock_daily_catalog WHERE symbol=?
    """, (value,)).fetchone()
    if catalog is None:
        raise DataContractError(
            f"stock symbol {value} has no catalog provenance",
            "UNCATALOGED_STOCK",
        )
    keys = (
        "symbol", "asset_type", "price_mode", "source", "start_date",
        "end_date", "row_count", "updated_at",
    )
    provenance = dict(zip(keys, catalog))
    if provenance["asset_type"] not in {"STOCK", "ETF"}:
        raise DataContractError(
            f"stock symbol {value} has unverified asset type",
            "UNVERIFIED_ASSET_TYPE",
        )
    actual = conn.execute("""
        SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
        FROM stock_daily WHERE symbol=?
    """, (value,)).fetchone()
    if tuple(actual) != (
        provenance["start_date"], provenance["end_date"], provenance["row_count"]
    ):
        raise DataContractError(
            f"stock catalog coverage mismatch for {value}",
            "CATALOG_COVERAGE_MISMATCH",
        )
    if provenance["start_date"] > start_date or provenance["end_date"] < end_date:
        raise DataContractError(
            f"stock data does not cover requested range for {value}",
            "INSUFFICIENT_DATA_COVERAGE",
        )
    if provenance["price_mode"] not in {"RAW", "QFQ"}:
        raise DataContractError(
            f"stock symbol {value} has unknown price mode",
            "UNKNOWN_PRICE_MODE",
        )
    if backtest_mode == "STRICT" and provenance["price_mode"] != "RAW":
        raise DataContractError(
            "strict stock backtest requires RAW prices",
            "RAW_EXECUTION_UNAVAILABLE",
        )
    provenance["verification_status"] = "VERIFIED"
    provenance["price_semantics"] = (
        "RAW_EXECUTION" if provenance["price_mode"] == "RAW"
        else "ADJUSTED_PROXY"
    )
    return provenance


def validate_stock_universe(conn, symbols, start_date, end_date, backtest_mode):
    values = [str(symbol).strip().upper() for symbol in symbols]
    if not values or len(set(values)) != len(values):
        raise DataContractError("stock universe must be non-empty and unique")
    return [
        validate_stock_contract(
            conn, value, start_date, end_date, backtest_mode
        )
        for value in values
    ]


def audit_database(db_path):
    path = Path(db_path)
    if not path.is_file():
        raise DataContractError("database is missing", "DATABASE_MISSING")
    with sqlite3.connect(path) as conn:
        catalog_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(stock_daily_catalog)"
            )
        }
        asset_type_available = "asset_type" in catalog_columns
        stock = conn.execute("""
            SELECT COUNT(*) AS rows, COUNT(DISTINCT symbol) AS symbols,
                   SUM(symbol LIKE '%_IDX') AS index_rows
            FROM stock_daily
        """).fetchone()
        uncataloged = conn.execute("""
            SELECT COUNT(DISTINCT d.symbol) FROM stock_daily d
            LEFT JOIN stock_daily_catalog c ON c.symbol=d.symbol
            WHERE c.symbol IS NULL
        """).fetchone()[0]
        asset_type_clause = (
            "c.asset_type='LEGACY_UNVERIFIED'"
            if asset_type_available else "1=1"
        )
        mismatch = conn.execute(f"""
            SELECT COUNT(*) FROM stock_daily_catalog c
            WHERE {asset_type_clause}
               OR c.row_count != (
                   SELECT COUNT(*) FROM stock_daily d WHERE d.symbol=c.symbol
               )
               OR c.start_date != (
                   SELECT MIN(trade_date) FROM stock_daily d WHERE d.symbol=c.symbol
               )
               OR c.end_date != (
                   SELECT MAX(trade_date) FROM stock_daily d WHERE d.symbol=c.symbol
               )
        """).fetchone()[0]
        futures = conn.execute("""
            SELECT COUNT(*) rows, COUNT(DISTINCT symbol) symbols,
                   SUM(volume=0) zero_volume
            FROM futures_min_bars WHERE timeframe='5m'
        """).fetchone()
    return {
        "stock": {
            "rows": stock[0], "symbols": stock[1],
            "index_rows": stock[2] or 0,
            "uncataloged_symbols": uncataloged,
            "catalog_mismatch_count": mismatch,
        },
        "futures_5m": {
            "rows": futures[0], "symbols": futures[1],
            "zero_volume": futures[2] or 0,
        },
    }
```

Keep the audit read-only: `ensure_asset_type_column` is called by schema
setup, but `audit_database` must inspect existing schemas without committing a
migration. If the production schema lacks the column, report all catalogs as
legacy/unverified rather than changing the database during an audit.

- [ ] **Step 5: Verify contract tests GREEN**

```bash
python3 -m pytest -q tests/test_data_contract.py tests/test_data_engine.py
```

Expected: all contract and catalog-atomicity tests pass.

- [ ] **Step 6: Commit the data contract**

```bash
git add code/data_contract.py code/ashare_data_engine.py \
  tests/test_data_contract.py tests/test_data_engine.py
git diff --cached --check
git commit -m "fix: enforce asset and data provenance contracts"
```

### Task 2: Enforce the contract in stock backtests and portfolios

**Files:**

- Modify: `code/backtest_kline_engine.py:18-22,330-390,701-771,936-1032`
- Modify: `tests/test_backtest_integration.py:41-155,280-360,936-1050`

**Interfaces:**

- Produces: stock backtests that return structured `DATA_CONTRACT_*` errors before model fitting; truthful `backtest_metadata` with `asset_type` and `price_semantics`.
- Consumes: `validate_stock_contract()` and `validate_stock_universe()`.

- [ ] **Step 1: Add failing backtest boundary tests**

```python
def test_research_proxy_rejects_uncataloged_stock(tmp_path, monkeypatch):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    monkeypatch.setattr(
        backtest_kline_engine, "walk_forward_predict", deterministic_predictions
    )

    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-10-31", backtest_mode="RESEARCH_PROXY"
    )

    assert result["error_code"] == "UNCATALOGED_STOCK"


def test_idx_symbol_is_rejected_by_stock_backtest(tmp_path):
    engine = KLineBacktestEngine(build_test_db(tmp_path, symbols=("AG_IDX",)))

    result = engine.run_kline_backtest(
        "AG_IDX", "2025-07-01", "2025-10-31", backtest_mode="RESEARCH_PROXY"
    )

    assert result["error_code"] == "ASSET_TYPE_MISMATCH"


def test_portfolio_does_not_fallback_to_mixed_stock_daily_symbols(tmp_path):
    engine = KLineBacktestEngine(build_test_db(tmp_path, symbols=("AG_IDX",)))

    result = engine.run_portfolio_backtest(
        symbols=None, start_date="2025-07-01", end_date="2025-10-31",
        backtest_mode="RESEARCH_PROXY",
    )

    assert result["error_code"] == "INSUFFICIENT_VERIFIED_UNIVERSE"


def test_research_proxy_metadata_states_adjusted_proxy(tmp_path, monkeypatch):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    catalog_symbol(engine, "000001", asset_type="STOCK")
    monkeypatch.setattr(
        backtest_kline_engine, "walk_forward_predict", deterministic_predictions
    )

    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-10-31", backtest_mode="RESEARCH_PROXY"
    )

    assert result["backtest_metadata"]["asset_type"] == "STOCK"
    assert result["backtest_metadata"]["price_semantics"] == "ADJUSTED_PROXY"
```

Update the test helper `catalog_symbol()` to insert `asset_type='STOCK'` and
update tests that intentionally exercise legacy unverified behavior to expect
the new structured rejection. Update `build_test_db()` so its normal fixture
creates a verified QFQ `stock_daily_catalog` row for every requested
stock-like symbol; otherwise every existing proxy-mode test would fail for the
right reason before reaching the behavior it is testing:

```python
conn.execute("""
    CREATE TABLE stock_daily_catalog (
        symbol TEXT PRIMARY KEY, price_mode TEXT NOT NULL, source TEXT NOT NULL,
        start_date TEXT NOT NULL, end_date TEXT NOT NULL, row_count INTEGER NOT NULL,
        asset_type TEXT NOT NULL, updated_at TEXT NOT NULL
    )
""")
# after inserting each symbol's bars:
conn.execute("""
    INSERT INTO stock_daily_catalog
    (symbol, price_mode, source, start_date, end_date, row_count, asset_type, updated_at)
    SELECT ?, 'QFQ', 'TEST_QFQ', MIN(trade_date), MAX(trade_date), COUNT(*), 'STOCK', 'now'
    FROM stock_daily WHERE symbol=?
""", (symbol, symbol))
```

Change `catalog_symbol()` from an INSERT to an UPDATE of the existing fixture
row, accepting `asset_type="STOCK"`; tests for unverified/uncataloged behavior
must explicitly delete that row before invoking the engine.

- [ ] **Step 2: Run the boundary tests and verify RED**

```bash
python3 -m pytest -q tests/test_backtest_integration.py \
  -k 'uncataloged or idx or portfolio or metadata'
```

Expected: the old engine either runs an unverified proxy or discovers mixed
symbols instead of returning the new data-contract errors.

- [ ] **Step 3: Guard single-symbol loading**

Import the contract functions in `backtest_kline_engine.py`. In
`run_kline_backtest`, after opening the connection and before `_load_market`,
call:

```python
try:
    provenance = validate_stock_contract(
        db_connection, clean_symbol, start_date, end_date, backtest_mode
    )
except DataContractError as exc:
    return {"error": str(exc), "error_code": exc.error_code}
```

Remove the legacy `_data_provenance()` fallback for active runs. Keep the
method only if existing forensic callers need it, but active backtests must use
the validated contract result.

- [ ] **Step 4: Guard portfolio universe and metadata**

Replace the automatic-universe fallback block with a catalog-only query:

```python
if automatic_universe:
    candidates = [
        str(row[0]) for row in conn.execute("""
            SELECT c.symbol FROM stock_daily_catalog c
            WHERE c.asset_type IN ('STOCK', 'ETF')
            ORDER BY c.symbol LIMIT 12
        """).fetchall()
    ]
    if len(candidates) < 1:
        return {
            "error": "no verified stock/ETF universe is available",
            "error_code": "INSUFFICIENT_VERIFIED_UNIVERSE",
        }
    symbols = candidates
else:
    symbols = [str(symbol) for symbol in symbols]

try:
    universe_provenance = validate_stock_universe(
        conn, symbols, start_date, end_date, backtest_mode
    )
except DataContractError as exc:
    return {"error": str(exc), "error_code": exc.error_code}
```

Inside the per-symbol loop, use the matching item from
`universe_provenance` instead of recomputing `_data_provenance`. Add
`asset_type`, `price_mode`, `price_semantics`, and `verification_status` to
`backtest_metadata`; retain the existing limitations.

- [ ] **Step 5: Verify stock backtests GREEN**

```bash
python3 -m pytest -q tests/test_backtest_integration.py \
  tests/test_backtest_metrics.py tests/test_data_contract.py
```

Expected: all tests pass, strict QFQ rejection remains intact, and proxy mode
only runs with a verified catalog entry.

- [ ] **Step 6: Commit stock backtest enforcement**

```bash
git add code/backtest_kline_engine.py tests/test_backtest_integration.py
git diff --cached --check
git commit -m "fix: enforce stock provenance in backtests"
```

### Task 3: Add database smoke audit and truthful report metadata

**Files:**

- Modify: `code/data_contract.py` only if audit fields need correction
- Modify: `code/backtest_kline_engine.py:190-220`
- Create: `tests/test_database_contract_audit.py`
- Modify: `tests/test_backtest_integration.py`

**Interfaces:**

- Produces: read-only `audit_database()` output and stock reports that state asset/price semantics and contract limitations.
- Consumes: current SQLite database without mutating it.

- [ ] **Step 1: Write failing metadata/audit tests**

```python
def test_database_audit_counts_mixed_stock_daily_domain(tmp_path):
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stock_daily VALUES "
            "('AG_IDX','2025-01-02',10,10,11,9,100,1000,2,0,0,1)"
        )

    result = audit_database(db_path)

    assert result["stock"]["index_rows"] == 1
    assert result["stock"]["uncataloged_symbols"] == 1


def test_backtest_metadata_never_labels_qfq_as_raw(tmp_path, monkeypatch):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    catalog_symbol(engine, "000001", asset_type="STOCK")
    monkeypatch.setattr(
        backtest_kline_engine, "walk_forward_predict", deterministic_predictions
    )

    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-10-31", backtest_mode="RESEARCH_PROXY"
    )

    metadata = result["backtest_metadata"]
    assert metadata["price_mode"] == "QFQ_ADJUSTED_PROXY"
    assert metadata["price_semantics"] == "ADJUSTED_PROXY"
    assert metadata["asset_type"] == "STOCK"
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python3 -m pytest -q tests/test_database_contract_audit.py \
  tests/test_backtest_integration.py -k 'audit or metadata'
```

Expected: the audit fields and asset/price metadata are absent or mislabeled.

- [ ] **Step 3: Add truthful metadata fields**

Extend `_backtest_metadata()` with:

```python
metadata.update({
    "asset_type": data_provenance.get("asset_type"),
    "source": data_provenance.get("source"),
    "verification_status": data_provenance.get("verification_status"),
    "coverage_start": data_provenance.get("start_date"),
    "coverage_end": data_provenance.get("end_date"),
    "price_semantics": price_semantics,
})
```

Do not change the existing explicit limitation strings; add
`UNCATALOGED_ASSETS_REJECTED` and `MIXED_ASSET_DOMAINS_REJECTED`.

- [ ] **Step 4: Run read-only production audit**

```bash
PYTHONPATH=code python3 -c 'import json; from data_contract import audit_database; print(json.dumps(audit_database("data/ashare_quant.db"), indent=2, ensure_ascii=False))'
```

Expected: JSON reports the existing mixed `_IDX` rows and catalog coverage
without changing `data/ashare_quant.db`.

- [ ] **Step 5: Verify and commit metadata/audit changes**

```bash
python3 -m pytest -q tests/test_database_contract_audit.py \
  tests/test_backtest_integration.py tests/test_data_contract.py
git diff --check
git add code/data_contract.py code/backtest_kline_engine.py \
  tests/test_database_contract_audit.py tests/test_backtest_integration.py
git commit -m "feat: report truthful stock data semantics"
```

### Task 4: Make Qlib model-only and fail closed

**Files:**

- Modify: `code/qlib_model_adapter.py:107-168`
- Modify: `code/futures_research_backtest.py:326-390`
- Modify: `tests/test_qlib_futures_backtest.py`

**Interfaces:**

- Produces: `ResearchRejected("Qlib dependency unavailable")` on Qlib import/training failure; model provenance fields for successful Qlib fits.
- Consumes: validated feature matrices from the existing research pipeline.

- [ ] **Step 1: Write failing Qlib boundary tests**

```python
def test_qlib_model_identity_declares_model_only_role():
    qlib_adapter, features, labels, weights = make_qlib_fixture()
    probability, model = qlib_adapter.fit_qlib_lightgbm(
        features.iloc[:400], labels.iloc[:400], weights.iloc[:400],
        features.iloc[400:], 42,
    )

    params = model.get_params()
    assert params["validation"] == "external_nested_walk_forward"
    assert params["backend"] == "qlib.LGBModel"
    assert "provider" not in params
    assert "executor" not in params


def test_qlib_failure_does_not_fallback_to_native(monkeypatch):
    import qlib_model_adapter
    features, labels, weights = make_model_fixture()

    monkeypatch.setattr(
        qlib_model_adapter,
        "fit_qlib_lightgbm",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ImportError("qlib unavailable")
        ),
    )
    with pytest.raises(research.ResearchRejected, match="Qlib"):
        research._fit_matrix(
            research.Candidate("qlib_lightgbm_constrained", 0.55),
            features.iloc[:400], labels.iloc[:400], weights.iloc[:400],
            features.iloc[400:], research.ResearchConfig(model_backend="qlib"),
        )
```

Define the test data helpers once above these tests:

```python
def make_model_fixture():
    rng = np.random.default_rng(42)
    features = pd.DataFrame(
        rng.normal(size=(500, len(research.FEATURE_COLUMNS))),
        columns=research.FEATURE_COLUMNS,
    )
    labels = pd.Series(np.arange(500) % 2, name="label")
    weights = pd.Series(np.ones(500), index=features.index)
    return features, labels, weights


def make_qlib_fixture():
    import qlib_model_adapter
    features, labels, weights = make_model_fixture()
    return qlib_model_adapter, features, labels, weights
```

- [ ] **Step 2: Run Qlib tests and verify RED**

```bash
python3 -m pytest -q tests/test_qlib_futures_backtest.py \
  -k 'model_only or qlib_failure'
```

Expected: the model-only metadata assertion is incomplete and ImportError
bubbles out instead of becoming `ResearchRejected`.

- [ ] **Step 3: Convert Qlib failures to structured rejection**

In `_fit_matrix`, wrap only the Qlib model call:

```python
try:
    probability, model = fit_qlib_lightgbm(
        x_train, y_train, sample_weight, x_evaluation, config.seed
    )
except (ImportError, ModuleNotFoundError, OSError, ValueError) as exc:
    raise ResearchRejected(
        f"Qlib model unavailable: {exc}"
    ) from exc
```

Do not route the failed Qlib candidate to native LightGBM or logistic
regression. The existing candidate selection may still choose logistic when it
is explicitly a selectable candidate and independently passes its folds.

Add to Qlib parameters:

```python
"role": "model_only",
"data_provider": "project_validated_in_memory",
"execution_engine": "project_standardized_ledger",
```

- [ ] **Step 4: Verify Qlib boundary GREEN**

```bash
python3 -m pytest -q tests/test_qlib_futures_backtest.py
```

Expected: finite predictions, fixed domain, model-only provenance, and
fail-closed dependency behavior all pass.

- [ ] **Step 5: Commit Qlib boundary**

```bash
git add code/qlib_model_adapter.py code/futures_research_backtest.py \
  tests/test_qlib_futures_backtest.py
git diff --cached --check
git commit -m "fix: make qlib model-only and fail closed"
```

### Task 5: Full verification and truthful smoke evidence

**Files:**

- Generate, do not commit: `data/reports/stock_contract_audit_20260817.json`
- Generate, do not commit: `data/reports/qlib_futures_15m_20260817_v4/`

**Interfaces:**

- Produces: final test evidence, read-only database audit, one stock proxy rejection/acceptance check, and one locked futures v4 report.
- Consumes: all previous tasks.

- [ ] **Step 1: Run the complete relevant suite**

```bash
python3 -m pytest -q \
  tests/test_data_contract.py \
  tests/test_data_engine.py \
  tests/test_backtest_integration.py \
  tests/test_backtest_metrics.py \
  tests/test_qlib_futures_backtest.py \
  tests/test_futures_research_backtest.py \
  tests/test_financial_truth.py \
  tests/test_web_validation.py \
  tests/test_legacy_ml_boundary.py
```

Expected: zero failures.

- [ ] **Step 2: Run the read-only production audit**

```bash
PYTHONPATH=code python3 -c 'import json; from data_contract import audit_database; print(json.dumps(audit_database("data/ashare_quant.db"), ensure_ascii=False, indent=2))' > data/reports/stock_contract_audit_20260817.json
```

Expected: the file reports mixed `_IDX` rows, uncataloged symbols, catalog
mismatches, and futures 5m quality counts; the SQLite database hash and bytes
remain unchanged.

- [ ] **Step 3: Run one fixed real futures research run**

```bash
python3 code/futures_research_backtest.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/qlib_futures_15m_20260817_v4 \
  --config-json '{"timeframe":"15m","model_backend":"qlib","min_symbols":12,"min_fold_rows":125}'
```

Expected: exit 0 only for accepted evidence or exit 2 for an evidence-complete
rejection. Do not retune after observing the result.

- [ ] **Step 4: Verify artifacts and immutability**

```bash
python3 -m json.tool data/reports/stock_contract_audit_20260817.json >/dev/null
python3 -m json.tool data/reports/qlib_futures_15m_20260817_v4/report.json >/dev/null
rg -n "RESEARCH_(ACCEPTED|REJECTED)|ADJUSTED_PROXY|RAW_EXECUTION|Qlib|model_only" \
  data/reports/qlib_futures_15m_20260817_v4/report.md \
  data/reports/qlib_futures_15m_20260817_v4/report.html
git diff --check
git status --short
```

Expected: valid reports, explicit semantics, no code diff, and generated
artifacts remain uncommitted.

- [ ] **Step 5: Run final tests after smoke runs**

```bash
python3 -m pytest -q \
  tests/test_data_contract.py tests/test_backtest_integration.py \
  tests/test_qlib_futures_backtest.py tests/test_futures_research_backtest.py \
  tests/test_web_validation.py
```

Expected: zero failures.
