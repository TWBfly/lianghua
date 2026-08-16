# Qlib 15m Futures Backtest Design

## Goal

Run the current audited futures ML research path on 15-minute bars, use Qlib
for causal model training and prediction, and produce one self-contained HTML
backtest report.

## Boundary

- Treat `qlib/` as an unmodified upstream repository.
- Do not use modules listed as `RESEARCH_ONLY_INVALIDATED`.
- Use Qlib for dataset/model/prediction concerns only.
- Use the existing audited futures ledger for fills, short positions, fees,
  slippage, contract multipliers, cash, and PnL.
- Label the result as an offline weighted-index research backtest, not live or
  realizable contract performance.

## Flow

1. Load canonical `15m` weighted-index rows and metadata from
   `data/ashare_quant.db`.
2. Reuse the causal feature, temporal split, purge, quality, and adversarial
   gates from `futures_research_backtest.py`.
3. Train and predict through Qlib's LightGBM model interface without copying or
   modifying Qlib source.
4. Feed only out-of-sample predictions into the audited futures ledger.
5. Write one offline HTML artifact containing provenance, acceptance status,
   data quality, model/fold details, portfolio metrics, equity/drawdown charts,
   per-symbol results, and trades.

## Failure Rules

- Fail closed if Qlib dependencies, canonical metadata, sufficient 15m bars,
  temporal validation, reconciliation, or adversarial gates are unavailable.
- A rejected run still produces HTML explaining every rejection reason.
- Never silently fall back to an invalidated engine or a stock-style Qlib
  executor.

## Verification

- One small test proves Qlib predictions enter the existing ledger and that an
  accepted or rejected HTML report is always written.
- Run the focused test, the existing futures research tests, and one real-data
  15m smoke backtest before reporting completion.
