"""Causal LightGBM features, labels, and walk-forward predictions."""

from dataclasses import dataclass
import hashlib

import lightgbm as lgb
import numpy as np
import pandas as pd


def build_features(df_kline: pd.DataFrame,
                   df_factors: pd.DataFrame) -> pd.DataFrame:
    """Build features using only the current and earlier bars."""
    frame = df_kline.copy()
    frame.index = pd.to_datetime(frame["trade_date"])
    frame = frame.sort_index()
    features = pd.DataFrame(index=frame.index)

    for days in [1, 2, 3, 5, 10, 20]:
        features[f"ret_{days}d"] = frame["close"].pct_change(days)
    features["vol_ratio_5"] = (
        frame["volume"]
        / frame["volume"].rolling(5).mean().clip(lower=1)
    )
    features["vol_ratio_20"] = (
        frame["volume"]
        / frame["volume"].rolling(20).mean().clip(lower=1)
    )
    features["vol_trend"] = (
        frame["volume"].rolling(5).mean()
        / frame["volume"].rolling(20).mean().clip(lower=1)
    )
    features["volatility_5"] = frame["close"].pct_change().rolling(5).std()
    features["volatility_20"] = (
        frame["close"].pct_change().rolling(20).std()
    )
    features["high_low_ratio"] = (
        (frame["high"] - frame["low"])
        / frame["close"].clip(lower=0.01)
    )
    bar_range = frame["high"] - frame["low"] + 1e-8
    features["close_position"] = (
        frame["close"] - frame["low"]
    ) / bar_range
    features["body_ratio"] = (
        frame["close"] - frame["open"]
    ).abs() / bar_range
    features["upper_shadow"] = (
        frame["high"] - frame[["close", "open"]].max(axis=1)
    ) / bar_range
    features["lower_shadow"] = (
        frame[["close", "open"]].min(axis=1) - frame["low"]
    ) / bar_range
    for days in [5, 10, 20, 60]:
        average = frame["close"].rolling(days).mean()
        features[f"dist_ma{days}"] = (
            (frame["close"] - average) / average.clip(lower=0.01)
        )

    for column in ["rsi_14", "macd_hist", "bias_20"]:
        features[column] = (
            df_factors[column].reindex(frame.index)
            if column in df_factors.columns else 0.0
        )
    rsi = features["rsi_14"].fillna(50)
    features["rsi_change_3d"] = rsi.diff(3)
    features["rsi_dist_50"] = rsi - 50
    features["rsi_extreme"] = (
        (rsi < 30).astype(int) - (rsi > 70).astype(int)
    )
    macd = features["macd_hist"].fillna(0)
    features["macd_sign"] = np.sign(macd)
    features["macd_momentum"] = macd.diff(3)
    features["macd_golden"] = (
        (macd > 0) & (macd.shift(1) <= 0)
    ).astype(int)
    features["macd_dead"] = (
        (macd < 0) & (macd.shift(1) >= 0)
    ).astype(int)

    try:
        from tradingview_all_signals import TradingViewAllSignalsEngine

        signals = TradingViewAllSignalsEngine().generate_all_signals(frame)
        signals.index = frame.index
        for column in signals.columns:
            features[column] = signals[column]
    except Exception as exc:
        print(f"[ML] 策略信号计算异常: {exc}")
    return features.astype(np.float32)


def build_label_frame(df_kline: pd.DataFrame, forward_days: int = 5,
                      threshold: float = 0.015) -> pd.DataFrame:
    """Build labels whose unknown tail remains NaN."""
    frame = df_kline.copy()
    index = pd.to_datetime(frame["trade_date"])
    close = pd.Series(
        frame["close"].to_numpy(dtype=float), index=index
    ).sort_index()
    future_close = close.shift(-forward_days)
    future_return = future_close / close - 1.0
    label = (future_return > threshold).astype(float)
    label[future_close.isna()] = np.nan
    label_end_time = pd.Series(
        close.index, index=close.index
    ).shift(-forward_days)
    return pd.DataFrame({
        "label": label,
        "future_return": future_return,
        "label_end_time": pd.to_datetime(label_end_time),
    }, index=close.index)


def build_labels(df_kline: pd.DataFrame, forward_days: int = 5,
                 threshold: float = 0.015) -> pd.Series:
    return build_label_frame(
        df_kline, forward_days, threshold
    )["label"]


def causal_feature_frame(df_kline: pd.DataFrame,
                         df_factors: pd.DataFrame) -> pd.DataFrame:
    return build_features(df_kline, df_factors)


@dataclass(frozen=True)
class WalkForwardSplit:
    prediction_start: pd.Timestamp
    prediction_end: pd.Timestamp
    train_index: pd.DatetimeIndex
    prediction_index: pd.DatetimeIndex


def walk_forward_splits(label_frame: pd.DataFrame,
                        prediction_index: pd.DatetimeIndex,
                        min_train_size: int = 120,
                        retrain_every: int = 5) -> list:
    """Use only labels whose outcomes matured before prediction time."""
    dates = pd.DatetimeIndex(prediction_index).sort_values()
    splits = []
    for start in range(0, len(dates), retrain_every):
        prediction_dates = dates[start:start + retrain_every]
        if prediction_dates.empty:
            continue
        mature = label_frame[
            label_frame["label"].notna()
            & (
                label_frame["label_end_time"]
                < prediction_dates[0]
            )
        ]
        if len(mature) < min_train_size:
            continue
        splits.append(WalkForwardSplit(
            prediction_start=prediction_dates[0],
            prediction_end=prediction_dates[-1],
            train_index=pd.DatetimeIndex(mature.index),
            prediction_index=prediction_dates,
        ))
    return splits


def _default_causal_model():
    return lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
        n_jobs=1,
    )


def _rule_score(features: pd.DataFrame) -> pd.Series:
    rsi = features.get(
        "rsi_14", pd.Series(50, index=features.index)
    ).fillna(50)
    macd = features.get(
        "macd_hist", pd.Series(0, index=features.index)
    ).fillna(0)
    return ((50 - rsi) * 0.10 + macd * 2 + 5.0).clip(1.0, 9.5)


def walk_forward_predict(df_kline: pd.DataFrame,
                         df_factors: pd.DataFrame,
                         symbol: str,
                         min_train_size: int = 120,
                         retrain_every: int = 5,
                         model_factory=None) -> pd.DataFrame:
    """Train on expanding mature history, then predict later batches."""
    features = causal_feature_frame(df_kline, df_factors).fillna(0)
    labels = build_label_frame(df_kline)
    result = pd.DataFrame(index=features.index)
    result["score"] = np.nan
    result["probability"] = np.nan
    result["model_version"] = None
    result["trained_until"] = pd.NaT
    factory = model_factory or _default_causal_model

    for split in walk_forward_splits(
        labels,
        features.index,
        min_train_size,
        retrain_every,
    ):
        train_index = split.train_index.intersection(features.index)
        target = labels.loc[train_index, "label"].astype(int)
        if target.nunique() < 2:
            continue
        model = factory()
        model.fit(
            features.loc[train_index].to_numpy(dtype=np.float32),
            target.to_numpy(),
        )
        prediction_index = split.prediction_index.intersection(
            features.index
        )
        probability = model.predict_proba(
            features.loc[prediction_index].to_numpy(dtype=np.float32)
        )[:, 1]
        trained_until = labels.loc[
            train_index, "label_end_time"
        ].max()
        version = hashlib.sha256(
            (
                f"{symbol}|{trained_until.isoformat()}|"
                f"{','.join(features.columns)}"
            ).encode()
        ).hexdigest()[:16]
        result.loc[prediction_index, "probability"] = probability
        result.loc[prediction_index, "score"] = probability * 10.0
        result.loc[prediction_index, "model_version"] = version
        result.loc[prediction_index, "trained_until"] = trained_until

    fallback = _rule_score(features) / 10.0
    result["probability"] = result["probability"].fillna(fallback)
    result["score"] = result["score"].fillna(fallback * 10.0)
    result["model_version"] = result["model_version"].fillna(
        "causal-rule-v1"
    )
    return result
