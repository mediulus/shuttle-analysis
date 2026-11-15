"""Build the feature row for one leg or one stop visit at a given time.

The same code builds rows for training and for prediction. Simulated rows take
the conditions the simulator generated and leave everything it did not model
missing, so only real rows teach those effects.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from . import weather as weather_columns
from .community import AcademicCalendar, Classes, Games, Practice, SimCalendar
from .weather import Weather

BOSTON = ZoneInfo("America/New_York")
# A service day runs 4 AM to 4 AM, so a 1 AM Saferide trip belongs to the evening before.
SERVICE_DAY_START = timedelta(hours=4)

CONDITIONS = ["minutes_since_midnight", "weekday", "is_holiday", "term_period", *weather_columns.COLUMNS,
              "home_game_starting_60min", "home_game_ended_60min", "classes_ending_15min",
              "practice_block", "is_synthetic"]
FEATURES = {
    "leg": ["route_id", "leg_id", "leg_length_m", *CONDITIONS],
    "dwell": ["route_id", "stop_position", *CONDITIONS],
}
CATEGORICAL = {"route_id", "leg_id", "stop_position", "term_period", "precip_type"}
# The column that identifies what is being predicted, for each model.
KEY = {"leg": "leg_id", "dwell": "stop_position"}


class FeatureBuilder:
    """Look up conditions at a time and attach them to a leg or stop."""

    def __init__(self, weather=None, calendar=None, sim_calendar=None, games=None, classes=None, practice=None):
        self.weather = weather or Weather()
        self.calendar = calendar or AcademicCalendar()
        self.sim_calendar = sim_calendar or SimCalendar()
        self.games = games or Games()
        self.classes = classes or Classes()
        self.practice = practice or Practice()

    def conditions(self, when, synthetic=False):
        """Everything about the moment `when` (timezone-aware), for a real or simulated row."""
        local = when.astimezone(BOSTON)
        service_day = (local - SERVICE_DAY_START).date()
        row = dict.fromkeys(CONDITIONS)
        row.update(minutes_since_midnight=local.hour * 60 + local.minute, weekday=service_day.weekday(),
                   is_synthetic=int(synthetic))
        if synthetic:
            row["is_holiday"], row["term_period"], scenario = self.sim_calendar.get(service_day)
            row.update(weather_columns.simulated(scenario))
            return row
        row["is_holiday"] = self.calendar.is_holiday(service_day)
        row["term_period"] = self.calendar.term_period(service_day)
        row.update(self.weather.at(when))
        row["home_game_starting_60min"], row["home_game_ended_60min"] = self.games.counts(local)
        classes = self.classes.ending(local)
        # The timetable only applies on days when classes meet.
        in_session = row["term_period"] == "term" and not row["is_holiday"]
        row["classes_ending_15min"] = classes if classes is None or in_session else 0
        row["practice_block"] = self.practice.active(local)
        return row

    def leg(self, route_id, leg, length_m, when, synthetic=False):
        """Features for driving `leg` = (from_position, to_position), starting at `when`."""
        return {"route_id": str(route_id), "leg_id": f"{route_id}:{leg[0]}>{leg[1]}",
                "leg_length_m": length_m, **self.conditions(when, synthetic)}

    def dwell(self, route_id, position, when, synthetic=False):
        """Features for a visit to the stop at route position `position`, arriving at `when`."""
        return {"route_id": str(route_id), "stop_position": f"{route_id}:{position}",
                **self.conditions(when, synthetic)}
