"""Causal market-level Gaussian HMM regime filtering."""

import hashlib
import json

import numpy as np
import pandas as pd


INDEX_CODE = "000300"
N_STATES = 3
TRAINING_WINDOW = 504
RETRAIN_EVERY = 21
POLICY_VERSION = "hmm-market-regime-v1"
STATE_COLUMNS = {
    "LOW_VOL_BULL": "p_low_vol_bull",
    "RANGE": "p_range",
    "HIGH_VOL_BEAR": "p_high_vol_bear",
}


def build_regime_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Build prefix-invariant market observations from index closes."""
    clean = frame.copy()
    clean.index = pd.to_datetime(clean["trade_date"])
    clean = clean.sort_index()
    close = pd.Series(
        clean["close"].to_numpy(dtype=float), index=clean.index
    )
    log_return = np.log(close / close.shift(1))
    volatility = log_return.rolling(20).std(ddof=0)
    return pd.DataFrame({
        "log_return": log_return,
        "realized_volatility_20": volatility,
        "trend_strength_20": (
            log_return.rolling(20).mean()
            / volatility.replace(0, np.nan)
        ),
    }, index=clean.index)


def state_names_from_means(means: np.ndarray) -> dict[int, str]:
    """Assign stable economic names to permutation-invariant state ids."""
    values = np.asarray(means, dtype=float)
    if values.shape != (N_STATES, 3):
        raise ValueError("expected three HMM states and three observations")
    order = np.argsort(values[:, 2])
    return {
        int(order[0]): "HIGH_VOL_BEAR",
        int(order[1]): "RANGE",
        int(order[2]): "LOW_VOL_BULL",
    }


def _default_model():
    from hmmlearn.hmm import GaussianHMM

    return GaussianHMM(
        n_components=N_STATES,
        covariance_type="diag",
        n_iter=200,
        random_state=42,
    )


def _diagonal_covariances(model) -> np.ndarray:
    covariances = np.asarray(model.covars_, dtype=float)
    if covariances.ndim == 3:
        covariances = np.diagonal(
            covariances, axis1=1, axis2=2
        )
    if covariances.shape != (N_STATES, 3):
        raise ValueError("expected diagonal covariance per HMM state")
    return np.clip(covariances, 1e-9, None)


def _log_emission(values, means, covariances):
    difference = values[:, None, :] - means[None, :, :]
    return -0.5 * np.sum(
        np.log(2 * np.pi * covariances)[None, :, :]
        + difference * difference / covariances[None, :, :],
        axis=2,
    )


def _normalized(log_values):
    maximum = np.max(log_values)
    weights = np.exp(log_values - maximum)
    total = weights.sum()
    if not np.isfinite(total) or total <= 0:
        raise ValueError("non-finite HMM probability")
    return weights / total


def _forward(start_probability, transition, log_emissions):
    start = np.clip(np.asarray(start_probability, dtype=float), 1e-300, None)
    alpha = _normalized(np.log(start) + log_emissions[0])
    probabilities = [alpha]
    for emission in log_emissions[1:]:
        prior = np.clip(alpha @ transition, 1e-300, None)
        alpha = _normalized(np.log(prior) + emission)
        probabilities.append(alpha)
    return np.asarray(probabilities)


def _empty_regimes(index):
    result = pd.DataFrame(index=pd.DatetimeIndex(index))
    result["state"] = None
    for column in STATE_COLUMNS.values():
        result[column] = np.nan
    result["status"] = "REGIME_DATA_UNAVAILABLE"
    result["trained_until"] = pd.NaT
    result["model_version"] = None
    return result


def _model_version(trained_until, training, model):
    digest = hashlib.sha256(json.dumps({
        "policy": POLICY_VERSION,
        "trained_until": pd.Timestamp(trained_until).isoformat(),
        "start": np.asarray(model.startprob_).tolist(),
        "transition": np.asarray(model.transmat_).tolist(),
        "means": np.asarray(model.means_).tolist(),
        "covariances": _diagonal_covariances(model).tolist(),
    }, sort_keys=True, separators=(",", ":")).encode())
    digest.update(np.asarray(training, dtype=np.float64).tobytes())
    return f"{POLICY_VERSION}:{digest.hexdigest()[:16]}"


def walk_forward_regimes(
        frame: pd.DataFrame,
        model_factory=None,
        training_window: int = TRAINING_WINDOW,
        retrain_every: int = RETRAIN_EVERY) -> pd.DataFrame:
    """Fit on prior windows and forward-filter each later prediction batch."""
    if training_window < 1:
        raise ValueError("training_window must be positive")
    if retrain_every < 1:
        raise ValueError("retrain_every must be positive")
    try:
        observations = build_regime_observations(frame)
    except (KeyError, TypeError, ValueError):
        index = pd.to_datetime(
            frame.get("trade_date", pd.Series(dtype="datetime64[ns]"))
        )
        return _empty_regimes(index)

    result = _empty_regimes(observations.index)
    valid = observations.dropna()
    result.loc[valid.index, "status"] = "INSUFFICIENT_HISTORY"
    fits = []
    factory = model_factory or _default_model

    for start in range(0, len(valid), retrain_every):
        prediction = valid.iloc[start:start + retrain_every]
        if prediction.empty:
            continue
        training = valid.loc[valid.index < prediction.index[0]].tail(
            training_window
        )
        if len(training) < training_window:
            continue
        mean = training.mean()
        std = training.std(ddof=0)
        if (std <= 0).any() or not np.isfinite(std).all():
            result.loc[
                prediction.index, "status"
            ] = "REGIME_MODEL_UNAVAILABLE"
            continue
        normalized_training = (
            (training - mean) / std
        ).to_numpy(dtype=float)
        normalized_prediction = (
            (prediction - mean) / std
        ).to_numpy(dtype=float)
        try:
            model = factory().fit(normalized_training)
            monitor = getattr(model, "monitor_", None)
            if monitor is not None and not monitor.converged:
                raise ValueError("HMM did not converge")
            means = np.asarray(model.means_, dtype=float)
            covariances = _diagonal_covariances(model)
            transition = np.asarray(model.transmat_, dtype=float)
            train_alpha = _forward(
                model.startprob_,
                transition,
                _log_emission(
                    normalized_training, means, covariances
                ),
            )
            if (train_alpha.sum(axis=0) <= 1e-6).any():
                raise ValueError("empty effective HMM state")
            batch_alpha = _forward(
                train_alpha[-1] @ transition,
                transition,
                _log_emission(
                    normalized_prediction, means, covariances
                ),
            )
            names = state_names_from_means(means)
            trained_until = training.index[-1]
            version = _model_version(
                trained_until, normalized_training, model
            )
        except ImportError:
            result.loc[
                prediction.index, "status"
            ] = "REGIME_DEPENDENCY_UNAVAILABLE"
            continue
        except Exception:
            result.loc[
                prediction.index, "status"
            ] = "REGIME_MODEL_UNAVAILABLE"
            continue

        for position, date in enumerate(prediction.index):
            probabilities = batch_alpha[position]
            raw_state = int(np.argmax(probabilities))
            result.at[date, "state"] = names[raw_state]
            for state_id, name in names.items():
                result.at[
                    date, STATE_COLUMNS[name]
                ] = probabilities[state_id]
            result.at[date, "status"] = "AVAILABLE"
            result.at[date, "trained_until"] = trained_until
            result.at[date, "model_version"] = version
        fits.append({
            "prediction_start": prediction.index[0].isoformat(),
            "prediction_end": prediction.index[-1].isoformat(),
            "trained_until": trained_until.isoformat(),
            "model_version": version,
            "state_names": names,
            "start_probability": np.asarray(
                model.startprob_
            ).tolist(),
            "transition_matrix": transition.tolist(),
            "means": means.tolist(),
            "covariances": covariances.tolist(),
        })
    result.attrs["fits"] = fits
    return result


def _optional_float(value):
    return float(value) if pd.notna(value) else None


def apply_regime_overlay(action: str, reason: str,
                         target_fraction: float, regime_row):
    """Apply the fixed entry policy while always preserving exits."""
    if regime_row is None:
        return action, reason, target_fraction, {}
    state = regime_row.get("state")
    status = str(regime_row.get("status", "REGIME_DATA_UNAVAILABLE"))
    trained_until = regime_row.get("trained_until")
    features = {
        "market_regime": state if pd.notna(state) else None,
        "market_regime_status": status,
        "p_low_vol_bull": _optional_float(
            regime_row.get("p_low_vol_bull")
        ),
        "p_range": _optional_float(regime_row.get("p_range")),
        "p_high_vol_bear": _optional_float(
            regime_row.get("p_high_vol_bear")
        ),
        "regime_model_version": regime_row.get("model_version"),
        "regime_trained_until": (
            pd.Timestamp(trained_until).isoformat()
            if pd.notna(trained_until) else None
        ),
        "base_target_fraction": float(target_fraction),
        "regime_target_fraction": float(target_fraction),
    }
    if action != "BUY":
        return action, reason, target_fraction, features
    if status != "AVAILABLE" or state not in STATE_COLUMNS:
        features["regime_target_fraction"] = 0.0
        return "HOLD", "REGIME_UNAVAILABLE", 0.0, features
    if state == "HIGH_VOL_BEAR":
        features["regime_target_fraction"] = 0.0
        return "HOLD", "REGIME_HIGH_VOL_BEAR", 0.0, features
    if state == "RANGE":
        scaled = float(target_fraction) * 0.5
        features["regime_target_fraction"] = scaled
        return "BUY", f"{reason}|REGIME_RANGE_HALF", scaled, features
    return action, reason, target_fraction, features
