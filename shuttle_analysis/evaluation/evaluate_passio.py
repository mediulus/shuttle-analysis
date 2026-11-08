"""Evaluate Passio predictions at one-through-four-stop checkpoints."""

import argparse
import csv
from pathlib import Path

from .eta_evaluator import evaluate, summarize
from .prediction_matching import match_predictions
from ..processing.arrivals.arrival_detector import ArrivalDetector
from ..processing.predictions.prediction_extractor import PredictionExtractor
from ..storage import CSVStorage


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_FIELDS = ["session_id", "bus_id", "route_id", "stop_id", "route_stop_position",
                     "checkpoint_stop_id", "checkpoint_route_stop_position", "checkpoint_at",
                     "checkpoint_previous_observed_at", "checkpoint_arrival_method", "stops_ahead"]
RESULT_FIELDS = [*CHECKPOINT_FIELDS, "prediction_observed_at", "predicted_arrival_at",
                 "estimated_arrival_at", "target_previous_observed_at", "arrival_method",
                 "error_seconds", "absolute_error_seconds"]
SUMMARY_FIELDS = ["stops_ahead", "checkpoints", "no_target_arrival", "no_prediction",
                  "ambiguous_prediction", "count", "mae_seconds", "mean_error_seconds"]


def evaluate_session(session_id, data_dir, max_stops=4):
    """Read saved observations and return errors, checkpoint coverage, and summary."""
    storage = CSVStorage(session_id, data_dir)
    snapshot = storage.read_session_metadata()
    observations = storage.read_observations("vehicles")
    arrivals = ArrivalDetector(snapshot).detect(observations)
    predictions = PredictionExtractor(snapshot).extract(storage.read_observations("eta"))
    pairs, coverage = match_predictions(snapshot, observations, arrivals, predictions, max_stops)
    results = evaluate(pairs)
    return results, coverage, summarize_checkpoints(results, coverage, max_stops)


def summarize_checkpoints(results, coverage, max_stops=4):
    """Report error and coverage counts separately for each stops-ahead category."""
    summary = []
    for ahead in range(1, max_stops + 1):
        checkpoints = [row for row in coverage if row["stops_ahead"] == ahead]
        summary.append({
            "stops_ahead": ahead, "checkpoints": len(checkpoints),
            **{status: sum(row["status"] == status for row in checkpoints)
               for status in ("no_target_arrival", "no_prediction", "ambiguous_prediction")},
            **summarize([row for row in results if row["stops_ahead"] == ahead]),
        })
    return summary


def save_csv(rows, path, fields):
    """Replace a derived result CSV; never write collected observations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="Process one session; otherwise process all saved snapshots")
    args = parser.parse_args()
    sessions = [args.session_id] if args.session_id else sorted(p.stem for p in (ROOT / "data/sessions").glob("*.json"))
    all_results, all_coverage = [], []
    for session_id in sessions:
        results, coverage, summary = evaluate_session(session_id, ROOT / "data")
        for name, folder, rows, fields in [
            ("errors", "errors", results, RESULT_FIELDS),
            ("coverage", "coverage", coverage, [*CHECKPOINT_FIELDS, "status"]),
            ("summary", "summaries", summary, SUMMARY_FIELDS),
        ]:
            save_csv(rows, ROOT / "results/evaluation/passio" / folder / f"passio_{name}_{session_id}.csv", fields)
        all_results.extend(results)
        all_coverage.extend(coverage)
        print(f"{session_id}: {len(results)} evaluated predictions, {len(coverage)} checkpoints")
    # This summary covers exactly the sessions selected by this invocation.
    summary = summarize_checkpoints(all_results, all_coverage)
    output = ROOT / "results/evaluation/passio/summaries" / (f"passio_summary_{args.session_id}.csv" if args.session_id else "passio_summary_all.csv")
    save_csv(summary, output, SUMMARY_FIELDS)
    for row in summary:
        print(row)


if __name__ == "__main__":
    main()
