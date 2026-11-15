"""Calendar and campus-activity lookups for the historical model's features.

Real rows read Maeve's scraped CSVs. Simulated rows read the simulator's own
calendar, because that is what produced their travel times. A missing file
leaves its features missing instead of failing.
"""

import csv
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS_DIR = ROOT / "mit_comunity_events" / "data" / "mit_events_data"
SIM_CALENDAR_FILE = ROOT / "trip simulation" / "generated" / "calendar.csv"

GAME_MINUTES = 120  # Games have no end time; assume two hours.
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SIM_BREAKS = {"": "term", "summer": "summer", "IAP_assumed_lower_demand": "IAP"}  # anything else is a break


def read_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def minutes(clock):
    """'17:30' -> 1050."""
    hours, mins = clock.split(":")[:2]
    return int(hours) * 60 + int(mins)


class AcademicCalendar:
    """Holidays and the term period of a date, from academic_calendar.csv."""

    def __init__(self, path=EVENTS_DIR / "academic_calendar.csv"):
        self.holidays, self.exams, self.breaks, self.terms = [], [], [], []
        starts, ends = {}, {}
        for row in read_rows(path):
            span = (date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"]))
            if row["category"] == "holiday":
                self.holidays.append(span)
            elif row["category"] == "exams":
                self.exams.append(span)
            elif row["category"] == "break":
                self.breaks.append(span)
            elif row["category"] == "term_start":
                starts[row["term"]] = span[0]
            elif row["category"] == "term_end":
                ends[row["term"]] = span[1]
        # (start, end, term name), for terms that have both ends listed.
        self.terms = sorted((starts[name], ends[name], name) for name in starts if name in ends)

    @staticmethod
    def _within(day, spans):
        return any(start <= day <= end for start, end in spans)

    def is_holiday(self, day):
        if not self.terms:
            return None
        return int(self._within(day, self.holidays))

    def term_period(self, day):
        """term, exams, IAP, break or summer; None outside the calendar's coverage."""
        if not self.terms or day < self.terms[0][0]:
            return None
        if self._within(day, self.exams):
            return "exams"
        if self._within(day, self.breaks):
            return "break"
        ended = None
        for start, end, name in self.terms:
            if start <= day <= end:
                return "IAP" if name.startswith("IAP") else "term"
            if end < day:
                ended = name
        # Between terms: after spring it is summer, otherwise a break.
        return "summer" if ended and ended.startswith("Spring") else "break"


class SimCalendar:
    """The simulator's assumed holiday, break and weather scenario for each service date."""

    def __init__(self, path=SIM_CALENDAR_FILE):
        self.days = {row["date"]: row for row in read_rows(path)}

    def get(self, day):
        """Return (is_holiday, term_period, weather_scenario), or three Nones for an unknown date."""
        row = self.days.get(day.isoformat())
        if row is None:
            return None, None, None
        return int(bool(row["holiday"])), SIM_BREAKS.get(row["academic_break"], "break"), row["weather_scenario"]


class Games:
    """Home games with a posted start time."""

    def __init__(self, path=EVENTS_DIR / "sports_games.csv"):
        self.loaded = False
        self.starts = defaultdict(list)
        for row in read_rows(path):
            self.loaded = True
            if row["home_away"] == "home" and row["start_time"]:
                self.starts[row["date"]].append(minutes(row["start_time"]))

    def counts(self, local):
        """Return (games starting in the next hour, games that ended in the past hour)."""
        if not self.loaded:
            return None, None
        now = local.hour * 60 + local.minute
        starts = self.starts.get(local.date().isoformat(), [])
        return (sum(0 <= start - now <= 60 for start in starts),
                sum(0 <= now - (start + GAME_MINUTES) <= 60 for start in starts))


class Classes:
    """Weekly class timetable: how many meetings end near a given time."""

    def __init__(self, path=EVENTS_DIR / "class_meetings.csv"):
        self.loaded = False
        self.ends = defaultdict(list)
        for row in read_rows(path):
            self.loaded = True
            self.ends[row["weekday"]].append(minutes(row["end"]))
        for ends in self.ends.values():
            ends.sort()

    def ending(self, local, window=15):
        if not self.loaded:
            return None
        now = local.hour * 60 + local.minute
        ends = self.ends.get(WEEKDAYS[local.weekday()], [])
        return bisect_right(ends, now + window) - bisect_left(ends, now - window)


class Practice:
    """Assumed varsity practice blocks."""

    def __init__(self, path=EVENTS_DIR / "practice_blocks.csv"):
        self.loaded = False
        self.blocks = defaultdict(list)
        for row in read_rows(path):
            self.loaded = True
            self.blocks[row["date"]].append((minutes(row["start_time"]), minutes(row["end_time"])))

    def active(self, local):
        if not self.loaded:
            return None
        now = local.hour * 60 + local.minute
        return int(any(start <= now < end for start, end in self.blocks.get(local.date().isoformat(), [])))
