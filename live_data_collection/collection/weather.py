import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

URL = "https://api.weather.gov/stations/KBOS/observations"
HEADERS = {"User-Agent": "my-weather-app (you@example.com)"}  # NWS requires this
CSV_FILE = Path(__file__).resolve().parent.parent / "data" / "weather_log.csv"
INTERVAL = 300  # 5 minutes

FIELDS = [
    "collected_at_utc",
    "observed_at",
    "temperature_c",
    "humidity_pct",
    "wind_speed_kmh",
    "pressure_pa",
    "description",
]

def fetch_weather():
    response = requests.get(URL, headers=HEADERS, params={"limit": 10}, timeout=10)
    response.raise_for_status()
    features = response.json()["features"]  # newest first

    # Pick the newest observation that actually has a temperature
    props = next(
        (f["properties"] for f in features
         if f["properties"]["temperature"]["value"] is not None),
        features[0]["properties"],  # fallback if none are complete
    )

    return {
        "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "observed_at": props.get("timestamp"),
        "temperature_c": props["temperature"]["value"],
        "humidity_pct": props["relativeHumidity"]["value"],
        "wind_speed_kmh": props["windSpeed"]["value"],
        "pressure_pa": props["barometricPressure"]["value"],
        "description": props.get("textDescription"),
    }

def append_to_csv(row):
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not file_exists:
            writer.writeheader()  # only write the header once
        writer.writerow(row)

def main():
    while True:
        start = time.monotonic()
        try:
            row = fetch_weather()
            append_to_csv(row)
            print(f"Saved: {row['collected_at_utc']}  {row['temperature_c']}°C")
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"Error: {e}")
        time.sleep(max(0, INTERVAL - (time.monotonic() - start)))

if __name__ == "__main__":
    main()