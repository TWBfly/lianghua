"""
rsi_bollinger_combo.py — RSI 与布林带动量突破热插拔策略
"""
import pandas as pd

STRATEGY_NAME = "rsi_bollinger_combo"
STRATEGY_DESCRIPTION = "RSI + 布林带上轨突破强力热插拔策略"

def calculate_signal(df: pd.DataFrame) -> pd.Series:
    close = df['close']
    
    # 布林带 (20, 2)
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    upper = ma20 + 2.0 * std20
    lower = ma20 - 2.0 * std20
    
    # RSI (14)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-6)
    rsi = 100 - (100 / (1 + rs))
    
    # 信号逻辑: 突破布林带上轨且 RSI > 55 时触发买入；跌破中轨或 RSI < 45 时卖出
    buy = (close > upper) & (rsi > 55)
    sell = (close < ma20) | (rsi < 45)
    
    signal = pd.Series(0, index=df.index)
    signal[buy] = 1
    signal[sell] = -1
    return signal
