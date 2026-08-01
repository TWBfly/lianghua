"""Canonical validation for daily A-share bar frames."""

import numpy as np
import pandas as pd


REQUIRED_BAR_COLUMNS = (
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
)


class MarketDataError(ValueError):
    pass


def validate_daily_bars(frame: pd.DataFrame,
                        symbol: str | None = None) -> pd.DataFrame:
    missing = [
        column for column in REQUIRED_BAR_COLUMNS
        if column not in frame.columns
    ]
    if missing:
        raise MarketDataError(f"missing bar columns: {', '.join(missing)}")

    clean = frame.copy()
    numeric = ["open", "high", "low", "close", "volume", "amount"]
    try:
        clean["trade_date"] = pd.to_datetime(
            clean["trade_date"], errors="raise"
        )
        clean[numeric] = clean[numeric].apply(
            pd.to_numeric, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"invalid bar value: {exc}") from exc

    if clean["trade_date"].duplicated().any():
        raise MarketDataError("duplicate trade_date")
    if not np.isfinite(clean[numeric].to_numpy(dtype=float)).all():
        raise MarketDataError("non-finite bar value")
    if (clean[["open", "high", "low", "close"]] <= 0).any().any():
        raise MarketDataError("prices must be positive")
    if (clean[["volume", "amount"]] < 0).any().any():
        raise MarketDataError("volume and amount must be non-negative")
    if (
        (clean["low"] > clean[["open", "close"]].min(axis=1)).any()
        or (clean["high"] < clean[["open", "close"]].max(axis=1)).any()
        or (clean["low"] > clean["high"]).any()
    ):
        raise MarketDataError("invalid OHLC relationship")
    if symbol is not None and "symbol" in clean.columns:
        if set(clean["symbol"].astype(str)) != {str(symbol)}:
            raise MarketDataError("mixed or unexpected symbol")

    return clean.sort_values("trade_date").reset_index(drop=True)
