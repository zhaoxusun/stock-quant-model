import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "ml", "data", "raw")
SIGNAL_DATA_DIR = os.path.join(PROJECT_ROOT, "ml", "data", "signals")
MODEL_DIR = os.path.join(PROJECT_ROOT, "ml", "models")
FEATURE_CACHE_DIR = os.path.join(PROJECT_ROOT, "ml", "data")

STRATEGIES = {
    "EnhancedVolumeStrategy": {
        "enabled": True,
        "train_model": True,
        "params": {
            "n1": 1,
            "n2": 5,
            "n3": 20,
            "rsi_period": 14,
            "boll_period": 20,
            "boll_width": 2,
            "kdj_period": 9,
        },
    },
    "SingleVolumeStrategy": {
        "enabled": True,
        "train_model": False,
        "params": {
            "n1": 1,
            "n2": 5,
            "n3": 20,
            "rsi_period": 14,
            "boll_period": 20,
            "boll_width": 2,
            "kdj_period": 9,
        },
    },
}

SIGNAL_PRIORITY = {
    "normal_pos": 1,
    "normal_neg": 2,
    "strong_pos": 3,
    "strong_neg": 4,
    "hold": 0,
}

LABEL_MAP = {"hold": 0, "normal_pos": 1, "normal_neg": 2, "strong_pos": 3, "strong_neg": 4}
LABEL_INVERSE = {0: "hold", 1: "normal_pos", 2: "normal_neg", 3: "strong_pos", 4: "strong_neg"}

XGB_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "max_depth": 8,
    "learning_rate": 0.1,
    "n_estimators": 300,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "gamma": 0.1,
    "random_state": 42,
    "verbosity": 1,
}

SIGNAL_TYPES = ["normal_pos", "normal_neg", "strong_pos", "strong_neg"]
