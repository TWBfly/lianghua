"""Minimal in-memory bridge from the audited futures pipeline to Qlib."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
import warnings
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
QLIB_ROOT = PROJECT_ROOT / "qlib"
if str(QLIB_ROOT) not in sys.path:
    sys.path.insert(0, str(QLIB_ROOT))

class _NullRecorder:
    @staticmethod
    def log_metrics(**kwargs):
        return None


import qlib

class _ModelFT:
    pass


class _DatasetH:
    pass


class _DataHandlerLP:
    DK_L = "learn"
    DK_I = "infer"


class _LightGBMFInt:
    pass


class Reweighter:
    pass


_stub_attributes = {
    "qlib.model.base": {"ModelFT": _ModelFT},
    "qlib.data.dataset": {"DatasetH": _DatasetH},
    "qlib.data.dataset.handler": {"DataHandlerLP": _DataHandlerLP},
    "qlib.model.interpret.base": {"LightGBMFInt": _LightGBMFInt},
    "qlib.data.dataset.weight": {"Reweighter": Reweighter},
    "qlib.workflow": {"R": _NullRecorder()},
}
_previous_modules = {name: sys.modules.get(name) for name in _stub_attributes}
for name, attributes in _stub_attributes.items():
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
try:
    _gbdt_spec = importlib.util.spec_from_file_location(
        "qlib.contrib.model.gbdt", QLIB_ROOT / "qlib/contrib/model/gbdt.py"
    )
    qlib_gbdt = importlib.util.module_from_spec(_gbdt_spec)
    sys.modules[_gbdt_spec.name] = qlib_gbdt
    _gbdt_spec.loader.exec_module(qlib_gbdt)
finally:
    for name, previous in _previous_modules.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


class _FrameDataset:
    def __init__(self, train, test):
        self.segments = {"train": "train", "test": "test"}
        self.frames = {"train": train, "test": test}

    def prepare(self, segment, col_set, data_key=None):
        frame = self.frames[segment]
        if isinstance(col_set, str):
            return frame[col_set]
        return frame.loc[:, list(col_set)]


class _Weights(Reweighter):
    def __init__(self, values):
        self.values = np.asarray(values, dtype=float)

    def reweight(self, data):
        return pd.Series(self.values, index=data.index)


class AuditedQlibModel:
    def __init__(self, model, parameters):
        self.model = model
        self.parameters = parameters

    def get_params(self, deep=True):
        return dict(self.parameters)


def _qlib_revision():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=QLIB_ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def fit_qlib_lightgbm(x_train, y_train, sample_weight, x_evaluation, seed):
    feature_names = tuple(x_train.columns)
    if tuple(x_evaluation.columns) != feature_names:
        raise ValueError("Qlib train/evaluation features differ")
    train = pd.concat({
        "feature": x_train.reset_index(drop=True),
        "label": pd.Series(y_train).reset_index(drop=True).to_frame("label"),
    }, axis=1)
    test = pd.concat({
        "feature": x_evaluation.reset_index(drop=True),
    }, axis=1)
    dataset = _FrameDataset(train, test)
    parameters = {
        "backend": "qlib.LGBModel",
        "qlib_version": qlib.__version__,
        "qlib_revision": _qlib_revision(),
        "loss": "binary",
        "learning_rate": 0.03,
        "max_depth": 3,
        "num_leaves": 7,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l1": 1.0,
        "lambda_l2": 5.0,
        "seed": int(seed),
        "num_threads": 1,
        "validation": "external_nested_walk_forward",
        "boost_rounds": 100,
        "early_stopping_rounds": 0,
    }
    model = qlib_gbdt.LGBModel(
        num_boost_round=parameters["boost_rounds"],
        early_stopping_rounds=parameters["early_stopping_rounds"],
        **{key: value for key, value in parameters.items()
           if key not in {
               "backend", "qlib_version", "qlib_revision", "validation",
               "boost_rounds", "early_stopping_rounds",
           }},
    )
    recorder = qlib_gbdt.R
    qlib_gbdt.R = _NullRecorder()
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message="Only training set found, disabling early stopping."
            )
            model.fit(
                dataset, reweighter=_Weights(sample_weight), verbose_eval=0,
            )
    finally:
        qlib_gbdt.R = recorder
    probability = model.predict(dataset, segment="test").to_numpy(dtype=float)
    if not np.isfinite(probability).all():
        raise ValueError("Qlib produced non-finite probabilities")
    return probability, AuditedQlibModel(model, parameters)
