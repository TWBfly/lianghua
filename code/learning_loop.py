"""SQLite-backed trading experience and model evolution state."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import joblib
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit


@dataclass(frozen=True)
class EvaluationMetrics:
    net_return: float
    max_drawdown: float
    turnover: float
    brier_score: float
    folds: int
    hit_kill_switch: bool = False
    evaluated_samples: int = 0
    window_metrics: tuple = ()

    def as_dict(self):
        return asdict(self)


class PromotionGate:
    def passes(self, challenger, champion):
        reasons = []
        if challenger.folds < 3:
            reasons.append("INSUFFICIENT_FOLDS")
        if challenger.hit_kill_switch:
            reasons.append("KILL_SWITCH")
        if challenger.net_return <= champion.net_return:
            reasons.append("RETURN_NOT_IMPROVED")
        if challenger.max_drawdown > champion.max_drawdown:
            reasons.append("DRAWDOWN_WORSE")
        if challenger.turnover > champion.turnover * 1.10:
            reasons.append("TURNOVER_TOO_HIGH")
        if challenger.brier_score > champion.brier_score:
            reasons.append("CALIBRATION_WORSE")
        if (
            challenger.window_metrics
            and len(challenger.window_metrics)
            == len(champion.window_metrics)
        ):
            for window, (candidate, baseline) in enumerate(
                zip(
                    challenger.window_metrics,
                    champion.window_metrics,
                ),
                1,
            ):
                prefix = f"WINDOW_{window}_"
                if candidate["net_return"] <= baseline["net_return"]:
                    reasons.append(prefix + "RETURN_NOT_IMPROVED")
                if candidate["max_drawdown"] > baseline["max_drawdown"]:
                    reasons.append(prefix + "DRAWDOWN_WORSE")
                if candidate["turnover"] > baseline["turnover"] * 1.10:
                    reasons.append(prefix + "TURNOVER_TOO_HIGH")
                if candidate["brier_score"] > baseline["brier_score"]:
                    reasons.append(prefix + "CALIBRATION_WORSE")
        return not reasons, reasons

    @staticmethod
    def passes_baseline(candidate):
        reasons = []
        if candidate.folds < 3:
            reasons.append("INSUFFICIENT_FOLDS")
        if candidate.hit_kill_switch:
            reasons.append("KILL_SWITCH")
        if candidate.net_return <= 0:
            reasons.append("NON_POSITIVE_RETURN")
        if candidate.max_drawdown >= 0.10:
            reasons.append("DRAWDOWN_LIMIT")
        if candidate.turnover > 0.50:
            reasons.append("TURNOVER_TOO_HIGH")
        if candidate.brier_score > 0.25:
            reasons.append("CALIBRATION_UNSTABLE")
        for window, metrics in enumerate(
            candidate.window_metrics, 1
        ):
            prefix = f"WINDOW_{window}_"
            if metrics["net_return"] <= 0:
                reasons.append(prefix + "NON_POSITIVE_RETURN")
            if metrics["max_drawdown"] >= 0.10:
                reasons.append(prefix + "DRAWDOWN_LIMIT")
            if metrics["turnover"] > 0.50:
                reasons.append(prefix + "TURNOVER_TOO_HIGH")
            if metrics["brier_score"] > 0.25:
                reasons.append(prefix + "CALIBRATION_UNSTABLE")
        return not reasons, reasons


def evaluate_predictions(horizon_returns, probabilities, folds=3,
                         horizon_bars=5):
    """Evaluate a long-only probability policy across chronological folds."""
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be positive")
    frame = pd.DataFrame({
        "return": pd.Series(horizon_returns, dtype=float),
        "probability": pd.Series(probabilities, dtype=float),
    }).dropna().sort_index().iloc[::horizon_bars]
    if len(frame) < folds or folds < 1:
        raise ValueError("not enough rows for requested folds")

    fold_metrics = []
    for indices in np.array_split(np.arange(len(frame)), folds):
        fold = frame.iloc[indices]
        label = (fold["return"] > 0.015).astype(float)
        position = (fold["probability"] >= 0.55).astype(float)
        policy_return = position * (fold["return"] - 0.0015)
        equity = (1.0 + policy_return).cumprod()
        peak = equity.cummax()
        drawdown = ((peak - equity) / peak).max()
        fold_metrics.append({
            "net_return": float(equity.iloc[-1] - 1.0),
            "max_drawdown": float(drawdown),
            "turnover": float(position.diff().abs().fillna(position).mean()),
            "brier_score": float(
                ((fold["probability"] - label) ** 2).mean()
            ),
        })

    compounded = float(np.prod([
        1.0 + item["net_return"] for item in fold_metrics
    ]) - 1.0)
    max_drawdown = max(item["max_drawdown"] for item in fold_metrics)
    return EvaluationMetrics(
        net_return=compounded,
        max_drawdown=max_drawdown,
        turnover=float(np.mean([
            item["turnover"] for item in fold_metrics
        ])),
        brier_score=float(np.mean([
            item["brier_score"] for item in fold_metrics
        ])),
        folds=len(fold_metrics),
        hit_kill_switch=max_drawdown >= 0.10,
        evaluated_samples=len(frame),
        window_metrics=tuple(fold_metrics),
    )


class ModelRegistry:
    STATUSES = {"CHALLENGER", "SHADOW", "CHAMPION", "RETIRED"}

    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS model_versions (
                    version TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trained_until TEXT,
                    data_hash TEXT,
                    feature_hash TEXT,
                    artifact_path TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    shadow_metrics_json TEXT,
                    shadow_samples INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    promoted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_model_symbol_status
                ON model_versions(symbol, status, created_at);
            """)
            columns = {
                row["name"] for row in conn.execute(
                    "PRAGMA table_info(model_versions)"
                )
            }
            if "shadow_metrics_json" not in columns:
                conn.execute(
                    "ALTER TABLE model_versions "
                    "ADD COLUMN shadow_metrics_json TEXT"
                )

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def register(self, version, symbol, status, metrics, artifact_path,
                 trained_until=None, data_hash="", feature_hash=""):
        if status not in self.STATUSES:
            raise ValueError(f"invalid model status: {status}")
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO model_versions (
                    version, symbol, status, trained_until,
                    data_hash, feature_hash, artifact_path, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version) DO NOTHING
            """, (
                str(version),
                str(symbol),
                status,
                str(trained_until) if trained_until else None,
                str(data_hash),
                str(feature_hash),
                str(artifact_path),
                json.dumps(metrics, sort_keys=True),
            ))

    def get(self, version):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_versions WHERE version=?",
                (str(version),),
            ).fetchone()
        return dict(row) if row else None

    def champion(self, symbol):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT * FROM model_versions
                WHERE symbol=? AND status='CHAMPION'
                ORDER BY promoted_at DESC, created_at DESC
                LIMIT 1
            """, (str(symbol),)).fetchone()
        return dict(row) if row else None

    def shadow(self, symbol):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT * FROM model_versions
                WHERE symbol=? AND status='SHADOW'
                ORDER BY created_at DESC
                LIMIT 1
            """, (str(symbol),)).fetchone()
        return dict(row) if row else None

    def add_shadow_samples(self, version, count=1):
        with self._connect() as conn:
            conn.execute("""
                UPDATE model_versions
                SET shadow_samples=shadow_samples + ?
                WHERE version=? AND status='SHADOW'
            """, (int(count), str(version)))

    def record_shadow_metrics(self, version, metrics, sample_count):
        with self._connect() as conn:
            conn.execute("""
                UPDATE model_versions
                SET shadow_metrics_json=?, shadow_samples=?
                WHERE version=? AND status='SHADOW'
            """, (
                json.dumps(metrics, sort_keys=True),
                int(sample_count),
                str(version),
            ))

    def set_status(self, version, status):
        if status not in self.STATUSES:
            raise ValueError(f"invalid model status: {status}")
        with self._connect() as conn:
            conn.execute(
                "UPDATE model_versions SET status=? WHERE version=?",
                (status, str(version)),
            )

    def promote(self, version, min_shadow_samples=50):
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                candidate = conn.execute("""
                    SELECT symbol, status, shadow_samples
                    FROM model_versions WHERE version=?
                """, (str(version),)).fetchone()
                if (
                    candidate is None
                    or candidate["status"] != "SHADOW"
                    or candidate["shadow_samples"] < min_shadow_samples
                ):
                    conn.rollback()
                    return False
                conn.execute("""
                    UPDATE model_versions
                    SET status='RETIRED'
                    WHERE symbol=? AND status='CHAMPION'
                """, (candidate["symbol"],))
                conn.execute("""
                    UPDATE model_versions
                    SET status='CHAMPION',
                        promoted_at=CURRENT_TIMESTAMP
                    WHERE version=?
                """, (str(version),))
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise


class ExperienceStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS experiences (
                    decision_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    decision_time TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    feature_hash TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    action TEXT NOT NULL,
                    desired_shares INTEGER NOT NULL DEFAULT 0,
                    order_status TEXT NOT NULL,
                    rejection_reason TEXT,
                    fill_time TEXT,
                    fill_price REAL,
                    fees REAL,
                    exit_time TEXT,
                    exit_price REAL,
                    horizon_return REAL,
                    horizon_end_time TEXT,
                    trade_return REAL,
                    mfe REAL,
                    mae REAL,
                    reward REAL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_experience_symbol_completed
                ON experiences(symbol, completed, decision_time);
                CREATE INDEX IF NOT EXISTS idx_experience_run
                ON experiences(run_id, decision_time);
                CREATE TABLE IF NOT EXISTS training_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    trained_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_training_symbol_time
                ON training_events(symbol, trained_at);
            """)
            columns = {
                row[1] for row in conn.execute(
                    "PRAGMA table_info(experiences)"
                )
            }
            if "horizon_end_time" not in columns:
                conn.execute(
                    "ALTER TABLE experiences "
                    "ADD COLUMN horizon_end_time TEXT"
                )

    def record_decision(self, decision):
        features_json = json.dumps(
            decision.get("features", {}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        feature_hash = hashlib.sha256(features_json.encode()).hexdigest()
        action = str(decision["action"]).upper()
        order_status = "NONE" if action == "HOLD" else "PENDING"
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO experiences (
                    decision_id, run_id, decision_time, symbol,
                    features_json, feature_hash, model_version, action,
                    desired_shares, order_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id) DO NOTHING
            """, (
                str(decision["decision_id"]),
                str(decision["run_id"]),
                str(decision["decision_time"]),
                str(decision["symbol"]),
                features_json,
                feature_hash,
                str(decision["model_version"]),
                action,
                int(decision.get("desired_shares", 0) or 0),
                order_status,
            ))

    def get(self, decision_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM experiences WHERE decision_id=?",
                (str(decision_id),),
            ).fetchone()
        return dict(row) if row else None

    def record_order_result(self, decision_id, status,
                            fill_time=None, fill_price=None,
                            fees=None, rejection_reason=None):
        if status not in {"FILLED", "REJECTED"}:
            raise ValueError("status must be FILLED or REJECTED")
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE experiences
                SET order_status=?, rejection_reason=?,
                    fill_time=?, fill_price=?, fees=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE decision_id=?
            """, (
                status,
                rejection_reason,
                str(fill_time) if fill_time is not None else None,
                float(fill_price) if fill_price is not None else None,
                float(fees) if fees is not None else None,
                str(decision_id),
            ))
            if cursor.rowcount == 0:
                raise KeyError(decision_id)

    def complete_horizon(self, decision_id, horizon_return, mfe, mae,
                         horizon_end_time=None):
        row = self.get(decision_id)
        if row is None:
            raise KeyError(decision_id)
        no_trade = row["action"] != "BUY" or row["order_status"] == "REJECTED"
        with self._connect() as conn:
            conn.execute("""
                UPDATE experiences
                SET horizon_return=?, horizon_end_time=?, mfe=?, mae=?,
                    reward=CASE WHEN ? THEN ? ELSE reward END,
                    completed=CASE WHEN ? THEN 1 ELSE completed END,
                    updated_at=CURRENT_TIMESTAMP
                WHERE decision_id=?
            """, (
                float(horizon_return),
                (
                    str(horizon_end_time)
                    if horizon_end_time is not None else None
                ),
                float(mfe),
                float(mae),
                int(no_trade),
                float(horizon_return),
                int(no_trade),
                str(decision_id),
            ))

    def complete_trade(self, decision_id, trade_return,
                       exit_time, exit_price):
        row = self.get(decision_id)
        if row is None:
            raise KeyError(decision_id)
        mae = abs(float(row["mae"] or 0.0))
        reward = float(trade_return) - 0.25 * mae
        with self._connect() as conn:
            conn.execute("""
                UPDATE experiences
                SET trade_return=?, exit_time=?, exit_price=?,
                    reward=?, completed=1,
                    updated_at=CURRENT_TIMESTAMP
                WHERE decision_id=?
            """, (
                float(trade_return),
                str(exit_time),
                float(exit_price),
                reward,
                str(decision_id),
            ))

    def record_training(self, symbol, model_version, trained_at):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO training_events (
                    symbol, model_version, trained_at
                ) VALUES (?, ?, ?)
            """, (
                str(symbol),
                str(model_version),
                trained_at.isoformat(),
            ))

    def completed_since(self, symbol, since=None):
        sql = """
            SELECT COUNT(*) FROM experiences
            WHERE symbol=? AND completed=1
                  AND horizon_end_time IS NOT NULL
        """
        params = [str(symbol)]
        if since is not None:
            sql += " AND horizon_end_time > ?"
            params.append(since.isoformat())
        with self._connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def retrain_due(self, symbol, now, completed_threshold=50,
                    interval_days=7):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT trained_at FROM training_events
                WHERE symbol=?
                ORDER BY trained_at DESC LIMIT 1
            """, (str(symbol),)).fetchone()
        last_trained = (
            datetime.fromisoformat(row["trained_at"])
            if row else None
        )
        new_completed = self.completed_since(symbol, last_trained)
        if new_completed >= completed_threshold:
            return True
        return bool(
            last_trained
            and new_completed > 0
            and (now - last_trained).days >= interval_days
        )

    def completed_frame(self, symbol):
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT decision_id, decision_time, features_json,
                       horizon_return, horizon_end_time
                FROM experiences
                WHERE symbol=? AND completed=1
                      AND horizon_return IS NOT NULL
                      AND horizon_end_time IS NOT NULL
                ORDER BY decision_time, decision_id
            """, (str(symbol),)).fetchall()
        if not rows:
            return pd.DataFrame()
        records = []
        for row in rows:
            item = json.loads(row["features_json"])
            item.update({
                "decision_id": row["decision_id"],
                "decision_time": pd.Timestamp(row["decision_time"]),
                "horizon_return": float(row["horizon_return"]),
                "horizon_end_time": pd.Timestamp(row["horizon_end_time"]),
            })
            records.append(item)
        return pd.DataFrame(records).set_index("decision_time").sort_index()


class EvolutionManager:
    def __init__(self, store, registry, model_dir, model_factory=None):
        self.store = store
        self.registry = registry
        self.model_dir = Path(model_dir).resolve()
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.model_factory = model_factory or self._default_model
        self.gate = PromotionGate()

    @staticmethod
    def _default_model():
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

    def maybe_train(self, symbol, now):
        if self.registry.shadow(symbol):
            return None
        if not self.store.retrain_due(symbol, now):
            return None
        frame = self.store.completed_frame(symbol)
        if len(frame) < 120:
            return None

        excluded = {
            "decision_id", "horizon_return", "horizon_end_time",
        }
        feature_names = sorted(
            column for column in frame.columns if column not in excluded
        )
        if not feature_names:
            return None
        features = frame[feature_names].apply(
            pd.to_numeric, errors="coerce"
        ).fillna(0.0)
        target = (frame["horizon_return"] > 0.015).astype(int)
        if target.nunique() < 2:
            return None

        probabilities = pd.Series(np.nan, index=frame.index, dtype=float)
        valid_folds = 0
        for train_index, validation_index in TimeSeriesSplit(
                n_splits=3, gap=5).split(features):
            y_train = target.iloc[train_index]
            if y_train.nunique() < 2:
                continue
            model = self.model_factory()
            model.fit(features.iloc[train_index], y_train)
            probabilities.iloc[validation_index] = model.predict_proba(
                features.iloc[validation_index]
            )[:, 1]
            valid_folds += 1
        valid = probabilities.notna()
        if valid_folds < 3 or valid.sum() < 3:
            return None

        candidate_metrics = evaluate_predictions(
            frame.loc[valid, "horizon_return"],
            probabilities.loc[valid],
            folds=3,
        )
        final_model = self.model_factory()
        final_model.fit(features, target)

        feature_hash = hashlib.sha256(
            ",".join(feature_names).encode()
        ).hexdigest()
        data_hash = hashlib.sha256(
            "|".join(
                f"{row.decision_id}:{row.horizon_return:.12f}"
                for row in frame[["decision_id", "horizon_return"]].itertuples()
            ).encode()
        ).hexdigest()
        trained_until = pd.to_datetime(frame["horizon_end_time"]).max()
        version = hashlib.sha256(
            f"{symbol}|{trained_until.isoformat()}|{data_hash}|{feature_hash}".encode()
        ).hexdigest()[:16]
        symbol_dir = (self.model_dir / str(symbol)).resolve()
        if self.model_dir not in symbol_dir.parents:
            raise ValueError("model artifact path escapes model directory")
        symbol_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = symbol_dir / f"{version}.joblib"
        joblib.dump({
            "model": final_model,
            "feature_names": feature_names,
            "trained_until": trained_until.isoformat(),
            "data_hash": data_hash,
            "feature_hash": feature_hash,
        }, artifact_path)

        self.registry.register(
            version,
            symbol,
            "CHALLENGER",
            candidate_metrics.as_dict(),
            artifact_path,
            trained_until=trained_until.isoformat(),
            data_hash=data_hash,
            feature_hash=feature_hash,
        )
        champion = self.registry.champion(symbol)
        if champion:
            champion_metrics = EvaluationMetrics(
                **json.loads(champion["metrics_json"])
            )
            offline_passed = self.gate.passes(
                candidate_metrics, champion_metrics
            )[0]
        else:
            offline_passed = self.gate.passes_baseline(
                candidate_metrics
            )[0]
        if offline_passed:
            self.registry.set_status(version, "SHADOW")
        self.store.record_training(symbol, version, now)
        return version

    def promote_if_ready(self, version, min_shadow_samples=50):
        candidate = self.registry.get(version)
        if (
            candidate is None
            or candidate["status"] != "SHADOW"
            or candidate["shadow_samples"] < min_shadow_samples
            or not candidate["shadow_metrics_json"]
        ):
            return False
        shadow_metrics = EvaluationMetrics(
            **json.loads(candidate["shadow_metrics_json"])
        )
        champion = self.registry.champion(candidate["symbol"])
        if champion:
            champion_metrics = EvaluationMetrics(
                **json.loads(champion["metrics_json"])
            )
            passed = self.gate.passes(
                shadow_metrics, champion_metrics
            )[0]
        else:
            passed = self.gate.passes_baseline(shadow_metrics)[0]
        return (
            self.registry.promote(version, min_shadow_samples)
            if passed else False
        )

    def evaluate_shadow(self, symbol, min_shadow_samples=50):
        candidate = self.registry.shadow(symbol)
        if candidate is None:
            return {
                "symbol": str(symbol),
                "version": None,
                "shadow_samples": 0,
                "promoted": False,
            }
        frame = self.store.completed_frame(symbol)
        trained_until = pd.Timestamp(candidate["trained_until"])
        frame = frame.loc[frame.index > trained_until]
        sample_count = len(frame)
        result = {
            "symbol": str(symbol),
            "version": candidate["version"],
            "shadow_samples": sample_count,
            "promoted": False,
        }
        if sample_count < min_shadow_samples:
            return result

        artifact_path = Path(candidate["artifact_path"]).resolve()
        if self.model_dir not in artifact_path.parents:
            raise ValueError("model artifact path escapes model directory")
        artifact = joblib.load(artifact_path)
        feature_names = artifact["feature_names"]
        features = frame.reindex(columns=feature_names).apply(
            pd.to_numeric, errors="coerce"
        ).fillna(0.0)
        probabilities = artifact["model"].predict_proba(features)[:, 1]
        shadow_metrics = evaluate_predictions(
            frame["horizon_return"],
            pd.Series(probabilities, index=frame.index),
            folds=3,
        )
        self.registry.record_shadow_metrics(
            candidate["version"],
            shadow_metrics.as_dict(),
            sample_count,
        )
        result["promoted"] = self.promote_if_ready(
            candidate["version"], min_shadow_samples
        )
        return result

    def run_after_backtest(self, symbols, now):
        statuses = []
        for symbol in dict.fromkeys(str(item) for item in symbols):
            try:
                status = self.evaluate_shadow(symbol)
                status["trained_version"] = self.maybe_train(symbol, now)
            except Exception as exc:
                status = {
                    "symbol": symbol,
                    "version": None,
                    "shadow_samples": 0,
                    "promoted": False,
                    "trained_version": None,
                    "error": str(exc),
                }
            statuses.append(status)
        return statuses
