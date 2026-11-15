"""Gradient-boosted leg-time and dwell models, and the averages baseline they must beat.

Both predict an average (squared-error loss), because averages add up correctly
when legs and dwells are summed into an ETA.
"""

import json
import pickle
from collections import defaultdict
from datetime import datetime

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from .features import CATEGORICAL, FEATURES, KEY
from .labels import MODEL_DIR

SETTINGS = {"learning_rate": 0.05, "max_leaf_nodes": 15, "min_samples_leaf": 50}
# Longer labels are clipped in training so one long hold does not distort an average.
CAPS = {"leg": 1200.0, "dwell": 600.0}
# Chosen by leaving one real training session out at a time.
REAL_ROW_WEIGHTS = (1, 10, 30, 100)  # A simulated row always counts 1.
TREE_COUNTS = (100, 200, 300, 500)


def feature_rows(target, labels, builder):
    """Attach features to label rows from labels.py."""
    rows = []
    for label in labels:
        when = datetime.fromisoformat(label["at"])
        if target == "leg":
            rows.append(builder.leg(label["route_id"], (label["from_position"], label["to_position"]),
                                    label["length_m"], when, label["synthetic"]))
        else:
            rows.append(builder.dwell(label["route_id"], label["stop_position"], when, label["synthetic"]))
    return rows


def encode(rows, features, categories):
    """Feature dicts -> matrix. Labels become category numbers; missing and unseen values become NaN."""
    matrix = np.full((len(rows), len(features)), np.nan)
    for column, name in enumerate(features):
        if name in CATEGORICAL:
            codes = {value: code for code, value in enumerate(categories[name])}
            matrix[:, column] = [codes.get(row[name], np.nan) for row in rows]
        else:
            matrix[:, column] = [np.nan if row[name] is None else row[name] for row in rows]
    return matrix


def fit(matrix, y, weights, features, trees):
    # scikit-learn cannot bin a numeric column with no values at all. A constant column is never split on.
    empty = np.isnan(matrix).all(axis=0)
    if empty.any():
        matrix = np.where(empty, 0.0, matrix)
    model = HistGradientBoostingRegressor(
        max_iter=trees, early_stopping=False, random_state=0,
        categorical_features=[name in CATEGORICAL for name in features], **SETTINGS)
    return model.fit(matrix, y, sample_weight=weights)


class BoostedEstimator:
    """The trained trees for both targets, with the category lists used to encode rows."""

    name = "historical"

    def __init__(self):
        self.models, self.categories = {}, {}

    def predict(self, target, rows):
        matrix = encode(rows, FEATURES[target], self.categories[target])
        return np.maximum(self.models[target].predict(matrix), 0.0).tolist()


class BaselineEstimator:
    """Average for each leg or stop and hour of the week; falls back to the leg, then to everything."""

    name = "baseline"

    def __init__(self):
        self.tables = {}

    @staticmethod
    def _keys(target, row):
        hour = row["weekday"] * 24 + row["minutes_since_midnight"] // 60
        return (row[KEY[target]], hour), (row[KEY[target]],), ()

    def fit(self, target, rows, y, weights):
        sums = defaultdict(lambda: [0.0, 0.0])
        for row, value, weight in zip(rows, y, weights):
            for key in self._keys(target, row):
                sums[key][0] += weight * value
                sums[key][1] += weight
        self.tables[target] = {key: total / weight for key, (total, weight) in sums.items()}
        return self

    def predict(self, target, rows):
        table = self.tables[target]
        return [next(table[key] for key in self._keys(target, row) if key in table) for row in rows]


def choose(target, rows, matrix, y, raw_y, real, sessions):
    """Pick the real-row weight and tree count by leaving one real session out at a time.

    Returns (weight, trees, table), where table holds the mean absolute error on
    the left-out real rows for every candidate and for the baseline.
    """
    features = FEATURES[target]
    folds = [fold for fold in sorted(set(sessions[real].tolist()))]
    errors = defaultdict(list)
    for weight in REAL_ROW_WEIGHTS:
        weights = np.where(real, float(weight), 1.0)
        for fold in folds:
            held = real & (sessions == fold)
            model = fit(matrix[~held], y[~held], weights[~held], features, max(TREE_COUNTS))
            for trees, predicted in enumerate(model.staged_predict(matrix[held]), 1):
                if trees in TREE_COUNTS:
                    errors[f"weight {weight}, {trees} trees"].extend(np.abs(np.maximum(predicted, 0.0) - raw_y[held]))
            kept = np.flatnonzero(~held)
            baseline = BaselineEstimator().fit(target, [rows[i] for i in kept], y[kept], weights[kept])
            predicted = np.array(baseline.predict(target, [rows[i] for i in np.flatnonzero(held)]))
            errors[f"baseline, weight {weight}"].extend(np.abs(predicted - raw_y[held]))
    table = {name: round(float(np.mean(values)), 2) for name, values in errors.items()}
    candidates = [(table[f"weight {weight}, {trees} trees"], weight, trees)
                  for weight in REAL_ROW_WEIGHTS for trees in TREE_COUNTS]
    _, weight, trees = min(candidates)  # Ties go to the smaller weight, then fewer trees.
    return weight, trees, table


def train(labels, builder, log=print):
    """Train both targets. `labels` is {"leg": rows, "dwell": rows} from labels.py, real and simulated together."""
    boosted, baseline, report = BoostedEstimator(), BaselineEstimator(), {}
    for target in ("leg", "dwell"):
        features = FEATURES[target]
        rows = feature_rows(target, labels[target], builder)
        categories = {name: sorted({row[name] for row in rows if row[name] is not None})
                      for name in features if name in CATEGORICAL}
        matrix = encode(rows, features, categories)
        raw_y = np.array([label["seconds"] for label in labels[target]], dtype=float)
        y = np.minimum(raw_y, CAPS[target])
        real = np.array([not label["synthetic"] for label in labels[target]])
        sessions = np.array([label["session_id"] for label in labels[target]])
        weight, trees, table = choose(target, rows, matrix, y, raw_y, real, sessions)
        weights = np.where(real, float(weight), 1.0)
        boosted.models[target] = fit(matrix, y, weights, features, trees)
        boosted.categories[target] = categories
        baseline.fit(target, rows, y, weights)
        report[target] = {
            "real_rows": int(real.sum()), "simulated_rows": int((~real).sum()),
            "rows_clipped_at_cap": int((raw_y > CAPS[target]).sum()),
            "real_row_weight": weight, "trees": trees,
            "leave_one_session_out_mae_seconds": table,
        }
        log(f"{target}: {int(real.sum())} real + {int((~real).sum())} simulated rows; "
            f"real-row weight {weight}, {trees} trees; left-out MAE "
            f"{table[f'weight {weight}, {trees} trees']} s (baseline {table[f'baseline, weight {weight}']} s)")
    return boosted, baseline, report


def save(boosted, baseline, report, directory=MODEL_DIR):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "model.pkl").open("wb") as file:
        pickle.dump({"boosted": boosted, "baseline": baseline}, file)
    details = {"settings": SETTINGS, "caps_seconds": CAPS, "scikit_learn": sklearn.__version__, **report}
    (directory / "model.json").write_text(json.dumps(details, indent=2) + "\n")


def load(directory=MODEL_DIR):
    """Return (boosted, baseline, details). Run historical_prediction_model.train first."""
    path = directory / "model.pkl"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: run python -m historical_prediction_model.train")
    with path.open("rb") as file:
        estimators = pickle.load(file)
    return estimators["boosted"], estimators["baseline"], json.loads((directory / "model.json").read_text())
