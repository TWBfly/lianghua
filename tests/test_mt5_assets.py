from pathlib import Path


def test_importer_contract():
    source = Path("mt5/LianghuaImporter.mq5").read_text()
    assert '"CN_603986"' in source
    assert '"lianghua_603986_bars.csv"' in source
    assert "CustomSymbolCreate" in source
    assert "CustomRatesReplace" in source
    assert "CustomSymbolSetSessionTrade" in source
    assert "LIANGHUA_IMPORT_OK" in source

    config = Path("mt5/config/import.ini").read_text()
    assert "Script=LianghuaImporter" in config
    assert "ShutdownTerminal=1" in config


def test_supertrend_ea_contract():
    source = Path("mt5/LianghuaSupertrendEA.mq5").read_text()
    for token in (
        "InpAtrPeriod",
        "InpMultiplier",
        "CopyRates",
        "TesterWithdrawal",
        "LIANGHUA_TRADE",
        "lianghua_mt5_signals.csv",
    ):
        assert token in source

    config = Path("mt5/config/backtest.ini").read_text()
    assert "Symbol=CN_603986" in config
    assert "Model=2" in config
    assert "Deposit=1000000" in config


def test_runner_contract():
    source = Path("mt5/run_backtest.sh").read_text()
    for token in (
        "MetaEditor64.exe",
        "LianghuaImporter.mq5",
        "LianghuaSupertrendEA.mq5",
        "LIANGHUA_IMPORT_OK",
        "lianghua_603986_supertrend",
    ):
        assert token in source
