"""Replay saved sessions through the live model and score it against Passio.

Uses the existing checkpoint matching and evaluator, so live and Passio errors
are measured the same way. The comparison summary uses only checkpoint/target
pairs that both models have.
"""

import argparse
import csv
from pathlib import Path

from shuttle_analysis.evaluation.eta_evaluator import evaluate, summarize
from shuttle_analysis.evaluation.evaluate_passio import (
    CHECKPOINT_FIELDS, RESULT_FIELDS, SUMMARY_FIELDS, save_csv, summarize_checkpoints,
)
from shuttle_analysis.evaluation.prediction_matching import match_predictions
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.predictions.prediction_extractor import PredictionExtractor
from shuttle_analysis.processing.shared.routes import analysis_route_ids, route_snapshot
from shuttle_analysis.storage import CSVStorage

from .predictor import PREDICTION_FIELDS, LivePredictor, Settings
from .traffic import load_traffic


ROOT = Path(__file__).resolve().parents[1]
SIM_DATASET = ROOT / "trip simulation" / "generated"
PAIR_KEY = ["session_id", "bus_id", "route_id", "stop_id", "route_stop_position", "checkpoint_at", "stops_ahead"]
COMPARISON_FIELDS = ["route_id", "stops_ahead", "shared_pairs", "live_mae_seconds", "passio_mae_seconds",
                     "live_mean_error_seconds", "passio_mean_error_seconds"]


def evaluate_session(session_id, data_dir, settings=Settings(), with_passio=True):
    """Return live predictions, live errors, coverage, and Passio errors for one session."""
    storage = CSVStorage(session_id, data_dir)
    snapshot = storage.read_session_metadata()
    observations = storage.read_observations("vehicles")
    passio = PredictionExtractor(snapshot).extract(storage.read_observations("eta")) if with_passio else []
    predictions, live, coverage, passio_results = [], [], [], []
    for route_id in analysis_route_ids(snapshot):
        selected = route_snapshot(snapshot, route_id)
        arrivals = ArrivalDetector(selected).detect(observations)
        predictor = LivePredictor(selected, settings)
        predictor.set_traffic(load_traffic(route_id, predictor.leg_lengths))
        route_predictions = predictor.predict(observations)
        pairs, route_coverage = match_predictions(selected, observations, arrivals, route_predictions)
        predictions.extend(route_predictions)
        live.extend(evaluate(pairs))
        coverage.extend(route_coverage)
        if with_passio:
            passio_pairs, _ = match_predictions(selected, observations, arrivals, passio)
            passio_results.extend(evaluate(passio_pairs))
    return predictions, live, coverage, passio_results


def compare(live, passio, max_stops=4):
    """Summarize both models on the pairs they share, overall and per route."""
    passio_by_key = {tuple(r[k] for k in PAIR_KEY): r for r in passio}
    shared = [(r, passio_by_key[key]) for r in live
              if (key := tuple(r[k] for k in PAIR_KEY)) in passio_by_key]
    rows = []
    for route_id in ["all", *sorted({r["route_id"] for r, _ in shared})]:
        for ahead in range(1, max_stops + 1):
            group = [(l, p) for l, p in shared
                     if l["stops_ahead"] == ahead and route_id in ("all", l["route_id"])]
            ls, ps = summarize([l for l, _ in group]), summarize([p for _, p in group])
            rows.append({"route_id": route_id, "stops_ahead": ahead, "shared_pairs": len(group),
                         "live_mae_seconds": ls["mae_seconds"], "passio_mae_seconds": ps["mae_seconds"],
                         "live_mean_error_seconds": ls["mean_error_seconds"],
                         "passio_mean_error_seconds": ps["mean_error_seconds"]})
    return rows


def sessions_to_run(args):
    """Return (session_id, data_dir) pairs for real sessions or simulated days."""
    if args.sim_day:
        with (SIM_DATASET / "manifest.csv").open(newline="") as file:
            rows = [r for r in csv.DictReader(file) if r["service_date"] in args.sim_day]
        return [(r["session_id"], SIM_DATASET / r["data_dir"]) for r in rows]
    data_dir = ROOT / "data"
    ids = [args.session_id] if args.session_id else sorted(p.stem for p in (data_dir / "sessions").glob("*.json"))
    return [(session_id, data_dir) for session_id in ids]


def fmt(value):
    return "    -" if value is None else f"{value:5.0f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="One real session; otherwise all saved real sessions")
    parser.add_argument("--sim-day", nargs="+", help="Simulated service date(s), e.g. 2026-11-10")
    parser.add_argument("--save-predictions", action="store_true", help="Also write every live prediction")
    parser.add_argument("--no-passio", action="store_true", help="Skip the Passio comparison (faster)")
    defaults = Settings()
    for name in ("w_last", "w_tomtom", "w_fallback", "default_speed_mps", "default_dwell_s"):
        parser.add_argument(f"--{name.replace('_', '-')}", type=float, default=getattr(defaults, name))
    args = parser.parse_args()
    settings = Settings(w_last=args.w_last, w_tomtom=args.w_tomtom, w_fallback=args.w_fallback,
                        default_speed_mps=args.default_speed_mps, default_dwell_s=args.default_dwell_s)
    output = ROOT / "results/evaluation/live" / ("simulated" if args.sim_day else "")
    all_live, all_coverage, all_passio = [], [], []
    for session_id, data_dir in sessions_to_run(args):
        predictions, live, coverage, passio = evaluate_session(session_id, data_dir, settings, not args.no_passio)
        save_csv(live, output / "errors" / f"live_errors_{session_id}.csv", RESULT_FIELDS)
        save_csv(coverage, output / "coverage" / f"live_coverage_{session_id}.csv", [*CHECKPOINT_FIELDS, "status"])
        save_csv(summarize_checkpoints(live, coverage), output / "summaries" / f"live_summary_{session_id}.csv",
                 SUMMARY_FIELDS)
        if args.save_predictions:
            save_csv(predictions, output / "predictions" / f"live_predictions_{session_id}.csv", PREDICTION_FIELDS)
        all_live.extend(live)
        all_coverage.extend(coverage)
        all_passio.extend(passio)
        print(f"{session_id}: {len(predictions)} predictions, {len(live)} evaluated pairs")
    if not all_coverage:
        print("No sessions evaluated.")
        return
    suffix = args.session_id or "all"
    save_csv(summarize_checkpoints(all_live, all_coverage), output / "summaries" / f"live_summary_{suffix}.csv",
             SUMMARY_FIELDS)
    if args.no_passio:
        return
    comparison = compare(all_live, all_passio)
    save_csv(comparison, output / "summaries" / f"live_vs_passio_{suffix}.csv", COMPARISON_FIELDS)
    print(f"\nShared pairs (seconds)   {'route':>6} {'ahead':>5} {'pairs':>6} {'live MAE':>9} {'Passio MAE':>11}"
          f" {'live bias':>10} {'Passio bias':>12}")
    for row in comparison:
        print(f"{'':24} {row['route_id']:>6} {row['stops_ahead']:>5} {row['shared_pairs']:>6}"
              f" {fmt(row['live_mae_seconds']):>9} {fmt(row['passio_mae_seconds']):>11}"
              f" {fmt(row['live_mean_error_seconds']):>10} {fmt(row['passio_mean_error_seconds']):>12}")


if __name__ == "__main__":
    main()
