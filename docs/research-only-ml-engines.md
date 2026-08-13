# Research-only invalidated ML engines

These modules are retained only for forensic review. Their reported results
failed the trusted simulator or temporal-validation contract and must not be
offered by `hot_plugger.get_executable_strategies()` or `/api/strategies`.

- `futures_ml_strategy_engine` — `RESEARCH_ONLY_INVALIDATED`
- `futures_self_evolving_holy_grail_engine` — `RESEARCH_ONLY_INVALIDATED`
- `futures_v14_complete_self_evolving_engine` — `RESEARCH_ONLY_INVALIDATED`
- `futures_v15_anti_degradation_engine` — `RESEARCH_ONLY_INVALIDATED`
- `multi_timeframe_benchmark_evaluator` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_ml_strategy` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_self_evolving_engine` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_hardcore_multi_tf` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_hardcore_stress_test` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_m5_runner` — `RESEARCH_ONLY_INVALIDATED`

Re-entry requires timestamp-aligned real market data, the shared execution
contract, causal validation, and reconciled fills, positions, cash, and PnL.
Historical JSON output is not evidence of validity.

## Audited offline research proxy

- `futures_research_backtest` — `AUDITED_RESEARCH_PROXY`

This module may run only as an offline weighted-index research backtest. It is
not an executable strategy, contract simulator, live-trading path, or evidence
of realizable futures PnL. Its own adversarial gates determine
`RESEARCH_ACCEPTED` or `RESEARCH_REJECTED` for each run.
