# Qlib 15m Futures Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the audited futures research pipeline on causally resampled 15-minute bars with Qlib LightGBM predictions and produce one self-contained HTML report.

**Architecture:** Keep `futures_research_backtest.py` as the sole owner of validation, temporal folds, attacks, gates, and the futures ledger. Add one small Qlib model adapter and parameterize the existing pipeline for `15m`; derive 15m bars from provenance-approved 5m rows so the run does not trust the unprovenanced 15m table. Extend the existing atomic report bundle with HTML rather than creating a second reporting path.

**Tech Stack:** Python 3.10, pandas, NumPy, Qlib `LGBModel`, LightGBM, SQLite, pytest, stdlib HTML/JSON.

## Global Constraints

- Treat `qlib/` as an unmodified upstream repository.
- Do not use modules listed as `RESEARCH_ONLY_INVALIDATED`.
- Use Qlib for dataset/model/prediction concerns only.
- Use the existing audited futures ledger for fills, short positions, fees, slippage, cash, and PnL.
- Label every artifact as an offline weighted-index research backtest.
- Fail closed and still emit HTML when dependencies, data, validation, reconciliation, or gates fail.
- Preserve the untracked Qlib repository and existing SQLite WAL/SHM files.

---

### Task 1: Add causal 15m input support

**Files:**

- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_futures_research_backtest.py`

**Interfaces:**

- Produces: `ResearchConfig.timeframe: str`, `_prepare_segmented_bars(bars, config) -> (segmented, quality)`, regular-frequency ledger validation.
- Consumes: provenance-approved 5m bars returned by `load_futures_bars()`.

- [ ] **Step 1: Write failing tests**

Add tests proving that `timeframe="15m"` resamples each already-segmented symbol independently, preserves source attributes, never crosses a 5m gap, and allows the shared ledger to consume a regular 15m trade path:

```python
def test_prepare_segmented_bars_resamples_canonical_5m_to_15m_without_crossing_gaps():
    bars = make_bars(12)
    bars.loc[6:, "trade_time"] += pd.Timedelta(minutes=5)
    bars.attrs["source_manifest"] = [{"symbol": "AG_IDX", "source_path": "x", "source_sha256": "a" * 64}]
    segmented, _ = research._prepare_segmented_bars(
        bars, ResearchConfig(timeframe="15m", min_symbol_rows=1, min_symbols=1)
    )
    assert set(segmented.groupby("segment_id").size()) == {2}
    assert segmented["trade_time"].diff().dropna().ne(pd.Timedelta(minutes=5)).all()
    assert segmented.attrs["source_manifest"] == bars.attrs["source_manifest"]

def test_standardized_ledger_accepts_regular_15m_paths():
    scored = make_scored_trade()
    base = scored["decision_time"].iloc[0]
    for column, offset in (("entry_time", 15), ("exit_time", 30)):
        scored[column] = base + pd.Timedelta(minutes=offset)
    market = make_mark_market(scored)
    market["trade_time"] = pd.date_range(base, periods=len(market), freq="15min")
    trades, daily = simulate_standardized_ledger(scored, market, 0.55, 5, 1)
    assert len(trades) == 1
    assert not daily.empty
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py -k 'prepare_segmented_bars or regular_15m_paths'
```

Expected: FAIL because `ResearchConfig.timeframe` and `_prepare_segmented_bars` do not exist and the ledger assumes five-minute spacing.

- [ ] **Step 3: Implement the minimum timeframe path**

Add `timeframe: str = "5m"` to `ResearchConfig`. Implement `_prepare_segmented_bars` by calling `validate_and_segment` on canonical 5m rows, then for `15m` grouping by `(symbol, segment_id)` and aggregating complete three-row windows only:

```python
def _prepare_segmented_bars(bars, config=ResearchConfig()):
    segmented, quality = validate_and_segment(bars, config)
    if config.timeframe == "5m":
        return segmented, quality
    if config.timeframe != "15m":
        raise ResearchRejected("timeframe must be 5m or 15m")
    rows = []
    for (_, segment_id), group in segmented.groupby(["symbol", "segment_id"], sort=False):
        group = group.sort_values("trade_time", kind="stable")
        for start in range(0, len(group) - 2, 3):
            window = group.iloc[start:start + 3]
            if window["trade_time"].diff().dropna().eq(pd.Timedelta(minutes=5)).all():
                rows.append(_aggregate_15m_window(window, segment_id))
    result = pd.DataFrame(rows)
    result.attrs = dict(bars.attrs)
    return result, quality
```

Change `_segment_arrays` to infer the segment's smallest positive interval and reject any larger internal jump, so existing 5m behavior remains unchanged and regular 15m paths work. Route both `run_research` and `run_prefix_attack` through `_prepare_segmented_bars`.

- [ ] **Step 4: Run focused and existing tests**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py -k 'prepare_segmented_bars or standardized_ledger or prefix'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git diff --check --cached
git commit -m "feat: support audited 15m futures research"
```

### Task 2: Route model fitting through Qlib

**Files:**

- Create: `code/qlib_model_adapter.py`
- Modify: `code/futures_research_backtest.py`
- Create: `tests/test_qlib_futures_backtest.py`

**Interfaces:**

- Produces: `fit_qlib_lightgbm(x_train, y_train, sample_weight, x_evaluation, seed) -> (probability, model)`.
- `model` exposes `get_params(deep=False)` for the existing audit identity.
- Consumes: local upstream checkout at `PROJECT_ROOT / "qlib"` and Qlib `LGBModel`.

- [ ] **Step 1: Write the failing adapter test**

```python
def test_qlib_backend_returns_index_aligned_finite_probabilities(monkeypatch):
    frame = make_model_dataset(80)
    train, evaluation = frame.iloc[:120], frame.iloc[120:]
    probability, model = qlib_adapter.fit_qlib_lightgbm(
        train[research.FEATURE_COLUMNS], train["label"],
        research.inverse_symbol_class_weights(train),
        evaluation[research.FEATURE_COLUMNS], 42,
    )
    assert probability.shape == (len(evaluation),)
    assert np.isfinite(probability).all()
    assert ((0 <= probability) & (probability <= 1)).all()
    assert model.get_params()["backend"] == "qlib.LGBModel"
```

- [ ] **Step 2: Run the test and confirm RED**

Run:

```bash
python3 -m pytest -q tests/test_qlib_futures_backtest.py
```

Expected: FAIL because `qlib_model_adapter` does not exist.

- [ ] **Step 3: Implement the Qlib adapter**

Create a minimal in-memory Dataset protocol accepted by `LGBModel`; MultiIndex columns must be `("feature", feature_name)` and `("label", "label")`. Supply aligned weights through a `Reweighter` subclass. Fit with deterministic constrained parameters and expose Qlib provenance:

```python
model = LGBModel(
    loss="binary", num_boost_round=100, early_stopping_rounds=10,
    learning_rate=0.03, max_depth=3, num_leaves=7,
    min_data_in_leaf=200, feature_fraction=0.8, bagging_fraction=0.8,
    bagging_freq=1, lambda_l1=1.0, lambda_l2=5.0,
    seed=seed, num_threads=1,
)
model.fit(dataset, reweighter=weights, verbose_eval=0)
probability = model.predict(dataset, segment="test").to_numpy(dtype=float)
```

Do not call `qlib.init()` because the adapter supplies an in-memory Dataset and needs no market provider.

- [ ] **Step 4: Add backend selection to the audited pipeline**

Add `model_backend: str = "native"` to `ResearchConfig`. For `qlib`, expose only `("qlib_lightgbm_constrained",)` as the selectable candidate domain and route `_fit_matrix` to `fit_qlib_lightgbm`; keep the existing three candidates untouched for `native`. Include `timeframe`, `model_backend`, Qlib version, and Qlib commit in provenance and report payloads.

- [ ] **Step 5: Install only the dependencies required by the local Qlib checkout**

Run the source import smoke check. If it reports missing packages, install the local project normally so versions come from `qlib/pyproject.toml`:

```bash
python3 -m pip install -e ./qlib
python3 -c "import sys; sys.path.insert(0, 'qlib'); from qlib.contrib.model.gbdt import LGBModel; print('Qlib import OK')"
```

Expected: `Qlib import OK`.

- [ ] **Step 6: Run tests and commit**

```bash
python3 -m pytest -q tests/test_qlib_futures_backtest.py tests/test_futures_research_backtest.py
git add code/qlib_model_adapter.py code/futures_research_backtest.py tests/test_qlib_futures_backtest.py
git diff --check --cached
git commit -m "feat: add qlib futures model backend"
```

Expected: PASS.

### Task 3: Add atomic HTML evidence and run the real backtest

**Files:**

- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_qlib_futures_backtest.py`
- Generate: `data/reports/qlib_futures_15m_20260817/report.html`

**Interfaces:**

- Produces: `report.html` inside the existing atomic evidence directory.
- Consumes: the exact reconciled JSON-safe result already used by Markdown/CSV reports.

- [ ] **Step 1: Write the failing HTML test**

```python
def test_report_bundle_contains_self_contained_html_for_rejection(tmp_path):
    result = research.rejected_result("run", ResearchConfig(timeframe="15m", model_backend="qlib"), "fixture")
    paths = research.write_report(result, tmp_path / "report")
    html = Path(paths["report.html"]).read_text(encoding="utf-8")
    assert "RESEARCH_REJECTED" in html
    assert research.DISCLAIMER in html
    assert "https://" not in html and "http://" not in html
    assert "Qlib" in html and "15m" in html
```

- [ ] **Step 2: Run the test and confirm RED**

```bash
python3 -m pytest -q tests/test_qlib_futures_backtest.py -k html
```

Expected: FAIL because `report.html` is not in `REPORT_FILES`.

- [ ] **Step 3: Implement one self-contained HTML renderer**

Add `report.html` to `REPORT_FILES`. Render escaped text and inline CSS/SVG only; include status, disclaimer, provenance, config, gate reasons, holdout metrics, equity/drawdown points, data quality, symbol metrics, and trades. Write it inside the existing temporary directory before `_reconcile_report`, and verify its status/disclaimer during reconciliation.

- [ ] **Step 4: Run all relevant verification**

```bash
python3 -m pytest -q tests/test_qlib_futures_backtest.py tests/test_futures_research_backtest.py
python3 -m pytest -q tests/test_legacy_ml_boundary.py tests/test_web_validation.py
```

Expected: PASS.

- [ ] **Step 5: Run the real 15m Qlib research backtest**

Use a new evidence directory so atomic reporting never overwrites prior evidence:

```bash
python3 code/futures_research_backtest.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/qlib_futures_15m_20260817 \
  --config-json '{"timeframe":"15m","model_backend":"qlib"}'
```

Expected: exit 0 for `RESEARCH_ACCEPTED` or exit 2 for an evidence-complete `RESEARCH_REJECTED`; both must produce `report.html`.

- [ ] **Step 6: Verify the generated evidence**

```bash
python3 -m json.tool data/reports/qlib_futures_15m_20260817/report.json >/dev/null
rg -n "RESEARCH_(ACCEPTED|REJECTED)|Qlib|15m|加权指数研究回测" data/reports/qlib_futures_15m_20260817/report.html
git diff --check
```

Expected: valid JSON, all four report markers present, and no whitespace errors.

- [ ] **Step 7: Commit code only**

```bash
git add code/futures_research_backtest.py tests/test_qlib_futures_backtest.py
git diff --check --cached
git commit -m "feat: generate qlib futures html evidence"
```

Do not commit generated reports, database WAL/SHM files, or the nested Qlib checkout.
