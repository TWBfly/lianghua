# MT5 A-Share Backtest Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update 603986 daily data, import it as `CN_603986`, compile a native Supertrend EA, and complete a reproducible MT5 Strategy Tester run on macOS Wine.

**Architecture:** SQLite remains the source of truth. A small Python exporter creates validated MT5 bar and reference-signal CSV files; an MQL5 startup script imports the bars into a custom symbol; a native MQL5 EA calculates Supertrend and trades in the Strategy Tester. A shell runner deploys, compiles, imports, tests, and collects artifacts.

**Tech Stack:** Python 3, pandas, SQLite, AKShare, pytest, MQL5, MetaEditor/MetaTrader 5 under Wine, POSIX shell.

## Global Constraints

- Symbol: `603986`; MT5 symbol: `CN_603986`.
- Strategy: Supertrend with period `10` and multiplier `3.0`.
- Test range: `2024-01-01` through `2026-07-28` with CNY `1,000,000` initial capital.
- Signals use the closed D1 bar and execute on the next D1 open.
- Data is daily only; the result is not tick-accurate.
- Do not install or depend on the native macOS `MetaTrader5` Python package.
- Do not port LightGBM, HMM, the Web UI, portfolio mode, or the other strategies.
- Preserve unrelated worktree changes and keep generated reports out of Git.

## File Map

- Create `code/mt5_export.py`: validate SQLite bars, export MT5 rows, export Python reference directions, and optionally sync one symbol.
- Create `tests/test_mt5_export.py`: executable contract for bar validation, atomic export, and reference signals.
- Create `mt5/LianghuaImporter.mq5`: create/configure `CN_603986` and replace its custom M1 history from CSV.
- Create `mt5/LianghuaSupertrendEA.mq5`: native Supertrend, next-open trading, A-share fees, and signal audit CSV.
- Create `tests/test_mt5_assets.py`: source/config contract checks for the two MQL5 programs.
- Create `mt5/run_backtest.sh`: deploy, compile, run the importer and tester, and collect artifacts.
- Create `mt5/config/import.ini`: unattended startup-script configuration.
- Create `mt5/config/backtest.ini`: unattended Strategy Tester configuration.
- Modify `.gitignore`: ignore `mt5/exports/` and `mt5/results/`.

---

### Task 1: Validated SQLite-to-MT5 Export

**Files:**
- Create: `tests/test_mt5_export.py`
- Create: `code/mt5_export.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `validate_daily_bars(frame, symbol)` and `supertrend_signal(frame, period, multiplier)`.
- Produces: `load_bars(db_path, symbol, end_date) -> pd.DataFrame`, `export_symbol(db_path, symbol, output_dir, end_date) -> dict[str, object]`, and CSV files `lianghua_603986_bars.csv` and `lianghua_603986_signals.csv`.

- [ ] **Step 1: Write failing exporter tests**

Create a temporary SQLite database with `stock_daily`, insert three valid rows, and assert:

```python
def test_export_symbol_writes_mt5_bars_and_reference_signals(tmp_path):
    db_path = build_db(tmp_path)
    result = mt5_export.export_symbol(
        db_path, "603986", tmp_path / "out", "2026-07-28"
    )
    bars = pd.read_csv(result["bars_path"])
    signals = pd.read_csv(result["signals_path"])
    assert list(bars.columns) == [
        "Date", "Time", "Open", "High", "Low", "Close",
        "TickVolume", "Volume", "Spread",
    ]
    assert bars.iloc[0]["Date"] == "2026.07.24"
    assert bars.iloc[0]["Time"] == "09:30:00"
    assert signals.columns.tolist() == ["Date", "Direction"]
    assert result["row_count"] == 3


def test_export_symbol_rejects_invalid_ohlc_without_overwrite(tmp_path):
    db_path = build_db(tmp_path, high=8.0, close=10.0)
    output = tmp_path / "out"
    output.mkdir()
    old = output / "lianghua_603986_bars.csv"
    old.write_text("old", encoding="utf-8")
    with pytest.raises(MarketDataError):
        mt5_export.export_symbol(db_path, "603986", output, "2026-07-28")
    assert old.read_text(encoding="utf-8") == "old"
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `pytest -q tests/test_mt5_export.py`

Expected: collection fails because `mt5_export` does not exist.

- [ ] **Step 3: Implement the minimal exporter**

Implement `load_bars()` with a parameterized SQLite query ordered by date, validate using `validate_daily_bars`, and implement atomic CSV replacement:

```python
def _atomic_csv(frame, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(target)


def export_symbol(db_path, symbol, output_dir, end_date):
    bars = load_bars(db_path, symbol, end_date)
    mt5 = pd.DataFrame({
        "Date": bars["trade_date"].dt.strftime("%Y.%m.%d"),
        "Time": "09:30:00",
        "Open": bars["open"], "High": bars["high"],
        "Low": bars["low"], "Close": bars["close"],
        "TickVolume": bars["volume"].round().astype("int64").clip(lower=1),
        "Volume": bars["volume"].round().astype("int64").clip(lower=1),
        "Spread": 0,
    })
    signal_frame = bars.copy()
    signal_frame.index = pd.DatetimeIndex(bars["trade_date"])
    signals = pd.DataFrame({
        "Date": signal_frame.index.strftime("%Y.%m.%d"),
        "Direction": supertrend_signal(signal_frame, 10, 3.0).astype(int),
    })
    output = Path(output_dir)
    bars_path = output / f"lianghua_{symbol}_bars.csv"
    signals_path = output / f"lianghua_{symbol}_signals.csv"
    _atomic_csv(mt5, bars_path)
    _atomic_csv(signals, signals_path)
    return {"bars_path": bars_path, "signals_path": signals_path,
            "row_count": len(mt5), "first_date": mt5.iloc[0]["Date"],
            "last_date": mt5.iloc[-1]["Date"]}
```

The CLI accepts `--db`, `--symbol`, `--end-date`, `--output-dir`, and `--sync`. With `--sync`, call `AShareDataEngine(db_path).sync_stock_daily([symbol], end_date=current_day)` before exporting; if sync fails but the database still covers the requested end date, continue with existing validated data.

Add:

```gitignore
mt5/exports/
mt5/results/
```

- [ ] **Step 4: Run exporter tests and existing signal tests**

Run: `pytest -q tests/test_mt5_export.py tests/test_strategy_signal_library.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the exporter**

```bash
git add .gitignore code/mt5_export.py tests/test_mt5_export.py
git commit -m "feat: export validated A-share bars for MT5"
```

---

### Task 2: Custom Symbol Importer

**Files:**
- Create: `mt5/LianghuaImporter.mq5`
- Create: `mt5/config/import.ini`
- Create: `tests/test_mt5_assets.py`

**Interfaces:**
- Consumes: `MQL5/Files/lianghua_603986_bars.csv`.
- Produces: custom symbol `CN_603986` with M1 history and log marker `LIANGHUA_IMPORT_OK`.

- [ ] **Step 1: Write a failing asset-contract test**

```python
def test_importer_contract():
    source = Path("mt5/LianghuaImporter.mq5").read_text()
    assert '"CN_603986"' in source
    assert '"lianghua_603986_bars.csv"' in source
    assert "CustomSymbolCreate" in source
    assert "CustomRatesReplace" in source
    assert "LIANGHUA_IMPORT_OK" in source
```

- [ ] **Step 2: Run the contract test and confirm failure**

Run: `pytest -q tests/test_mt5_assets.py::test_importer_contract`

Expected: fail because the MQL5 source is absent.

- [ ] **Step 3: Implement the importer script**

`OnStart()` must:

```cpp
const string CUSTOM_SYMBOL="CN_603986";
const string CSV_FILE="lianghua_603986_bars.csv";

void OnStart()
  {
   bool is_custom=false;
   bool exists=SymbolExist(CUSTOM_SYMBOL,is_custom);
   if(exists && !is_custom)
     {
      Print("LIANGHUA_IMPORT_ERROR broker symbol collision");
      return;
     }
   if(!exists && !CustomSymbolCreate(CUSTOM_SYMBOL,"Lianghua"))
     {
      PrintFormat("LIANGHUA_IMPORT_ERROR create=%d",GetLastError());
      return;
     }
   CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_DIGITS,2);
   CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_CHART_MODE,SYMBOL_CHART_MODE_LAST);
   CustomSymbolSetInteger(CUSTOM_SYMBOL,SYMBOL_TRADE_CALC_MODE,SYMBOL_CALC_MODE_EXCH_STOCKS);
   CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_POINT,0.01);
   CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_TRADE_TICK_SIZE,0.01);
   CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_TRADE_TICK_VALUE,1.0);
   CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_TRADE_CONTRACT_SIZE,100.0);
   CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_VOLUME_MIN,1.0);
   CustomSymbolSetDouble(CUSTOM_SYMBOL,SYMBOL_VOLUME_STEP,1.0);
   CustomSymbolSetString(CUSTOM_SYMBOL,SYMBOL_CURRENCY_BASE,"CNY");
   CustomSymbolSetString(CUSTOM_SYMBOL,SYMBOL_CURRENCY_PROFIT,"CNY");
   CustomSymbolSetString(CUSTOM_SYMBOL,SYMBOL_CURRENCY_MARGIN,"CNY");
   // Read all CSV records into chronological MqlRates[], then replace history.
   int updated=CustomRatesReplace(CUSTOM_SYMBOL,0,LONG_MAX,rates);
   if(updated!=ArraySize(rates))
     {
      PrintFormat("LIANGHUA_IMPORT_ERROR updated=%d error=%d",updated,GetLastError());
      return;
     }
   SymbolSelect(CUSTOM_SYMBOL,true);
   PrintFormat("LIANGHUA_IMPORT_OK symbol=%s bars=%d first=%s last=%s",
               CUSTOM_SYMBOL,updated,TimeToString(rates[0].time),
               TimeToString(rates[updated-1].time));
  }
```

Read and discard the CSV header, reject malformed/non-positive OHLC, enforce `high >= open`, `high >= close`, `low <= open`, and `low <= close`, set `tick_volume >= 1`, and configure Monday-Friday quote/trade sessions for 09:30-11:30 and 13:00-15:00.

Create `mt5/config/import.ini`:

```ini
[Experts]
AllowLiveTrading=0
AllowDllImport=0
Enabled=1

[StartUp]
Script=LianghuaImporter
Symbol=EURUSD
Period=M1
ShutdownTerminal=1
```

- [ ] **Step 4: Run the source contract test**

Run: `pytest -q tests/test_mt5_assets.py::test_importer_contract`

Expected: pass.

- [ ] **Step 5: Commit the importer**

```bash
git add mt5/LianghuaImporter.mq5 mt5/config/import.ini tests/test_mt5_assets.py
git commit -m "feat: import A-share bars as an MT5 custom symbol"
```

---

### Task 3: Native Supertrend EA

**Files:**
- Create: `mt5/LianghuaSupertrendEA.mq5`
- Modify: `tests/test_mt5_assets.py`
- Create: `mt5/config/backtest.ini`

**Interfaces:**
- Consumes: D1 history of `CN_603986`.
- Produces: MT5 deals, fee withdrawals, `lianghua_mt5_signals.csv` in `FILE_COMMON`, and log markers `LIANGHUA_TRADE`/`LIANGHUA_TEST_DONE`.

- [ ] **Step 1: Add a failing EA contract test**

```python
def test_supertrend_ea_contract():
    source = Path("mt5/LianghuaSupertrendEA.mq5").read_text()
    for token in ("InpAtrPeriod", "InpMultiplier", "CopyRates",
                  "TesterWithdrawal", "LIANGHUA_TRADE",
                  "lianghua_mt5_signals.csv"):
        assert token in source
```

- [ ] **Step 2: Run the contract test and confirm failure**

Run: `pytest -q tests/test_mt5_assets.py::test_supertrend_ea_contract`

Expected: fail because the EA source is absent.

- [ ] **Step 3: Implement chronological Supertrend calculation**

Use `CopyRates(_Symbol, PERIOD_D1, 1, count, rates)` and chronological arrays. ATR must match pandas `ewm(alpha=1/period, adjust=False)`:

```cpp
double atr=0.0;
int direction=1;
for(int i=0;i<count;i++)
  {
   double previous_close=(i==0 ? rates[i].close : rates[i-1].close);
   double tr=MathMax(rates[i].high-rates[i].low,
                     MathMax(MathAbs(rates[i].high-previous_close),
                             MathAbs(rates[i].low-previous_close)));
   atr=(i==0 ? tr : atr+(tr-atr)/InpAtrPeriod);
   double upper=(rates[i].high+rates[i].low)/2.0+InpMultiplier*atr;
   double lower=(rates[i].high+rates[i].low)/2.0-InpMultiplier*atr;
   if(i>0)
     {
      if(!(lower>previous_lower || rates[i-1].close<previous_lower))
         lower=previous_lower;
      if(!(upper<previous_upper || rates[i-1].close>previous_upper))
         upper=previous_upper;
      if(direction==-1 && rates[i].close>previous_upper) direction=1;
      else if(direction==1 && rates[i].close<previous_lower) direction=-1;
     }
   previous_upper=upper;
   previous_lower=lower;
  }
```

Initialize the current D1 timestamp in `OnInit()` so the EA skips the first test-day open. On each later new D1 bar, record the previous bar date and direction. Buy only when direction is `1` and no position exists; close only when direction is `-1` and a position exists.

- [ ] **Step 4: Implement sizing and A-share cost withdrawals**

Calculate lots as:

```cpp
double budget=AccountInfoDouble(ACCOUNT_EQUITY)*InpTargetFraction;
double estimated=ask*(1.0+InpSlippageRate)*contract_size;
double lots=MathFloor((budget/estimated)/volume_step)*volume_step;
```

After a successful buy, withdraw `max(5, gross*0.00025) + gross*0.00001 + gross*0.001`. After a successful sell, additionally withdraw `gross*0.0005`. Call `TesterWithdrawal()` only when `MQLInfoInteger(MQL_TESTER)` is true, and fail the test pass with an explicit log message if withdrawal fails.

- [ ] **Step 5: Add unattended tester configuration**

Create `mt5/config/backtest.ini`:

```ini
[Tester]
Expert=LianghuaSupertrendEA
Symbol=CN_603986
Period=D1
Model=2
ExecutionMode=0
Optimization=0
FromDate=2024.01.01
ToDate=2026.07.28
Deposit=1000000
Currency=CNY
Leverage=1:1
UseLocal=1
UseRemote=0
UseCloud=0
Visual=0
Report=reports\lianghua_603986_supertrend
ReplaceReport=1
ShutdownTerminal=1
```

- [ ] **Step 6: Run asset tests**

Run: `pytest -q tests/test_mt5_assets.py`

Expected: all tests pass.

- [ ] **Step 7: Commit the EA**

```bash
git add mt5/LianghuaSupertrendEA.mq5 mt5/config/backtest.ini tests/test_mt5_assets.py
git commit -m "feat: add native MT5 Supertrend backtest EA"
```

---

### Task 4: Repeatable Wine Deployment and Test Runner

**Files:**
- Create: `mt5/run_backtest.sh`
- Modify: `tests/test_mt5_assets.py`

**Interfaces:**
- Consumes: exporter CLI, both `.mq5` files, both `.ini` files, installed MT5 Wine prefix.
- Produces: compile logs, terminal/tester logs, report HTML, MT5 signal CSV, and a zero/non-zero exit status.

- [ ] **Step 1: Add a failing runner contract test**

```python
def test_runner_contract():
    source = Path("mt5/run_backtest.sh").read_text()
    for token in ("MetaEditor64.exe", "LianghuaImporter.mq5",
                  "LianghuaSupertrendEA.mq5", "LIANGHUA_IMPORT_OK",
                  "lianghua_603986_supertrend"):
        assert token in source
```

- [ ] **Step 2: Run the test and confirm failure**

Run: `pytest -q tests/test_mt5_assets.py::test_runner_contract`

Expected: fail because the runner is absent.

- [ ] **Step 3: Implement the shell runner**

The runner must use fixed, quoted paths under:

```sh
MT5_PREFIX="/Users/tang/Library/Application Support/net.metaquotes.wine.metatrader5"
MT5_ROOT="$MT5_PREFIX/drive_c/Program Files/MetaTrader 5"
WINE="/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine"
```

It must:

1. run `python3 code/mt5_export.py --sync ...`;
2. copy importer/EA/config/CSV into the matching MT5 directories;
3. compile both sources with `MetaEditor64.exe /compile:... /log:...`;
4. decode UTF-16LE logs and require `0 errors`;
5. stop the currently open terminal gracefully before command-line starts;
6. start `terminal64.exe /portable /config:...import.ini` and require `LIANGHUA_IMPORT_OK` in the decoded terminal log;
7. start `terminal64.exe /portable /config:...backtest.ini` and require the HTML report plus at least one `LIANGHUA_TRADE` marker;
8. copy all evidence to `mt5/results/` and reopen `/Applications/MetaTrader 5.app`.

Use `trap` to reopen MT5 on failure. Do not delete user files or kill unrelated Wine applications.

- [ ] **Step 4: Run shell syntax and contract checks**

Run: `zsh -n mt5/run_backtest.sh && pytest -q tests/test_mt5_assets.py`

Expected: exit zero and all tests pass.

- [ ] **Step 5: Commit the runner**

```bash
git add mt5/run_backtest.sh tests/test_mt5_assets.py
git commit -m "feat: automate MT5 Wine backtest execution"
```

---

### Task 5: Deploy, Run, and Verify

**Files:**
- Generated: `mt5/exports/*`
- Generated: `mt5/results/*`

**Interfaces:**
- Consumes: all earlier task outputs.
- Produces: verified MT5 report and Python/MT5 signal comparison.

- [ ] **Step 1: Run the full Python test suite before external deployment**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Execute the automated backtest runner**

Run: `zsh mt5/run_backtest.sh`

Expected: exporter summary, two zero-error compile summaries, `LIANGHUA_IMPORT_OK`, at least one `LIANGHUA_TRADE`, and a saved HTML report.

- [ ] **Step 3: Compare Python and MT5 signal CSV files**

Run:

```bash
python3 -c "import pandas as pd; p=pd.read_csv('mt5/exports/lianghua_603986_signals.csv'); m=pd.read_csv('mt5/results/lianghua_mt5_signals.csv'); j=p.merge(m,on='Date',suffixes=('_python','_mt5')); bad=j[j.Direction_python!=j.Direction_mt5]; changes=j[j.Direction_python.ne(j.Direction_python.shift())]; print({'rows':len(j),'mismatches':len(bad),'first_change':changes.Date.iloc[0],'last_change':changes.Date.iloc[-1]}); assert bad.empty"
```

Expected: mismatch count `0`.

- [ ] **Step 4: Inspect the MT5 report and logs**

Verify:

- test dates are `2024.01.01` to `2026.07.28`;
- deposit is CNY `1,000,000`;
- symbol is `CN_603986`, D1, open-price model;
- at least one completed deal exists;
- no `LIANGHUA_*_ERROR`, compiler error, or tester fatal error appears.

- [ ] **Step 5: Run final repository verification**

Run: `git status --short && pytest -q`

Expected: only ignored generated artifacts are absent from status and all tests pass.

- [ ] **Step 6: Commit any verification-only tracked adjustment**

If no tracked adjustment was required, do not create an empty commit. If a source/config correction was required, stage only that correction and commit with a specific `fix:` message, then rerun Steps 1–5.
