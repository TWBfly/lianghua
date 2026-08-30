import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (PROJECT_ROOT / "code", PROJECT_ROOT / "strategies"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np
import pandas as pd
import importlib.util

import autoquant_dual_agent_evolution_engine as engine
import autoquant_champion_strategy as champion


def market_frame(rows):
    close = 100.0 + np.arange(rows, dtype=float)
    return pd.DataFrame({
        "open": close - 0.2,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.full(rows, 10_000.0),
        "open_interest": np.full(rows, 5_000.0),
    })


def test_evolution_selects_on_train_and_blocks_negative_oos_export(monkeypatch):
    train = {"TRAIN": object()}
    oos = {"OOS": object()}
    seen = []
    reported = []
    exported = []

    monkeypatch.setattr(
        engine, "load_precomputed_market_data", lambda: (train, oos)
    )
    monkeypatch.setattr(
        engine,
        "compute_fast_fitness",
        lambda data, gene: (seen.append(data) or (1.0, 1.0, 1.0)),
    )
    monkeypatch.setattr(
        engine,
        "generate_champion_health_report",
        lambda gene, data: (
            reported.append(data)
            or {
                "oos_total_pnl": -1.0,
                "oos_total_trades": 1,
                "oos_3x_pnl": -2.0,
            }
        ),
    )
    monkeypatch.setattr(
        engine,
        "export_production_champion_strategy",
        lambda gene: exported.append(gene),
    )

    engine.run_autoquant_50_generations(pop_size=2, generations=1)

    assert seen and all(data is train for data in seen)
    assert reported == [oos]
    assert exported == []


def test_champion_features_are_prefix_invariant_during_warmup():
    short = market_frame(4)
    long = market_frame(10)

    pd.testing.assert_frame_equal(
        champion.calculate_factors(short),
        champion.calculate_factors(long).loc[short.index],
    )


def test_champion_oos_gate_requires_positive_stressed_result():
    assert engine.champion_passes_oos({
        "oos_total_pnl": 1.0,
        "oos_total_trades": 1,
        "oos_3x_pnl": -0.01,
        "prefix_invariance_pass": True,
    }) is False


def test_champion_oos_gate_requires_prefix_invariance_evidence():
    report = {
        "oos_total_pnl": 1.0,
        "oos_total_trades": 1,
        "oos_3x_pnl": 0.0,
    }

    assert engine.champion_passes_oos(report) is False
    assert engine.champion_passes_oos({
        **report,
        "prefix_invariance_pass": True,
    }) is True


def test_precomputed_features_produce_measured_prefix_evidence():
    data = {
        "AG_IDX": engine.SymbolPrecomputedData(
            market_frame(80), "AG_IDX"
        )
    }

    assert engine.prefix_invariance_passes(data) is True


def test_future_champion_exports_keep_causal_template(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "STRATEGIES_DIR", tmp_path)

    engine.export_production_champion_strategy(engine.AutoQuantGenome())

    source = (tmp_path / "autoquant_champion_strategy.py").read_text(
        encoding="utf-8"
    )
    assert ".bfill(" not in source
    compile(source, "autoquant_champion_strategy.py", "exec")


def test_evaluation_signals_match_exported_champion(tmp_path, monkeypatch):
    frame = market_frame(100)
    gene = engine.AutoQuantGenome()
    pdata = engine.SymbolPrecomputedData(frame, "AG_IDX")
    signals = engine.build_signal_arrays(pdata, gene)
    expected = np.where(
        signals["long"], 1, np.where(signals["short"], -1, 0)
    )

    monkeypatch.setattr(engine, "STRATEGIES_DIR", tmp_path)
    engine.export_production_champion_strategy(gene)
    path = tmp_path / "autoquant_champion_strategy.py"
    spec = importlib.util.spec_from_file_location("generated_champion", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    np.testing.assert_array_equal(
        module.calculate_signal(frame).to_numpy(), expected
    )
