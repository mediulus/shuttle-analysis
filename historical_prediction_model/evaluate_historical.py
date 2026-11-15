"""Replay real test sessions through the historical model and score it.

Uses the existing checkpoint matching and evaluator, and compares the model
with the averages baseline, the live model and Passio on the checkpoint/target
pairs that all of them have. Training sessions are never scored.

    .venv/bin/python -m historical_prediction_model.evaluate_historical
"""

import argparse
from pathlib import Path

from live_prediction_model.evaluate_live import PAIR_KEY, fmt
from live_prediction_model.predictor import LivePredictor
from live_prediction_model.traffic import load_traffic
from shuttle_analysis.evaluation.eta_evaluator import evaluate, summarize
from shuttle_analysis.evaluation.evaluate_passio import (
    CHECKPOINT_FIELDS, RESULT_FIELDS, SUMMARY_FIELDS, save_csv, summarize_checkpoints,
)
from shuttle_analysis.evaluation.prediction_matching import match_predictions
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.predictions.prediction_extractor import PredictionExtractor
from shuttle_analysis.processing.shared.routes import analysis_route_ids, route_snapshot
from shuttle_analysis.storage import CSVStorage

from .features import FeatureBuilder
from .labels import DATA_DIR, ROOT, test_sessions
from .model import load
from .predictor import HistoricalPredictor

OUTPUT = ROOT / "results" / "evaluation" / "historical"


def evaluate_session(session_id, data_dir, estimators, features, with_passio=True):
    """Return ({model name: error rows}, historical coverage rows) for one session."""
    storage = CSVStorage(session_id, data_dir)
    snapshot = storage.read_session_metadata()
    observations = storage.read_observations("vehicles")
    passio = PredictionExtractor(snapshot).extract(storage.read_observations("eta")) if with_passio else None
    results, coverage = {}, []
    for route_id in analysis_route_ids(snapshot):
        selected = route_snapshot(snapshot, route_id)
        arrivals = ArrivalDetector(selected).detect(observations)
        live = LivePredictor(selected)
        live.set_traffic(load_traffic(route_id, live.leg_lengths))
        predictions = {estimator.name: HistoricalPredictor(selected, estimator, features).predict(observations)
                       for estimator in estimators}
        predictions["live"] = live.predict(observations)
        if with_passio:
            predictions["passio"] = passio
        for name, rows in predictions.items():
            pairs, route_coverage = match_predictions(selected, observations, arrivals, rows)
            results.setdefault(name, []).extend(evaluate(pairs))
            if name == "historical":
                coverage.extend(route_coverage)
    return results, coverage


def compare(results, max_stops=4):
    """Summarize every model on the pairs they all have, overall and for each route."""
    by_key = {name: {tuple(row[k] for k in PAIR_KEY): row for row in rows} for name, rows in results.items()}
    shared = set.intersection(*(set(rows) for rows in by_key.values())) if by_key else set()
    table = []
    for route_id in ["all", *sorted({key[PAIR_KEY.index("route_id")] for key in shared})]:
        for ahead in range(1, max_stops + 1):
            keys = [key for key in shared if key[PAIR_KEY.index("stops_ahead")] == ahead
                    and route_id in ("all", key[PAIR_KEY.index("route_id")])]
            row = {"route_id": route_id, "stops_ahead": ahead, "shared_pairs": len(keys)}
            for name, rows in by_key.items():
                summary = summarize([rows[key] for key in keys])
                row[f"{name}_mae_seconds"] = summary["mae_seconds"]
                row[f"{name}_mean_error_seconds"] = summary["mean_error_seconds"]
            table.append(row)
    return table


def print_table(table, names):
    header = f"{'route':>6} {'ahead':>5} {'pairs':>6}  " + "".join(f"{name + ' MAE':>15}" for name in names)
    print("\nShared pairs (seconds)\n" + header + "   |" + "".join(f"{name + ' bias':>16}" for name in names))
    for row in table:
        print(f"{row['route_id']:>6} {row['stops_ahead']:>5} {row['shared_pairs']:>6}  "
              + "".join(f"{fmt(row[f'{name}_mae_seconds']):>15}" for name in names) + "   |"
              + "".join(f"{fmt(row[f'{name}_mean_error_seconds']):>16}" for name in names))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="One real test session; otherwise every real session not used for training")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="Folder holding the collected CSVs and sessions/")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="Folder for result CSVs")
    parser.add_argument("--no-passio", action="store_true", help="Skip the Passio comparison (faster)")
    args = parser.parse_args()
    boosted, baseline, details = load()
    if args.session_id in details["training_sessions"]:
        parser.error("That session was used for training, so scoring it would not be a fair test")
    sessions = [args.session_id] if args.session_id else test_sessions(args.data_dir)
    features = FeatureBuilder()
    everything, all_coverage = {}, []
    for session_id in sessions:
        results, coverage = evaluate_session(session_id, args.data_dir, [boosted, baseline], features, not args.no_passio)
        historical = results.get("historical", [])
        save_csv(historical, args.output / "errors" / f"historical_errors_{session_id}.csv", RESULT_FIELDS)
        save_csv(coverage, args.output / "coverage" / f"historical_coverage_{session_id}.csv", [*CHECKPOINT_FIELDS, "status"])
        save_csv(summarize_checkpoints(historical, coverage),
                 args.output / "summaries" / f"historical_summary_{session_id}.csv", SUMMARY_FIELDS)
        for name, rows in results.items():
            everything.setdefault(name, []).extend(rows)
        all_coverage.extend(coverage)
        print(f"{session_id}: {len(historical)} evaluated pairs")
    if not all_coverage:
        print("No sessions evaluated.")
        return
    suffix = args.session_id or "all"
    save_csv(summarize_checkpoints(everything["historical"], all_coverage),
             args.output / "summaries" / f"historical_summary_{suffix}.csv", SUMMARY_FIELDS)
    table = compare(everything)
    save_csv(table, args.output / "summaries" / f"historical_comparison_{suffix}.csv", list(table[0]))
    print_table(table, list(everything))


if __name__ == "__main__":
    main()
