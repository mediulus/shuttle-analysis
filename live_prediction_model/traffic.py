"""Load TomTom leg travel times saved by live_data_collection/collection/live_traffic.py."""

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

TRAFFIC_FILE = Path(__file__).resolve().parents[1] / "data" / "traffic_legs.csv"


def load_traffic(route_id, leg_lengths, path=TRAFFIC_FILE, max_length_mismatch=0.25):
    """Return {(from_position, to_position): [(observed_at, travel_seconds), ...]}.

    Legs whose TomTom road length differs from the shuttle's route length by
    more than `max_length_mismatch` are skipped: TomTom took a different path
    (e.g. a shortcut across Mass Ave), so its time is not for the shuttle's leg.
    """
    traffic = defaultdict(list)
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            leg = (row["from_position"], row["to_position"])
            if row["route_id"] != str(route_id) or leg not in leg_lengths or not row["travel_time_s"]:
                continue
            shuttle = leg_lengths[leg]
            if abs(float(row["length_m"]) - shuttle) > max_length_mismatch * shuttle:
                continue
            traffic[leg].append((datetime.fromisoformat(row["collected_at_utc"]), float(row["travel_time_s"])))
    return dict(traffic)
