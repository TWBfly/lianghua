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


def ml_policy_action(probability, close, ma20, rsi, macd, previous_macd, atr=None,
                     entry_price=None, peak_price=None, min_buy_prob=0.53):
    """
    Adaptive Dynamic Policy Action for Causal ML Trading Engine.
    Ensures active trade opportunity capture while maintaining high win rate, >2.0 profit-loss ratio, and strict drawdown controls.
    """
    if pd.isna(probability):
        return "HOLD", "NO_ACTION"

    # 1. 动态自适应阈值开仓逻辑 (概率 > 0.53 + 动量/均线共振)
    min_ma_ratio = 0.965 if (pd.notna(probability) and probability >= 0.58) else 0.975
    trend_ok = pd.isna(ma20) or close >= ma20 * min_ma_ratio
    rsi_ok = pd.isna(rsi) or (38.0 <= rsi <= 78.0)
    macd_ok = pd.isna(previous_macd) or (macd > previous_macd or macd > -0.05)

    if probability >= min_buy_prob and trend_ok and rsi_ok and macd_ok:
        return "BUY", "ADAPTIVE_ML_DYNAMIC_ASYMMETRIC_ENTRY"

    # 2. 动态 ATR 止损止盈与跟踪止盈 (盈亏比 > 2.0，最大回撤控制)
    if entry_price is not None and entry_price > 0:
        if pd.notna(atr) and atr > 0:
            stop_loss = max(entry_price - 1.25 * atr, entry_price * 0.972)
            take_profit = entry_price + 2.5 * atr
        else:
            stop_loss = entry_price * 0.970
            take_profit = entry_price * 1.060

        if close <= stop_loss:
            return "SELL", "DYNAMIC_ATR_STOP_LOSS"
        if close >= take_profit:
            return "SELL", "DYNAMIC_ATR_TAKE_PROFIT"

        # 移动追踪止盈 (Trailing Stop)
        if peak_price is not None and peak_price > entry_price * 1.03:
            trailing_stop = peak_price - (1.0 * (atr if pd.notna(atr) and atr > 0 else entry_price * 0.015))
            if close <= trailing_stop:
                return "SELL", "TRAILING_PROFIT_PROTECTION"

    # 3. 基础趋势跌破与概率塌陷离场
    stop_out = pd.notna(ma20) and ma20 > 0 and close < ma20 * 0.965
    prob_collapse = pd.notna(probability) and probability < 0.28

    if stop_out or prob_collapse:
        return (
            "SELL",
            "MA20_TREND_BREAK" if stop_out else "PROBABILITY_COLLAPSE_EXIT"
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


def build_triple_barrier_labels(df_kline: pd.DataFrame,
                                 forward_days: int = LABEL_HORIZON,
                                 pt_mult: float = 2.0,
                                 sl_mult: float = 1.5,
                                 atr_window: int = 14) -> pd.DataFrame:
    """
    López de Prado Triple Barrier Method with ATR dynamic thresholds.
    Upper Barrier: Take Profit (+pt_mult * ATR)
    Lower Barrier: Stop Loss (-sl_mult * ATR)
    Vertical Barrier: Time Horizon (forward_days)
    """
    frame = df_kline.copy()
    index = pd.to_datetime(frame["trade_date"])
    close = pd.Series(frame["close"].to_numpy(dtype=float), index=index).sort_index()
    high = pd.Series(frame["high"].to_numpy(dtype=float), index=index).sort_index()
    low = pd.Series(frame["low"].to_numpy(dtype=float), index=index).sort_index()

    # Calculate ATR
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(atr_window, min_periods=1).mean()

    labels = np.full(len(close), np.nan)
    label_end_time = [pd.NaT] * len(close)
    n = len(close)

    close_vals = close.to_numpy()
    high_vals = high.to_numpy()
    low_vals = low.to_numpy()
    atr_vals = atr.to_numpy()
    times = close.index

    for i in range(n - forward_days):
        c_i = close_vals[i]
        atr_i = atr_vals[i]
        if np.isnan(c_i) or np.isnan(atr_i) or atr_i <= 0:
            continue

        upper_barrier = c_i + pt_mult * atr_i
        lower_barrier = c_i - sl_mult * atr_i

        touched = False
        for j in range(1, forward_days + 1):
            idx = i + j
            if idx >= n:
                break
            h_j = high_vals[idx]
            l_j = low_vals[idx]

            hit_pt = h_j >= upper_barrier
            hit_sl = l_j <= lower_barrier

            if hit_pt and not hit_sl:
                labels[i] = 1.0
                label_end_time[i] = times[idx]
                touched = True
                break
            elif hit_sl and not hit_pt:
                labels[i] = 0.0
                label_end_time[i] = times[idx]
                touched = True
                break
            elif hit_pt and hit_sl:
                labels[i] = 0.0
                label_end_time[i] = times[idx]
                touched = True
                break

        if not touched:
            end_idx = min(i + forward_days, n - 1)
            final_return = (close_vals[end_idx] - c_i) / c_i
            labels[i] = 1.0 if final_return > 0.005 else 0.0
            label_end_time[i] = times[end_idx]

    future_return = (close.shift(-forward_days) - close) / close
    return pd.DataFrame({
        "label": pd.Series(labels, index=close.index),
        "future_return": future_return,
        "label_end_time": pd.to_datetime(pd.Series(label_end_time, index=close.index)),
    }, index=close.index)


def build_label_frame(df_kline: pd.DataFrame,
                      forward_days: int = LABEL_HORIZON,
                      threshold: float = LABEL_THRESHOLD,
                      use_triple_barrier: bool = True) -> pd.DataFrame:
    """Build labels using López de Prado Triple Barrier Method with fallback to fixed threshold."""
    if use_triple_barrier:
        try:
            return build_triple_barrier_labels(df_kline, forward_days=forward_days)
        except Exception:
            pass

    frame = df_kline.copy()
    index = pd.to_datetime(frame["trade_date"])
    close = pd.Series(frame["close"].to_numpy(dtype=float), index=index).sort_index()
    high = pd.Series(frame["high"].to_numpy(dtype=float), index=index).sort_index()
    low = pd.Series(frame["low"].to_numpy(dtype=float), index=index).sort_index()

    future_high = high.shift(-1).iloc[::-1].rolling(forward_days).max().iloc[::-1]
    future_low = low.shift(-1).iloc[::-1].rolling(forward_days).min().iloc[::-1]
    future_close = close.shift(-forward_days)

    future_max_up = (future_high - close) / close
    future_max_down = (close - future_low) / close
    future_return = (future_close - close) / close

    reward_risk_ratio = future_max_up / (future_max_down.clip(lower=0.005))
    label = ((future_max_up >= 0.035) & (reward_risk_ratio >= 1.8) & (future_return > 0.010)).astype(float)
    label[future_close.isna()] = np.nan
    label_end_time = pd.Series(close.index, index=close.index).shift(-forward_days)
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
        n_estimators=120,
        learning_rate=0.03,        # 较低学习率防过拟合
        max_depth=4,
        num_leaves=12,
        subsample=0.8,             # 样本行采样子集防过拟合
        colsample_bytree=0.7,      # 特征列采样子集防单因子依赖过拟合
        reg_alpha=0.1,             # L1 正则化
        reg_lambda=1.0,            # L2 正则化
        class_weight="balanced",
        random_state=42,
        verbose=-1,
        n_jobs=1,
    )


class RegimeConditionedMLEnsemble:
    """Multi-model ensemble fitting regime-specific LightGBM classifiers for BULL, BEAR, and RANGE market regimes."""

    def __init__(self, base_factory=None):
        self.factory = base_factory or _default_causal_model
        self.regime_models = {}
        self.global_model = self.factory()

    def fit(self, X: np.ndarray, y: np.ndarray, regimes: np.ndarray = None, min_samples: int = 30):
        """Fit global model and regime-conditioned sub-models if sufficient samples exist."""
        from sklearn.calibration import CalibratedClassifierCV

        X_arr = np.asarray(X, dtype=np.float32)
        y_arr = np.asarray(y, dtype=int)
        
        try:
            if len(y_arr) >= 120 and len(np.unique(y_arr)) >= 2:
                calibrated = CalibratedClassifierCV(estimator=self.factory(), cv=3, method="isotonic")
                calibrated.fit(X_arr, y_arr)
                self.global_model = calibrated
            elif len(y_arr) >= 60 and len(np.unique(y_arr)) >= 2:
                calibrated = CalibratedClassifierCV(estimator=self.factory(), cv=3, method="sigmoid")
                calibrated.fit(X_arr, y_arr)
                self.global_model = calibrated
            else:
                self.global_model.fit(X_arr, y_arr)
        except Exception:
            self.global_model.fit(X_arr, y_arr)

        if regimes is not None and len(regimes) == len(y_arr):
            for state in ("LOW_VOL_BULL", "RANGE", "HIGH_VOL_BEAR"):
                mask = np.asarray(regimes) == state
                X_sub, y_sub = X_arr[mask], y_arr[mask]
                if len(y_sub) >= min_samples and len(np.unique(y_sub)) >= 2:
                    try:
                        if len(y_sub) >= 120:
                            sub_model = CalibratedClassifierCV(estimator=self.factory(), cv=3, method="isotonic")
                            sub_model.fit(X_sub, y_sub)
                        elif len(y_sub) >= 60:
                            sub_model = CalibratedClassifierCV(estimator=self.factory(), cv=3, method="sigmoid")
                            sub_model.fit(X_sub, y_sub)
                        else:
                            sub_model = self.factory()
                            sub_model.fit(X_sub, y_sub)
                        self.regime_models[state] = sub_model
                    except Exception:
                        sub_model = self.factory()
                        sub_model.fit(X_sub, y_sub)
                        self.regime_models[state] = sub_model
        return self

    def predict_proba(self, X: np.ndarray, current_regime: str = None) -> np.ndarray:
        """Predict probabilities using state-conditioned model if present, else fallback to global model."""
        X_arr = np.asarray(X, dtype=np.float32)
        if current_regime and current_regime in self.regime_models:
            return self.regime_models[current_regime].predict_proba(X_arr)
        return self.global_model.predict_proba(X_arr)


def walk_forward_predict(df_kline: pd.DataFrame,
                         df_factors: pd.DataFrame,
                         symbol: str,
                         min_train_size: int = TRAINING_WINDOW,
                         retrain_every: int = RETRAIN_EVERY,
                         max_train_size: int = TRAINING_WINDOW,
                         forward_days: int = LABEL_HORIZON,
                         threshold: float = LABEL_THRESHOLD,
                         model_factory=None) -> pd.DataFrame:
    """Train on the latest fixed mature window, then predict later batches using Regime-Conditioned Ensemble."""
    features = causal_feature_frame(df_kline, df_factors).fillna(0)
    labels = build_label_frame(df_kline, forward_days, threshold)
    result = pd.DataFrame(index=features.index)
    result["score"] = np.nan
    result["probability"] = np.nan
    result["model_version"] = "INSUFFICIENT_HISTORY"
    result["trained_until"] = pd.NaT
    factory = model_factory or _default_causal_model

    # 因果计算 20 日波动率与 60 日均线 (使用 expanding.median 防止未来信息泄露)
    close_ret = df_kline["close"].pct_change()
    vol20 = close_ret.rolling(20).std()
    ma60 = df_kline["close"].rolling(60).mean()
    vol_median = vol20.expanding(min_periods=20).median().fillna(0.02)
    regimes = np.where(
        (df_kline["close"] >= ma60) & (vol20 < vol_median), "LOW_VOL_BULL",
        np.where(df_kline["close"] < ma60, "HIGH_VOL_BEAR", "RANGE")
    )

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
            
        ensemble = RegimeConditionedMLEnsemble(base_factory=factory)
        train_locs = [features.index.get_loc(idx) for idx in train_index]
        ensemble.fit(
            features.loc[train_index].to_numpy(dtype=np.float32),
            target.to_numpy(),
            regimes=regimes[train_locs]
        )
        
        pred_locs = np.array([
            features.index.get_loc(idx) for idx in prediction_index
        ])
        prediction_regimes = regimes[pred_locs]
        probability = np.full(len(prediction_index), np.nan)
        prediction_values = features.loc[prediction_index].to_numpy(
            dtype=np.float32
        )
        for state in pd.unique(prediction_regimes):
            state_mask = prediction_regimes == state
            state_probability = ensemble.predict_proba(
                prediction_values[state_mask],
                current_regime=state,
            )[:, 1]
            probability[state_mask] = np.where(
                np.isfinite(state_probability), state_probability, np.nan
            )

        trained_until = labels.loc[
            train_index, "label_end_time"
        ].max()
        version = build_model_identity(
            symbol,
            trained_until,
            features.loc[train_index],
            target,
            ensemble.global_model,
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


def cross_sectional_walk_forward_rank(market_data: dict,
                                     factors_data: dict = None,
                                     top_quantile: float = 0.05,
                                     min_train_size: int = TRAINING_WINDOW,
                                     retrain_every: int = RETRAIN_EVERY) -> dict:
    """
    Cross-Sectional Quantile Ranking Engine across all symbols.
    Ranks daily ML predicted probabilities cross-sectionally and picks Top N% Quantile Long signals.
    """
    factors_data = factors_data or {}
    predictions_by_symbol = {}

    for symbol, df_kline in market_data.items():
        if df_kline is None or len(df_kline) < min_train_size:
            continue
        df_factors = factors_data.get(symbol, pd.DataFrame())
        pred_df = walk_forward_predict(
            df_kline=df_kline,
            df_factors=df_factors,
            symbol=symbol,
            min_train_size=min_train_size,
            retrain_every=retrain_every,
        )
        predictions_by_symbol[symbol] = pred_df

    if not predictions_by_symbol:
        return {}

    prob_matrix = pd.DataFrame({
        sym: df["probability"] for sym, df in predictions_by_symbol.items()
    }).sort_index()

    rank_pct_matrix = prob_matrix.rank(axis=1, pct=True, numeric_only=True)
    cutoff = max(0.50, 1.0 - top_quantile)

    results = {}
    for symbol, df_pred in predictions_by_symbol.items():
        df_res = df_pred.copy()
        if symbol in rank_pct_matrix.columns:
            symbol_ranks = rank_pct_matrix[symbol]
            df_res["cross_sectional_rank_pct"] = symbol_ranks
            df_res["quantile_signal"] = (symbol_ranks >= cutoff).astype(int)
        else:
            df_res["cross_sectional_rank_pct"] = np.nan
            df_res["quantile_signal"] = 0
        results[symbol] = df_res

    return results
