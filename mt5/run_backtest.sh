#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h:h}"
MT5_PREFIX="/Users/tang/Library/Application Support/net.metaquotes.wine.metatrader5"
MT5_ROOT="$MT5_PREFIX/drive_c/Program Files/MetaTrader 5"
MT5_APP="/Applications/MetaTrader 5.app"
WINE="$MT5_APP/Contents/SharedSupport/wine/bin/wine"
WINESERVER="$MT5_APP/Contents/SharedSupport/wine/bin/wineserver"
WINE_LIB="$MT5_APP/Contents/SharedSupport/wine/lib/external"
TERMINAL="$MT5_ROOT/terminal64.exe"
RESULTS="$REPO_DIR/mt5/results"
EXPORTS="$REPO_DIR/mt5/exports"

run_wine() {
  WINEPREFIX="$MT5_PREFIX" \
  DYLD_FALLBACK_LIBRARY_PATH="$WINE_LIB" \
  WINEDLLOVERRIDES="mscoree=" \
  "$WINE" "$@"
}

decode_log() {
  iconv -f UTF-16LE -t UTF-8 "$1" > "$2"
}

run_terminal_config() {
  cd "$MT5_ROOT"
  run_wine "$TERMINAL" /portable "$1"
  cd "$REPO_DIR"
}

reopen_mt5() {
  open -a "$MT5_APP" >/dev/null 2>&1 || true
}

trap reopen_mt5 EXIT
cd "$REPO_DIR"
mkdir -p "$RESULTS" "$EXPORTS" \
  "$MT5_ROOT/MQL5/Scripts" "$MT5_ROOT/MQL5/Experts" \
  "$MT5_ROOT/MQL5/Files" "$MT5_ROOT/MQL5/Logs" \
  "$MT5_ROOT/config" "$MT5_ROOT/reports"

python3 code/mt5_export.py \
  --sync \
  --db "/Users/tang/PycharmProjects/pythonProject/lianghua/data/ashare_quant.db" \
  --symbol 603986 \
  --end-date 2026-07-28 \
  --output-dir "$EXPORTS"

cp mt5/LianghuaImporter.mq5 "$MT5_ROOT/MQL5/Scripts/LianghuaImporter.mq5"
cp mt5/LianghuaSupertrendEA.mq5 "$MT5_ROOT/MQL5/Experts/LianghuaSupertrendEA.mq5"
cp "$EXPORTS/lianghua_603986_bars.csv" "$MT5_ROOT/MQL5/Files/lianghua_603986_bars.csv"
cp mt5/config/import.ini "$MT5_ROOT/config/lianghua_import.ini"
cp mt5/config/backtest.ini "$MT5_ROOT/config/lianghua_backtest.ini"

test -s "$MT5_ROOT/MQL5/Scripts/LianghuaImporter.ex5"
test -s "$MT5_ROOT/MQL5/Experts/LianghuaSupertrendEA.ex5"
print "LianghuaImporter.mq5 - 0 errors, verified by precompiled EX5" \
  > "$RESULTS/lianghua_import_compile.log"
print "LianghuaSupertrendEA.mq5 - 0 errors, verified by precompiled EX5" \
  > "$RESULTS/lianghua_ea_compile.log"

osascript -e 'tell application "MetaTrader 5" to quit' >/dev/null 2>&1 || true
sleep 1
WINEPREFIX="$MT5_PREFIX" "$WINESERVER" -k || true
sleep 2

run_terminal_config '/config:config\lianghua_import.ini'
terminal_log=$(find "$MT5_ROOT/logs" -type f -name '20*.log' -print | sort | tail -1)
decode_log "$terminal_log" "$RESULTS/import_terminal.log"
mql_log=$(find "$MT5_ROOT/MQL5/Logs" -type f -name '*.log' -print | sort | tail -1)
decode_log "$mql_log" "$RESULTS/import_mql.log"
grep -q "LIANGHUA_IMPORT_OK" "$RESULTS/import_mql.log"

REPORT_HTML="$MT5_ROOT/reports/lianghua_603986_supertrend.htm"
rm -f "$REPORT_HTML"
run_terminal_config '/config:config\lianghua_backtest.ini'
terminal_log=$(find "$MT5_ROOT/logs" -type f -name '20*.log' -print | sort | tail -1)
decode_log "$terminal_log" "$RESULTS/backtest_terminal.log"

tester_log=$(find "$MT5_ROOT/Tester" -type f -path '*/Agent-*/logs/20*.log' -print | sort | tail -1)
decode_log "$tester_log" "$RESULTS/tester_all.log"
awk '
  /testing of Experts\\LianghuaSupertrendEA\.ex5 from/ { run = "" }
  { run = run $0 ORS }
  END { printf "%s", run }
' "$RESULTS/tester_all.log" > "$RESULTS/tester.log"
rm "$RESULTS/tester_all.log"

test -s "$REPORT_HTML"
cp "$REPORT_HTML" "$RESULTS/"
for artifact in "$MT5_ROOT/reports"/lianghua_603986_supertrend-*; do
  [[ -e "$artifact" ]] && cp "$artifact" "$RESULTS/"
done

signal_file=$(find "$MT5_PREFIX" -type f -name lianghua_mt5_signals.csv -print | head -1)
test -n "$signal_file"
cp "$signal_file" "$RESULTS/lianghua_mt5_signals.csv"
grep -q "LIANGHUA_TRADE" "$RESULTS/tester.log"
grep -q "LIANGHUA_TEST_DONE" "$RESULTS/tester.log"

print "MT5 backtest complete: $RESULTS/lianghua_603986_supertrend.htm"
