import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load the environment variables from the .env file
load_dotenv()

import requests

# load with your own TOMTOMAPI key
API_KEY = os.getenv("TOMTOM_API_KEY")
CSV_FILE = Path(__file__).resolve().parent.parent / "data" / "route_log.csv"
INTERVAL = 300  # 5 minutes

ROUTE_NAME = "shuttle_route"

STOPS = [
    ("Stud round-a-bout", 42.359589, -71.094370),
    ("Sigma Chi Stop", 42.350650, -71.089483),
    ("Alpha Phi Stop", 42.349206, -71.093613),
    ("BU Stop", 42.349494, -71.100736),
    ("Sigma Kappa Stop", 42.348749, -71.094061),
    ("Back across Bridge", 42.350757, -71.089300),
    ("Stud round-a-bout", 42.359589, -71.094370),    
]

FIELDS = [
    "collected_at_utc",
    "route",
    "leg",
    "from_stop",
    "to_stop",
    "length_m",
    "travel_time_s",
    "no_traffic_time_s",
    "traffic_delay_s",
]

def fetch_route():
    coords = ":".join(f"{lat},{lon}" for _, lat, lon in STOPS)
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{coords}/json"
    response = requests.get(
        url,
        params={
            "key": API_KEY,
            "traffic": "true",
            "travelMode": "car",
            "routeType": "fastest",
            "computeTravelTimeFor": "all",  # also returns the no-traffic time
        },
        timeout=15,
    )
    response.raise_for_status()
    legs = response.json()["routes"][0]["legs"]

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for i, leg in enumerate(legs):
        s = leg["summary"]
        rows.append({
            "collected_at_utc": now,
            "route": ROUTE_NAME,
            "leg": i + 1,
            "from_stop": STOPS[i][0],
            "to_stop": STOPS[i + 1][0],
            "length_m": s.get("lengthInMeters"),
            "travel_time_s": s.get("travelTimeInSeconds"),
            "no_traffic_time_s": s.get("noTrafficTravelTimeInSeconds"),
            "traffic_delay_s": s.get("trafficDelayInSeconds"),
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
    print("Saving to:", CSV_FILE)
    while True:
        start = time.monotonic()
        try:
            rows = fetch_route()
            append_rows(rows)
            total = sum(r["travel_time_s"] or 0 for r in rows)
            print(f"Saved {len(rows)} legs | total {total/60:.1f} min")
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            print(f"Error: {e}")
        time.sleep(max(0, INTERVAL - (time.monotonic() - start)))

if __name__ == "__main__":
    main()