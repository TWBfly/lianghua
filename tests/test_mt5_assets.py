from pathlib import Path


def test_importer_contract():
    source = Path("mt5/LianghuaImporter.mq5").read_text()
    assert '"CN_603986"' in source
    assert '"lianghua_603986_bars.csv"' in source
    assert "CustomSymbolCreate" in source
    assert "CustomRatesReplace" in source
    assert "CustomSymbolSetSessionTrade" in source
    assert "LIANGHUA_IMPORT_OK" in source
    assert "property=%s error=%d" in source
    assert "24*60*60-1" in source

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
        "LianghuaImporter.ex5",
        "LianghuaSupertrendEA.ex5",
        "precompiled EX5",
        "wineserver",
        "LIANGHUA_IMPORT_OK",
        "import_mql.log",
        "lianghua_603986_supertrend",
    ):
        assert token in source
    assert "/compile:" not in source
    assert "/config:config\\lianghua_import.ini" in source
    assert "/config:config\\lianghua_backtest.ini" in source
    assert "/config:C:" not in source
    assert 'cd "$MT5_ROOT"' in source
    assert "-name '20*.log'" in source
    assert "testing of Experts\\\\LianghuaSupertrendEA\\.ex5 from" in source
    assert "MetaEditor64.exe" not in source
    assert "key code" not in source
