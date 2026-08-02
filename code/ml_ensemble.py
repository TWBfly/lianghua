"""Causal LightGBM features, labels, and walk-forward predictions."""

from dataclasses import dataclass
import hashlib
import json

import lightgbm as lgb
import numpy as np
import pandas as pd


TRAINING_WINDOW = 504
RETRAIN_EVERY = 21
LABEL_HORIZON = 5
LABEL_THRESHOLD = 0.015
HOLDOUT_SIZE = 252
MODEL_POLICY_VERSION = "fixed-window-walk-forward-v1"


def build_model_identity(symbol, trained_until, features, target,
                         model, policy):
    metadata = {
        "schema": MODEL_POLICY_VERSION,
        "symbol": str(symbol),
        "trained_until": pd.Timestamp(trained_until).isoformat(),
        "feature_names": list(features.columns),
        "model_class": (
            f"{model.__class__.__module__}.{model.__class__.__qualname__}"
        ),
        "model_params": model.get_params(deep=False),
        "policy": policy,
    }
    digest = hashlib.sha256(json.dumps(
        metadata,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode())
    digest.update(pd.util.hash_pandas_object(
        features, index=True,
    ).to_numpy().tobytes())
    digest.update(pd.util.hash_pandas_object(
        pd.Series(target, index=features.index), index=True,
    ).to_numpy().tobytes())
    return digest.hexdigest()[:16]


def ml_policy_action(probability, close, ma20, rsi, macd,
                     previous_macd):
    trend_safe = pd.notna(ma20) and close >= ma20 * 0.95
    macd_dead = (
        pd.notna(previous_macd)
        and macd < 0
        and previous_macd >= 0
    )
    if probability >= 0.55 and trend_safe and rsi < 75:
        return "BUY", "CAUSAL_ML_ENTRY"
    if probability < 0.38 or macd_dead:
        return (
            "SELL",
            "CAUSAL_ML_EXIT" if probability < 0.38
            else "MACD_DEATH_CROSS",
        )
    return "HOLD", "NO_ACTION"


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


def build_label_frame(df_kline: pd.DataFrame,
                      forward_days: int = LABEL_HORIZON,
                      threshold: float = LABEL_THRESHOLD) -> pd.DataFrame:
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


def build_labels(df_kline: pd.DataFrame,
                 forward_days: int = LABEL_HORIZON,
                 threshold: float = LABEL_THRESHOLD) -> pd.Series:
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
                        min_train_size: int = TRAINING_WINDOW,
                        retrain_every: int = RETRAIN_EVERY,
                        max_train_size: int = TRAINING_WINDOW) -> list:
    """Use only labels whose outcomes matured before prediction time."""
    if min_train_size < 1:
        raise ValueError("min_train_size must be positive")
    if retrain_every < 1:
        raise ValueError("retrain_every must be positive")
    if max_train_size < min_train_size:
        raise ValueError("max_train_size must be >= min_train_size")
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
        mature = mature.iloc[-max_train_size:]
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


def walk_forward_predict(df_kline: pd.DataFrame,
                         df_factors: pd.DataFrame,
                         symbol: str,
                         min_train_size: int = TRAINING_WINDOW,
                         retrain_every: int = RETRAIN_EVERY,
                         max_train_size: int = TRAINING_WINDOW,
                         forward_days: int = LABEL_HORIZON,
                         threshold: float = LABEL_THRESHOLD,
                         model_factory=None) -> pd.DataFrame:
    """Train on the latest fixed mature window, then predict later batches."""
    features = causal_feature_frame(df_kline, df_factors).fillna(0)
    labels = build_label_frame(df_kline, forward_days, threshold)
    result = pd.DataFrame(index=features.index)
    result["score"] = np.nan
    result["probability"] = np.nan
    result["model_version"] = "INSUFFICIENT_HISTORY"
    result["trained_until"] = pd.NaT
    factory = model_factory or _default_causal_model

    for split in walk_forward_splits(
        labels,
        features.index,
        min_train_size,
        retrain_every,
        max_train_size,
    ):
        train_index = split.train_index.intersection(features.index)
        target = labels.loc[train_index, "label"].astype(int)
        prediction_index = split.prediction_index.intersection(
            features.index
        )
        if target.nunique() < 2:
            result.loc[
                prediction_index, "model_version"
            ] = "INSUFFICIENT_CLASS_VARIATION"
            continue
        model = factory()
        model.fit(
            features.loc[train_index].to_numpy(dtype=np.float32),
            target.to_numpy(),
        )
        probability = model.predict_proba(
            features.loc[prediction_index].to_numpy(dtype=np.float32)
        )[:, 1]
        trained_until = labels.loc[
            train_index, "label_end_time"
        ].max()
        version = build_model_identity(
            symbol,
            trained_until,
            features.loc[train_index],
            target,
            model,
            {
                "training_window": max_train_size,
                "min_train_size": min_train_size,
                "retrain_every": retrain_every,
                "label_horizon": forward_days,
                "label_threshold": threshold,
            },
        )
        result.loc[prediction_index, "probability"] = probability
        result.loc[prediction_index, "score"] = probability * 10.0
        result.loc[prediction_index, "model_version"] = version
        result.loc[prediction_index, "trained_until"] = trained_until
    return result
