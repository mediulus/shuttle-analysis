"""Combine the historical and live (current) predictions into one ETA, and score it.

    ETA_predicted = W_HISTORICAL * historical + W_CURRENT * current

Both models predict at the same GPS fixes for the same next stops, so each
combined row is the weighted average of the two rows for one bus, stop and time.

    .venv/bin/python -m combined_prediction
"""

import argparse
from datetime import datetime, timedelta

from historical_prediction_model.evaluate_historical import compare, print_table
from historical_prediction_model.features import FeatureBuilder
from historical_prediction_model.labels import DATA_DIR, ROOT, test_sessions
from historical_prediction_model.model import load
from historical_prediction_model.predictor import HistoricalPredictor
from live_prediction_model.predictor import LivePredictor
from live_prediction_model.traffic import load_traffic
from shuttle_analysis.evaluation.eta_evaluator import evaluate
from shuttle_analysis.evaluation.evaluate_passio import RESULT_FIELDS, save_csv
from shuttle_analysis.evaluation.prediction_matching import match_predictions
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.shared.routes import analysis_route_ids, route_snapshot
from shuttle_analysis.storage import CSVStorage

W_HISTORICAL = 0.5
W_CURRENT = 0.5
KEY = ["session_id", "bus_id", "route_id", "stop_id", "route_stop_position", "prediction_observed_at"]


def combine(historical, current, w_historical=W_HISTORICAL, w_current=W_CURRENT):
    """Weighted average of two prediction lists, for the rows both of them have."""
    by_key = {tuple(row[k] for k in KEY): row for row in historical}
    combined = []
    for row in current:
        other = by_key.get(tuple(row[k] for k in KEY))
        if other is None:
            continue
        seconds = (w_historical * other["predicted_seconds"] + w_current * row["predicted_seconds"]) \
            / (w_historical + w_current)
        observed = datetime.fromisoformat(row["prediction_observed_at"])
        combined.append({**row, "predicted_seconds": round(seconds, 1),
                         "predicted_arrival_at": (observed + timedelta(seconds=seconds)).isoformat(),
                         "leg_sources": "combined"})
    return combined


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="One real test session; otherwise every real session not used for training")
    args = parser.parse_args()
    historical_model, _, _ = load()
    features = FeatureBuilder()
    results = {"combined": [], "historical": [], "live": []}
    for session_id in [args.session_id] if args.session_id else test_sessions():
        storage = CSVStorage(session_id, DATA_DIR)
        snapshot = storage.read_session_metadata()
        observations = storage.read_observations("vehicles")
        for route_id in analysis_route_ids(snapshot):
            selected = route_snapshot(snapshot, route_id)
            arrivals = ArrivalDetector(selected).detect(observations)
            live = LivePredictor(selected)
            live.set_traffic(load_traffic(route_id, live.leg_lengths))
            predictions = {"historical": HistoricalPredictor(selected, historical_model, features).predict(observations),
                           "live": live.predict(observations)}
            predictions["combined"] = combine(predictions["historical"], predictions["live"])
            for name, rows in predictions.items():
                pairs, _ = match_predictions(selected, observations, arrivals, rows)
                results[name].extend(evaluate(pairs))
    suffix = args.session_id or "all"
    output = ROOT / "results" / "evaluation" / "combined"
    save_csv(results["combined"], output / f"combined_errors_{suffix}.csv", RESULT_FIELDS)
    print_table(compare(results), list(results))


if __name__ == "__main__":
    main()
