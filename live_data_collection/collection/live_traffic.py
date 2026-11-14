"""Log TomTom live travel times between consecutive Passio stops, every 5 minutes.

For each project route (Boston Daytime and Saferide Boston East), one TomTom
request covers the whole loop. The shuttle's route shape is sent as supporting
points so TomTom drives the shuttle's exact path (left alone, it takes
shortcuts across Mass Ave on short legs). TomTom returns travel time along the
route; the time at each stop is read off it, and each leg is the difference.

Each leg is saved with the same route stop positions the live prediction model
uses, so rows join directly to its legs. TomTom only reports no-traffic time
and delay for the whole loop, so per-leg values of those two are the loop
totals split in proportion to each leg's travel time.

Run from the repo root (needs TOMTOM_API_KEY in .env):
    .venv/bin/python live_data_collection/collection/live_traffic.py
"""

import csv
import os
import sys
import time
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shuttle_analysis.collection.passio_api import PassioAPI  # noqa: E402
from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector  # noqa: E402
from shuttle_analysis.route_config import PROJECT_ROUTE_IDS  # noqa: E402

load_dotenv(ROOT / ".env")
API_KEY = os.getenv("TOMTOM_API_KEY")
URL = "https://api.tomtom.com/routing/1/calculateRoute/{points}/json"
CSV_FILE = ROOT / "data" / "traffic_legs.csv"
INTERVAL = 300  # 5 minutes

FIELDS = [
    "collected_at_utc", "route_id", "route_name", "leg",
    "from_position", "from_stop_id", "from_stop", "to_position", "to_stop_id", "to_stop",
    "length_m", "travel_time_s", "no_traffic_time_s", "traffic_delay_s",
]


def route_stops(stop_metadata, route_id, stop_segments=None):
    """Return the route name, shape, loop length, and stops in loop order.

    Uses the arrival detector's stop placement, so each stop has id, position,
    name, and distance along the shape (m). The repeated start/end stop of a
    loop appears once. `stop_segments` is only needed for non-project routes.
    """
    snapshot = {"session_id": "traffic", "metadata": {"route_id": route_id, "stop_metadata": stop_metadata}}
    detector = ArrivalDetector(snapshot, stop_segments=stop_segments)
    records = {str(stop["id"]): stop for stop in stop_metadata["stops"].values()}
    stops = [{"id": s["id"], "position": s["position"], "name": records[s["id"]].get("name", s["id"]),
              "progress": s["progress"] % detector.length} for s in detector.stops]
    return {"name": stop_metadata["routes"][route_id][0], "shape": detector.shape,
            "length": detector.length, "stops": stops}


def time_along(progress, distance_m):
    """Interpolate TomTom's travel time (s) at a distance along its route."""
    distances = [p["distanceInMeters"] for p in progress]
    times = [p["travelTimeInSeconds"] for p in progress]
    i = min(max(bisect_right(distances, distance_m) - 1, 0), len(distances) - 2)
    span = distances[i + 1] - distances[i] or 1
    return times[i] + (times[i + 1] - times[i]) * (distance_m - distances[i]) / span


def fetch_legs(route_id, route, collected_at):
    """Request one shape-guided loop and return one row per stop-to-stop leg."""
    shape, stops = route["shape"], route["stops"]
    points = f"{shape[0][0]},{shape[0][1]}:{shape[-1][0]},{shape[-1][1]}"
    response = requests.post(URL.format(points=points), params={
        "key": API_KEY,
        "traffic": "true",
        "travelMode": "car",
        "routeType": "fastest",
        "computeTravelTimeFor": "all",  # also returns the loop's no-traffic time
        "extendedRouteRepresentation": ["distance", "travelTime"],
    }, json={"supportingPoints": [{"latitude": lat, "longitude": lon} for lat, lon in shape]}, timeout=30)
    response.raise_for_status()
    result = response.json()["routes"][0]
    summary, progress = result["summary"], result["progress"]
    total_m, total_s = summary["lengthInMeters"], summary["travelTimeInSeconds"]
    if abs(total_m - route["length"]) > 0.1 * route["length"]:
        raise ValueError(f"Route {route_id}: TomTom loop is {total_m} m, shuttle loop is {route['length']:.0f} m")
    # TomTom's path follows the shape, so scale shuttle distances to its length.
    scale = total_m / route["length"]
    at_stop = [(s["progress"] * scale, time_along(progress, s["progress"] * scale)) for s in stops]
    free_ratio = summary["noTrafficTravelTimeInSeconds"] / total_s if total_s else 1
    delay_ratio = summary["trafficDelayInSeconds"] / total_s if total_s else 0
    rows = []
    for i, start in enumerate(stops):
        j = (i + 1) % len(stops)
        end = stops[j]
        length = (at_stop[j][0] - at_stop[i][0]) % total_m
        seconds = (at_stop[j][1] - at_stop[i][1]) % total_s
        rows.append({
            "collected_at_utc": collected_at, "route_id": route_id, "route_name": route["name"], "leg": i + 1,
            "from_position": start["position"], "from_stop_id": start["id"], "from_stop": start["name"],
            "to_position": end["position"], "to_stop_id": end["id"], "to_stop": end["name"],
            "length_m": round(length),
            "travel_time_s": round(seconds, 1),
            "no_traffic_time_s": round(seconds * free_ratio, 1),
            "traffic_delay_s": round(seconds * delay_ratio, 1),
        })
    return rows


def append_rows(rows):
    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    file_exists = CSV_FILE.is_file()
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def main():
    if not API_KEY:
        sys.exit("TOMTOM_API_KEY is missing. Add it to .env in the repo root.")
    stop_metadata = PassioAPI().get_stops()
    routes = {}
    for route_id in PROJECT_ROUTE_IDS:
        if route_id in stop_metadata["routes"]:
            route = routes[route_id] = route_stops(stop_metadata, route_id)
            print(f"{route['name']} ({route_id}): {len(route['stops'])} legs, {route['length']:.0f} m loop")
    if not routes:
        sys.exit("No project routes found in Passio stop metadata.")
    print("Saving to:", CSV_FILE)
    while True:
        start = time.monotonic()
        collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for route_id, route in routes.items():
            name = route["name"]
            try:
                rows = fetch_legs(route_id, route, collected_at)
                append_rows(rows)
                total = sum(r["travel_time_s"] or 0 for r in rows)
                delay = sum(r["traffic_delay_s"] or 0 for r in rows)
                print(f"{collected_at} {name}: {len(rows)} legs | loop {total / 60:.1f} min | delay {delay} s")
            except (requests.RequestException, KeyError, IndexError, ValueError) as e:
                # HTTP errors include the request URL, which contains the key.
                print(f"{collected_at} {name}: error: {str(e).replace(API_KEY, '***')}")
        time.sleep(max(0, INTERVAL - (time.monotonic() - start)))


if __name__ == "__main__":
    main()
