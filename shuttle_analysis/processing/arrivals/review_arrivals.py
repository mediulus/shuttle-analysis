"""Read saved sessions and write one estimated-arrivals CSV per session."""

import argparse
import csv
from pathlib import Path

from .arrival_detector import ArrivalDetector
from ...storage import CSVStorage


ROOT = Path(__file__).resolve().parents[3]
ARRIVAL_FIELDS = ["session_id", "bus_id", "route_id", "stop_id", "route_stop_position",
                  "estimated_arrival_at", "previous_observed_at", "arrival_method"]


def detect_session(session_id, data_dir):
    storage = CSVStorage(session_id, data_dir)
    detector = ArrivalDetector(storage.read_session_metadata())
    return detector.detect(storage.read_observations("vehicles"))


def save_arrivals(arrivals, path):
    """Replace only this derived CSV; collected input files are not changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ARRIVAL_FIELDS)
        writer.writeheader()
        writer.writerows(arrivals)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="Process one session; otherwise process all saved snapshots")
    args = parser.parse_args()
    data_dir = ROOT / "data"
    sessions = [args.session_id] if args.session_id else sorted(path.stem for path in (data_dir / "sessions").glob("*.json"))
    for session_id in sessions:
        arrivals = detect_session(session_id, data_dir)
        output = ROOT / "results" / "arrivals" / f"arrivals_{session_id}.csv"
        save_arrivals(arrivals, output)
        print(f"{session_id}: {len(arrivals)} estimated arrivals saved to {output}")


if __name__ == "__main__":
    main()
