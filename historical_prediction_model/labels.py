"""Turn saved sessions into training labels: one row per leg driven and per stop visit.

Definitions match the live model, so the two terms describe the same quantities:

    leg time  = arrival at a stop - last time seen inside the previous stop
    dwell     = last time seen inside a stop - arrival at that stop

A dwell plus the leg after it is therefore the exact arrival-to-arrival time.
Real and simulated sessions go through the same arrival and dwell detectors.
"""

import csv
import gzip
import json
from collections import defaultdict
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

from live_prediction_model.predictor import LivePredictor
from shuttle_analysis.processing.shared.routes import analysis_route_ids, route_snapshot
from shuttle_analysis.processing.shared.vehicle_positions import matched_positions
from shuttle_analysis.storage import CSVStorage

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SIM_DIR = ROOT / "trip simulation" / "generated"
MODEL_DIR = ROOT / "results" / "historical_model"

LEG_FIELDS = ["session_id", "route_id", "from_position", "to_position", "length_m", "at", "seconds", "synthetic"]
DWELL_FIELDS = ["session_id", "route_id", "stop_position", "at", "seconds", "seen_inside", "synthetic"]
FIELDS = {"leg": LEG_FIELDS, "dwell": DWELL_FIELDS}


def route_labels(snapshot, observations):
    """Return {"leg": rows, "dwell": rows} for one route of one session.

    `at` is when the leg starts or the bus arrives at the stop.
    """
    predictor = LivePredictor(snapshot)
    route, index, stops = predictor.route, predictor.index, predictor.route.stops
    arrivals_by_fix = defaultdict(list)
    for arrival in route.detect(observations):
        arrivals_by_fix[(arrival["bus_id"], arrival["estimated_arrival_at"])].append(arrival)
    visits = {(visit["bus_id"], visit["route_stop_position"], visit["estimated_arrival_at"]): visit
              for visit in predictor.dwell_detector.detect(observations)}
    base = {"session_id": route.session_id, "route_id": route.route_id,
            "synthetic": int(bool(snapshot["metadata"].get("synthetic")))}
    legs, dwells, last = [], [], {}
    for bus_id, _, timestamp, _, previous in matched_positions(observations, route):
        if previous is None:
            last.pop(bus_id, None)  # A gap breaks the chain of consecutive stops.
            continue
        # Several stops crossed in one sample: take them in travel order.
        arrivals = sorted(arrivals_by_fix.get((bus_id, timestamp.isoformat()), []), key=lambda arrival: (
            stops[index[arrival["route_stop_position"]]]["progress"] - previous["progress"]) % route.length)
        for arrival in arrivals:
            position = arrival["route_stop_position"]
            visit = visits.get((bus_id, position, arrival["estimated_arrival_at"]))
            if visit:
                dwells.append({**base, "stop_position": position, "at": arrival["estimated_arrival_at"],
                               "seconds": visit["observed_dwell_seconds"], "seen_inside": 1})
            elif arrival["arrival_method"] == "between_samples":
                # Never seen inside the stop area, so any stopped time is inside the legs around it.
                dwells.append({**base, "stop_position": position, "at": arrival["estimated_arrival_at"],
                               "seconds": 0.0, "seen_inside": 0})
            # Otherwise the bus was inside but never seen leaving: the dwell is unknown.
            before = last.get(bus_id)
            if before and index[before[0]["route_stop_position"]] == (index[position] - 1) % len(stops):
                earlier, earlier_visit = before
                start = earlier["estimated_arrival_at"]
                if earlier_visit and datetime.fromisoformat(earlier_visit["first_outside_at"]) <= timestamp:
                    start = earlier_visit["last_inside_at"]
                leg = (earlier["route_stop_position"], position)
                legs.append({**base, "from_position": leg[0], "to_position": leg[1],
                             "length_m": round(predictor.leg_lengths[leg], 1), "at": start,
                             "seconds": (timestamp - datetime.fromisoformat(start)).total_seconds()})
            last[bus_id] = (arrival, visit)
    return {"leg": legs, "dwell": dwells}


def session_labels(session_id, data_dir=DATA_DIR):
    """Labels for every analysed route of one saved session."""
    storage = CSVStorage(session_id, data_dir)
    snapshot = storage.read_session_metadata()
    observations = storage.read_observations("vehicles")
    labels = {"leg": [], "dwell": []}
    for route_id in analysis_route_ids(snapshot):
        for target, rows in route_labels(route_snapshot(snapshot, route_id), observations).items():
            labels[target].extend(rows)
    return labels


def _session_labels(args):
    return session_labels(*args)


def training_sessions():
    """Real sessions the simulator was calibrated on. Every other real session is test data."""
    return json.loads((SIM_DIR / "summary.json").read_text())["calibration_sessions"]


def test_sessions(data_dir=DATA_DIR):
    """Every saved real session that is not used for training."""
    training = set(training_sessions())
    return sorted(path.stem for path in (Path(data_dir) / "sessions").glob("*.json") if path.stem not in training)


def _cache(target):
    return MODEL_DIR / f"sim_{target}_rows.csv.gz"


def simulated_labels(jobs=None, rebuild=False):
    """Labels for the whole simulated dataset. Slow, so the result is cached in MODEL_DIR."""
    if not rebuild and all(_cache(target).exists() for target in FIELDS):
        labels = {}
        for target in FIELDS:
            with gzip.open(_cache(target), "rt", newline="", encoding="utf-8") as file:
                labels[target] = [{**row, "seconds": float(row["seconds"]), "synthetic": int(row["synthetic"]),
                                   **({"length_m": float(row["length_m"])} if "length_m" in row else {}),
                                   **({"seen_inside": int(row["seen_inside"])} if "seen_inside" in row else {})}
                                  for row in csv.DictReader(file)]
        return labels
    with (SIM_DIR / "manifest.csv").open(newline="", encoding="utf-8") as file:
        sessions = [(row["session_id"], SIM_DIR / row["data_dir"]) for row in csv.DictReader(file)]
    labels = {target: [] for target in FIELDS}
    with Pool(jobs) as pool:
        for session in pool.imap(_session_labels, sessions, chunksize=8):
            for target, rows in session.items():
                labels[target].extend(rows)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for target, fields in FIELDS.items():
        with gzip.open(_cache(target), "wt", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(labels[target])
    return labels
