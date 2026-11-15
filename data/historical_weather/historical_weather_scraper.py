import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Same station (KBOS) and same CSV schema as the live collector.
# api.weather.gov only keeps about 7 days of observations, so history comes from
# the Iowa Environmental Mesonet, which archives the same KBOS airport reports.
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
HEADERS = {"User-Agent": "my-weather-app (you@example.com)"}
CSV_FILE = Path(__file__).resolve().parent.parent / "data" / "weather_history.csv"
YEARS = 5
PAUSE_BETWEEN_REQUESTS = 10  # seconds; the archive rate-limits back-to-back downloads
MAX_TRIES = 6

FIELDS = [
    "collected_at_utc",
    "observed_at",
    "temperature_c",
    "humidity_pct",
    "wind_speed_kmh",
    "pressure_pa",
    "description",
]

# Approximates NWS textDescription from sky cover when no weather is reported.
SKY = {"CLR": "Clear", "SKC": "Clear", "FEW": "Mostly Clear",
       "SCT": "Partly Cloudy", "BKN": "Mostly Cloudy", "OVC": "Overcast"}


def num(value, convert=lambda x: x, digits=2):
    """Blank/'M' -> None, otherwise convert and round."""
    if value in (None, "", "M"):
        return None
    try:
        return round(convert(float(value)), digits)
    except ValueError:
        return None


def to_row(rec, collected_at):
    observed = datetime.strptime(rec["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    wx = (rec.get("wxcodes") or "").strip()
    return {
        "collected_at_utc": collected_at,
        "observed_at": observed.isoformat(),  # matches NWS: 2026-11-12T19:54:00+00:00
        "temperature_c": num(rec["tmpf"], lambda f: (f - 32) * 5 / 9),
        "humidity_pct": num(rec["relh"]),
        "wind_speed_kmh": num(rec["sknt"], lambda kt: kt * 1.852),
        "pressure_pa": num(rec["alti"], lambda inhg: inhg * 3386.389, 0),
        "description": wx or SKY.get((rec.get("skyc1") or "").strip(), None),
    }


def fetch_range(start, end):
    params = {
        "station": "BOS",
        "data": ["tmpf", "relh", "sknt", "alti", "wxcodes", "skyc1"],
        "year1": start.year, "month1": start.month, "day1": start.day,
        "year2": end.year, "month2": end.month, "day2": end.day,
        "tz": "Etc/UTC",
        "format": "onlycomma",
        "latlon": "no",
        "missing": "empty",
        "trace": "empty",
        "report_type": ["3", "4"],  # routine + special, like the live feed
    }
    for attempt in range(MAX_TRIES):
        r = requests.get(URL, headers=HEADERS, params=params, timeout=300)
        if r.status_code != 429:
            r.raise_for_status()
            return list(csv.DictReader(r.text.splitlines()))
        # 429 Too Many Requests: wait as long as the server asks, else back off 30s, 60s, ...
        try:
            wait = int(r.headers.get("Retry-After", ""))
        except ValueError:
            wait = 30 * (attempt + 1)
        print(f"  rate limited; waiting {wait}s before retrying ({attempt + 1}/{MAX_TRIES}) ...")
        time.sleep(wait)
    r.raise_for_status()


def main():
    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=365 * YEARS + 1)

    rows, seen = [], set()
    chunk_start = start
    while chunk_start < end:  # ~1 year per request keeps responses small
        chunk_end = min(chunk_start + timedelta(days=365), end)
        print(f"Fetching {chunk_start} to {chunk_end} ...")
        for rec in fetch_range(chunk_start, chunk_end):
            row = to_row(rec, collected_at)
            if row["temperature_c"] is None or row["observed_at"] in seen:
                continue  # same rule as live script: skip obs without a temperature
            seen.add(row["observed_at"])
            rows.append(row)
        chunk_start = chunk_end
        if chunk_start < end:
            time.sleep(PAUSE_BETWEEN_REQUESTS)  # be polite to the archive between requests

    rows.sort(key=lambda r: r["observed_at"])
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} observations to {CSV_FILE}")


if __name__ == "__main__":
    main()