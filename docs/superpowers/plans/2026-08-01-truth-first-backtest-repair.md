# Truth-First Backtest Repair Implementation Plan

> Implementation must be sequential and test-first. The project directory is
> not a Git repository, so each task ends with a test checkpoint instead of a
> commit.

**Goal:** Remove false success, fabricated data, causal strategy defects, and
optimistic evaluation from the current A-share research backtest while keeping
one execution ledger and an additive Web API.

**Architecture:** Keep SQLite, Pandas, `KLineBacktestEngine`, and
`simulate_portfolio`. Reuse the existing signal registry and simulator rather
than adding plugins, an event bus, or a second backtest engine. Strict mode
rejects the current adjusted-only dataset; research-proxy mode requires explicit
opt-in and reports its limitations.

**Tech stack:** Python 3, SQLite, Pandas, NumPy, scikit-learn, pytest, Flask,
vanilla JavaScript.

## Global Constraints

- Preserve existing successful response fields; additions may include status,
  mode, strategy, benchmark, and stable error codes.
- Do not import or ship Backtrader, vn.py, TA-Lib, or their source.
- Do not add a framework or dependency.
- Unknown provenance, point-in-time data, or model evidence never defaults to
  success.
- `simulate_portfolio` remains the only source of fills, costs, cash, T+1,
  limits, trades, and equity.
- Do not persist experiences or evolve models unless explicitly requested.

---

### Task 1: Truthful Data Synchronization And Schema Integrity

**Files:**
- Modify: `code/ashare_data_engine.py`
- Modify: `tests/test_data_engine.py`

- [ ] Add failing tests for an empty remote frame, a raised provider error, an
  already-current verified symbol, an already-covered uncataloged symbol, and
  preservation of the `stock_basic.symbol` primary key after refresh.

- [ ] Assert that `sync_stock_daily` returns this minimal structured shape:

```python
{
    "requested": 1,
    "committed": ["000001"],
    "unchanged": [],
    "empty": [],
    "failed": [],
}
```

Empty frames go to `empty`; exceptions go to `failed` with symbol and error;
neither increments `committed`. A covered symbol is `unchanged` only when its
catalog record matches the stored minimum date, maximum date, and row count.

- [ ] Run the focused tests and confirm RED:

```bash
pytest -q tests/test_data_engine.py
```

- [ ] Refactor the existing loop without adding a result class. Keep lists in a
  plain dictionary, move the success append inside the atomic transaction, and
  remove the unconditional success increment.

- [ ] Make `get_stock_daily_provenance` compare the catalog with actual stored
  rows and append `verification_status` as `VERIFIED` or `MISMATCH`.

- [ ] Replace `stock_basic.to_sql(if_exists="replace")` with transactional
  delete/insert. Add one targeted startup migration that recreates
  `stock_basic` only when `PRAGMA table_info` shows that `symbol` is not the
  primary key.

- [ ] Confirm GREEN and compile:

```bash
pytest -q tests/test_data_engine.py
python3 -m compileall -q code/ashare_data_engine.py tests/test_data_engine.py
```

---

### Task 2: Strict And Explicit Research-Proxy Backtests

**Files:**
- Modify: `code/backtest_kline_engine.py`
- Modify: `code/web_server.py`
- Modify: `tests/test_backtest_integration.py`
- Modify: `tests/test_web_validation.py`

- [ ] Add failing integration tests covering:
  - uncataloged data rejected by default with
    `UNVERIFIED_DATA_PROVENANCE`;
  - verified QFQ data rejected in strict mode with
    `RAW_EXECUTION_UNAVAILABLE`;
  - explicit `RESEARCH_PROXY` accepts QFQ and labels it
    `ADJUSTED_PROXY`;
  - uncataloged research data is labelled `LEGACY_UNVERIFIED`;
  - the same checks apply to every portfolio symbol.

- [ ] Add `backtest_mode` request validation with only `STRICT` and
  `RESEARCH_PROXY`; default to `STRICT`. Preserve the existing date, symbol, and
  capital validation.

- [ ] Replace `_data_provenance`'s inferred QFQ fallback with `price_mode:
  UNKNOWN`, `source: LEGACY_UNCATALOGED`, and `verification_status:
  UNVERIFIED`.

- [ ] Add one small provenance gate used by both single-stock and portfolio
  methods before decisions are built. Return the existing `error` field plus a
  stable `error_code`.

- [ ] Extend metadata with `backtest_mode`, `price_semantics`,
  `strategy_name`, `ai_used: false`, and
  `data_license_status: UNVERIFIED_FOR_COMMERCIAL_USE`.

- [ ] Confirm focused GREEN:

```bash
pytest -q tests/test_backtest_integration.py tests/test_web_validation.py
```

---

### Task 3: Correct The Shared A-Share Rule Helpers

**Files:**
- Modify: `code/portfolio_simulator.py`
- Modify: `tests/test_portfolio_simulator.py`

- [ ] Add failing boundary tests for:
  - `920` Beijing Stock Exchange 30% limit and one-share increments after the
    100-share minimum;
  - `689` STAR 20% limit and 200-share minimum;
  - `300`/`301` ST names retaining the post-reform 20% board limit;
  - ordinary main-board ST remaining 5%;
  - Shanghai/Shenzhen and Beijing transfer-fee rates immediately before and on
    2022-04-29;
  - the existing stamp-duty cutover remaining unchanged.

- [ ] Run and confirm RED:

```bash
pytest -q tests/test_portfolio_simulator.py
```

- [ ] Put board checks before the generic ST check in `_limit_fraction`, add
  `689` and `920`, and extend `_buy_quantity` for the Beijing minimum/increment.

- [ ] Add `_transfer_fee_rate(fees, symbol, date)` and use it in buy, sell, and
  fill component accounting. Keep the existing post-cutover rate and add only
  the two historical pre-cutover constants needed by current data.

- [ ] Do not invent IPO or historical ST state. Keep those limitations in
  metadata; strict execution remains blocked before simulation until those data
  exist.

- [ ] Confirm GREEN and one-cent ledger reconciliation:

```bash
pytest -q tests/test_portfolio_simulator.py tests/test_backtest_metrics.py
```

---

### Task 4: Make Mechanical Strategies Causal And Executable

**Files:**
- Modify: `code/strategy_signal_library.py`
- Modify: `code/backtest_kline_engine.py`
- Modify: `code/web_server.py`
- Create: `tests/test_strategy_signal_library.py`
- Modify: `tests/test_backtest_integration.py`
- Modify: `tests/test_web_validation.py`

- [ ] Create one synthetic OHLCV fixture and a parameterized test over every
  existing `SIGNAL_FUNCTIONS` item. Each function must run, return only
  `-1/0/1`, retain the input index, and be prefix invariant at several cutoffs.

- [ ] Add an integration test showing a named mechanical strategy creates
  dated decisions and its fills/trades come from `simulate_portfolio`. Add an
  invalid-strategy request test.

- [ ] Confirm RED:

```bash
pytest -q tests/test_strategy_signal_library.py tests/test_backtest_integration.py
```

- [ ] Delete the scalar `and` line in `supertrend_crossover`. Replace centered
  pivot windows with trailing confirmation windows so the pivot becomes known
  only after its right-hand bars exist. Apply the same confirmed-pivot rule to
  market structure.

- [ ] Remove `compute_all_signals`' exception-to-zero fallback. A broken
  registered strategy must fail its test and execution, not silently become
  HOLD.

- [ ] Reuse `SIGNAL_FUNCTIONS` as the mechanical registry. Add only
  `causal_ml` beside it; do not create a strategy class hierarchy.

- [ ] Extend `_build_symbol_run`, single-stock backtest, portfolio backtest, and
  request validation with `strategy="causal_ml"`. Mechanical `+1/-1/0` becomes
  BUY/SELL/HOLD with the same next-open simulator path. Preserve compatibility
  output while adding `strategy_name` to trades and metadata.

- [ ] Add a read-only `/api/strategies` endpoint sourced from the executable
  registry so the frontend never hardcodes an inflated count.

- [ ] Confirm GREEN:

```bash
pytest -q tests/test_strategy_signal_library.py tests/test_backtest_integration.py tests/test_web_validation.py
```

---

### Task 5: Remove Fabricated Fundamental Results

**Files:**
- Modify: `code/ashare_financial_fetcher.py`
- Modify: `code/munger_stock_screener.py`
- Modify: `code/web_server.py`
- Create: `tests/test_financial_truth.py`
- Modify: `tests/test_web_validation.py`

- [ ] Add failing tests proving that missing basics, missing statements, missing
  cash flow, missing ROE, and a database exception cannot produce `is_passed`
  or a positive quality score. Test SQL metacharacters as bound data.

- [ ] Replace the five-dimensional fabricated score with per-check `PASS`,
  `FAIL`, or `UNKNOWN`. Only stored PE/PB, reported revenue, and reported parent
  profit may be evaluated. Keep compatibility keys but set unavailable
  `quality_score`, `roe_est`, and `cfo_ratio` to `None`.

- [ ] Parameterize income-statement, notice, and basic-data reads. Do not fetch
  remote data while a caller supplied a database connection for a historical
  audit.

- [ ] Remove `pb / pe` ROE ranking from `munger_stock_screener` and
  `/api/munger_stocks`. Return a current valuation snapshot labelled
  `fundamental_status: UNKNOWN` instead of “wonderful company” claims.

- [ ] Confirm GREEN:

```bash
pytest -q tests/test_financial_truth.py tests/test_web_validation.py
```

---

### Task 6: Route ML Promotion Metrics Through The Simulator

**Files:**
- Modify: `code/ml_ensemble.py`
- Modify: `code/learning_loop.py`
- Modify: `code/backtest_kline_engine.py`
- Modify: `tests/test_learning_loop.py`
- Modify: `tests/test_backtest_integration.py`

- [ ] Add failing tests with synthetic bars showing that candidate evaluation:
  - equals simulator final equity after commissions, tax, transfer fees, and
    slippage;
  - cannot book a return when a limit-up bar prevents entry;
  - respects next-open execution, shared cash, and T+1;
  - refuses evaluation when market bars do not cover prediction dates.

- [ ] Extract the existing ML row decision rule into one pure helper in
  `ml_ensemble.py`; use it in both `_build_symbol_run` and evolution evaluation
  so thresholds and feature guards cannot diverge.

- [ ] Keep chronological folds and Brier score, but replace
  `position * (future_return - 0.0015)` with dated decisions passed to
  `simulate_portfolio`. Derive fold return, drawdown, and turnover from the
  simulation result.

- [ ] Pass the already-loaded per-symbol market frame through
  `_run_evolution -> run_after_backtest -> maybe_train/evaluate_shadow`.
  Insufficient aligned market data returns no challenger or promotion; it does
  not fall back to arithmetic returns.

- [ ] Confirm GREEN:

```bash
pytest -q tests/test_learning_loop.py tests/test_backtest_integration.py
```

---

### Task 7: Add Truthful Benchmark Comparison

**Files:**
- Modify: `code/backtest_kline_engine.py`
- Modify: `tests/test_backtest_integration.py`

- [ ] Add failing tests with `index_daily` rows for `000300` proving benchmark
  return uses the first and last common actual reporting dates and excess return
  equals portfolio return minus benchmark return.

- [ ] Add a missing-benchmark test expecting `status: UNKNOWN` and `None`
  numeric fields, never zero alpha.

- [ ] Implement one local helper in `backtest_kline_engine.py`; do not add a
  benchmark service. Append the benchmark object to single and portfolio metric
  output.

- [ ] Confirm GREEN:

```bash
pytest -q tests/test_backtest_integration.py
```

---

### Task 8: Remove False AI/UI Claims And Protect Mutation

**Files:**
- Modify: `code/deepseek_quant_copilot.py`
- Modify: `code/ashare_3d_fusion_engine.py`
- Modify: `code/web_server.py`
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `tests/test_web_validation.py`

- [ ] Add failing source and API tests proving:
  - AI errors never return the ML input as approved AI output;
  - the frontend contains no three-model, 330-strategy, automatic historical AI,
    fabricated ROE, moat, or five-dimension claim;
  - API-key write/check routes are absent;
  - data synchronization requires `LIANGHUA_ADMIN_TOKEN` using a bearer token;
  - empty, failed, partial, and unchanged sync summaries produce truthful HTTP
    status and messages.

- [ ] Make `DeepSeekQuantCopilot` return `UNAVAILABLE`/empty approval results on
  network, parsing, or grounding failure. Remove logs that claim notices were
  sent when only titles or no documents were supplied.

- [ ] Delete the unused browser API-key controls, JavaScript, Flask routes, and
  `.env` mutation import. Configuration remains environment-only.

- [ ] Protect `/api/sync_data` with `hmac.compare_digest` against
  `LIANGHUA_ADMIN_TOKEN`; fail closed when the token is absent. Validate the
  symbol and return the actual structured sync summary. Remove the public sync
  button because the browser has no admin secret.

- [ ] Add a native strategy `<select>` populated from `/api/strategies` and an
  unchecked research-proxy checkbox. Do not auto-run a proxy backtest on page
  load. Send the selected strategy and mode to both backtest endpoints and show
  fail-closed errors to the user.

- [ ] Rename AI-specific historical panels to strategy decision details and
  render the actual `strategy_name`, financial status, and `ai_used` metadata.

- [ ] Confirm GREEN and JavaScript syntax:

```bash
pytest -q tests/test_web_validation.py
node --check web/app.js
```

---

### Task 9: Full Regression And Real-Database Truth Check

**Files:**
- Modify only files required by a demonstrated failure.

- [ ] Run the complete suite and static checks:

```bash
pytest -q
python3 -m compileall -q code tests
node --check web/app.js
rg -n "backtrader|vnpy|talib" code web
```

The import scan must return no production runtime import. Documentation text is
outside this scan.

- [ ] Run one strict real-database backtest. With the current QFQ/uncataloged
  dataset, the expected result is a stable fail-closed error, not a fabricated
  success.

- [ ] Run the same symbol in explicit `RESEARCH_PROXY` mode. It must either
  return a reconciled result with `ADJUSTED_PROXY`/`LEGACY_UNVERIFIED` metadata
  or a specific data-quality error. Silent ML, AI, or rule fallback is a
  failure.

- [ ] Inspect the actual database schema and confirm `stock_basic.symbol` is a
  primary key and catalog verification matches stored row counts.

- [ ] Record the remaining release blockers in the final result: licensed
  point-in-time provider, corporate actions/raw execution, authenticated
  deployment, and real DL/DRL/document-grounded AI entry gates.
