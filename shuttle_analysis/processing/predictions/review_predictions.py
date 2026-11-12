"""Read saved sessions and write one extracted-predictions CSV per session."""

import argparse
import csv
from pathlib import Path

from .prediction_extractor import PredictionExtractor
from ...storage import CSVStorage
from ...route_config import PROJECT_ROUTE_IDS


ROOT = Path(__file__).resolve().parents[3]
PREDICTION_FIELDS = ["session_id", "bus_id", "route_id", "stop_id",
                     "prediction_observed_at", "predicted_arrival_at", "trip_id",
                     "passio_stop_position", "outdated", "out_of_service"]


def extract_session(session_id, data_dir):
    storage = CSVStorage(session_id, data_dir)
    snapshot = storage.read_session_metadata()
    extractor = PredictionExtractor(snapshot)
    selected = set(PROJECT_ROUTE_IDS)
    return [row for row in extractor.extract(storage.read_observations("eta"))
            if row["route_id"] in selected]


def save_predictions(predictions, path):
    """Replace only this derived CSV; collected input files are not changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=PREDICTION_FIELDS)
        writer.writeheader()
        writer.writerows(predictions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="Process one session; otherwise process all saved snapshots")
    args = parser.parse_args()
    data_dir = ROOT / "data"
    sessions = [args.session_id] if args.session_id else sorted(path.stem for path in (data_dir / "sessions").glob("*.json"))
    for session_id in sessions:
        predictions = extract_session(session_id, data_dir)
        output = ROOT / "results" / "predictions" / f"predictions_{session_id}.csv"
        save_predictions(predictions, output)
        print(f"{session_id}: {len(predictions)} extracted predictions saved to {output}")


if __name__ == "__main__":
    main()
