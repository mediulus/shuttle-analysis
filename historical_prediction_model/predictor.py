"""Predict arrivals at a bus's next stops from the trained historical model.

Position handling and ETA assembly are the live predictor's. Only the source of
each leg time and dwell differs: here they come from the model, looked up for
the time the bus is expected to reach that leg or stop.

    .venv/bin/python -m historical_prediction_model.predictor --route 71342 --x 1200 --time "2026-11-06 17:58"
"""

import argparse
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

from threadpoolctl import threadpool_limits

from live_prediction_model.predictor import LivePredictor, Settings
from shuttle_analysis.processing.shared.routes import route_snapshot
from shuttle_analysis.storage import CSVStorage

from .features import BOSTON, FeatureBuilder
from .labels import DATA_DIR
from .model import load


class HistoricalPredictor(LivePredictor):
    """Replay one route of one session, or predict for a single time and place."""

    def __init__(self, snapshot, estimator, features, max_stops=4):
        super().__init__(snapshot, Settings(max_stops=max_stops))
        self.estimator, self.features = estimator, features

    def _leg_time(self, leg, timestamp, last_leg, at=None):
        row = self.features.leg(self.route.route_id, leg, round(self.leg_lengths[leg], 1), at or timestamp)
        return self.estimator.predict("leg", [row])[0], self.estimator.name

    def _dwell(self, position, last_dwell, at=None):
        return self.estimator.predict("dwell", [self.features.dwell(self.route.route_id, position, at)])[0]

    def predict(self, observations):
        # Rows are predicted one at a time, where a single thread is far faster.
        with threadpool_limits(limits=1):
            return super().predict(observations)

    def predict_at(self, x, when):
        """Prediction rows for a bus `x` metres along the route at timezone-aware `when`."""
        route = self.route
        progress = x % route.length
        segment = min(bisect_right(route.cumulative, progress), len(route.shape) - 1) - 1
        span = route.cumulative[segment + 1] - route.cumulative[segment]
        fraction = (progress - route.cumulative[segment]) / span if span else 0.0
        (lat1, lon1), (lat2, lon2) = route.shape[segment], route.shape[segment + 1]
        coord = (lat1 + fraction * (lat2 - lat1), lon1 + fraction * (lon2 - lon1))
        with threadpool_limits(limits=1):
            return self._predict_bus("", coord, progress, when, None, {}, {})


def latest_snapshot(route_id, data_dir=DATA_DIR):
    """Route geometry from the newest saved session that includes the route."""
    paths = sorted((Path(data_dir) / "sessions").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths:
        snapshot = CSVStorage(path.stem, data_dir).read_session_metadata()
        if str(route_id) in snapshot["metadata"]["stop_metadata"]["routes"]:
            return route_snapshot(snapshot, route_id)
    raise ValueError(f"No saved session includes route {route_id}")


def main():
    parser = argparse.ArgumentParser(description="Historical ETAs for one time and place.")
    parser.add_argument("--route", required=True, help="Route ID, e.g. 71342")
    parser.add_argument("--x", type=float, required=True, help="Distance along the route in metres")
    parser.add_argument("--time", help='Boston time, "YYYY-MM-DD HH:MM" (default: now)')
    args = parser.parse_args()
    when = datetime.fromisoformat(args.time).replace(tzinfo=BOSTON) if args.time else datetime.now(BOSTON)
    snapshot = latest_snapshot(args.route)
    boosted, _, _ = load()
    stops = snapshot["metadata"]["stop_metadata"]["stops"]
    names = {str(stop["id"]): stop.get("name", "") for stop in stops.values()}
    for row in HistoricalPredictor(snapshot, boosted, FeatureBuilder()).predict_at(args.x, when):
        minutes = row["predicted_seconds"] / 60
        print(f"{row['stops_away']} stop(s) ahead  {minutes:5.1f} min  {row['stop_id']:>7}  {names.get(row['stop_id'], '')}")


if __name__ == "__main__":
    main()
