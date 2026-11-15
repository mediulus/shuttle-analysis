"""Turn weather into the six model columns.

Real rows use the latest KBOS report at or before the row's time. Simulated
rows use the simulator's scenario for the day. The mapping tables are in
docs/HISTORICAL_PREDICTION_MODEL.md.
"""

import csv
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEATHER_FILE = ROOT / "data" / "historical_weather" / "data" / "weather_history.csv"

COLUMNS = ["precip_type", "precip_intensity", "low_visibility", "wet_last_3h",
           "temperature_c", "wind_speed_kmh"]
MAX_AGE = timedelta(hours=2)
WET_WINDOW = timedelta(hours=3)
# Most severe first: a mixed report takes the first type that matches.
PRECIP_CODES = [("ice", ("FZRA", "FZDZ", "PL")), ("snow", ("SN",)), ("rain", ("RA",)), ("drizzle", ("DZ",))]
# Simulator scenario -> (precip_type, precip_intensity).
SCENARIOS = {"clear": ("none", 0), "rain": ("rain", 2), "heavy_rain": ("rain", 3), "snow": ("snow", 2)}


def decode(description):
    """Return (precip_type, precip_intensity, low_visibility) for one station report."""
    if not description:
        return None, None, None
    # Dry weather is written in words ("Mostly Clear"); only the shorthand is upper case.
    codes = [token for token in description.split() if token == token.upper()]
    low_visibility = int(any("BR" in code or "FG" in code for code in codes))
    for precip_type, markers in PRECIP_CODES:
        for code in codes:
            if any(marker in code for marker in markers):
                intensity = 1 if code.startswith("-") else 3 if code.startswith("+") else 2
                return precip_type, intensity, low_visibility
    return "none", 0, low_visibility


def simulated(scenario):
    """Weather columns for a simulated day. The simulator has no temperature, wind or visibility."""
    row = dict.fromkeys(COLUMNS)
    if scenario in SCENARIOS:
        precip_type, intensity = SCENARIOS[scenario]
        row.update(precip_type=precip_type, precip_intensity=intensity, wet_last_3h=int(precip_type != "none"))
    return row


def _number(value):
    return float(value) if value not in ("", None) else None


class Weather:
    """KBOS observations with a latest-at-or-before lookup."""

    def __init__(self, path=WEATHER_FILE):
        reports = []
        path = Path(path)
        if path.exists():
            with path.open(newline="", encoding="utf-8-sig") as file:
                for row in csv.DictReader(file):
                    reports.append((datetime.fromisoformat(row["observed_at"]), decode(row["description"]),
                                    _number(row["temperature_c"]), _number(row["wind_speed_kmh"])))
        reports.sort(key=lambda report: report[0])
        self.times = [report[0] for report in reports]
        self.reports = reports

    def at(self, when):
        """Weather columns at a timezone-aware time; all missing if the latest report is too old."""
        row = dict.fromkeys(COLUMNS)
        latest = bisect_right(self.times, when)
        if not latest or when - self.times[latest - 1] > MAX_AGE:
            return row
        _, (precip_type, intensity, low_visibility), temperature, wind = self.reports[latest - 1]
        recent = self.reports[bisect_left(self.times, when - WET_WINDOW):latest]
        row.update(precip_type=precip_type, precip_intensity=intensity, low_visibility=low_visibility,
                   wet_last_3h=int(any(report[1][0] not in (None, "none") for report in recent)),
                   temperature_c=temperature, wind_speed_kmh=wind)
        return row
