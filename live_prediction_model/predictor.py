"""Predict arrivals at each bus's next stops from live data only.

Formulas are in LIVE_PREDICTION.md. For each leg, the travel time is a weighted
average of the available sources (last bus's time on the leg, TomTom, fallback
speed). ETAs add the remaining part of the current leg, then dwell + travel
time for each later stop.

Predictions are made at every accepted GPS fix and use only information known
at that moment, so replaying a saved session gives the same predictions the
live collector would have produced.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby

from shuttle_analysis.processing.arrivals.arrival_detector import ArrivalDetector
from shuttle_analysis.processing.dwell.dwell_detector import DwellDetector
from shuttle_analysis.processing.shared.route_geometry import distance
from shuttle_analysis.processing.shared.vehicle_positions import matched_positions


@dataclass(frozen=True)
class Settings:
    """Tunable model settings. Weights need not sum to 1; they are renormalized."""

    w_last: float = 0.45
    w_tomtom: float = 0.45
    w_fallback: float = 0.10
    default_speed_mps: float = 5.0
    default_dwell_s: float = 30.0
    max_stops: int = 4
    # TomTom is polled every 5 min; older readings are from a previous run or day.
    tomtom_max_age_s: float = 900.0


PREDICTION_FIELDS = [
    "session_id", "bus_id", "route_id", "stop_id", "route_stop_position", "stops_away",
    "prediction_observed_at", "predicted_seconds", "predicted_arrival_at",
    "current_stop_position", "leg_sources", "outdated", "out_of_service",
]


class LivePredictor:
    """Replay one route of one session and return current-term predictions.

    `traffic` optionally maps a leg (from_position, to_position) to a list of
    (observed_at datetime, travel_seconds) TomTom readings. The latest reading
    at or before the prediction time is used.
    """

    def __init__(self, snapshot, settings=Settings(), traffic=None):
        self.route = ArrivalDetector(snapshot)
        self.dwell_detector = DwellDetector(snapshot)
        self.settings = settings
        stops = self.route.stops
        if len(stops) < 2:
            raise ValueError("Route needs at least two stops")
        self.max_stops = min(settings.max_stops, len(stops) - 1)
        self.index = {stop["position"]: i for i, stop in enumerate(stops)}
        self.leg_lengths = {}
        for i, stop in enumerate(stops):
            following = stops[(i + 1) % len(stops)]
            length = (following["progress"] - stop["progress"]) % self.route.length or self.route.length
            self.leg_lengths[(stop["position"], following["position"])] = length
        self.set_traffic(traffic)

    def set_traffic(self, traffic):
        """Attach TomTom readings: {leg: [(observed_at, travel_seconds), ...]}."""
        self.traffic = {}
        for leg, readings in (traffic or {}).items():
            readings = sorted(readings)
            self.traffic[leg] = ([time for time, _ in readings], [seconds for _, seconds in readings])

    def predict(self, observations):
        """Return prediction rows for every accepted fix in time order."""
        route = self.route
        arrivals_by_fix = defaultdict(list)
        for arrival in route.detect(observations):
            arrivals_by_fix[(arrival["bus_id"], arrival["estimated_arrival_at"])].append(arrival)
        dwells = self.dwell_detector.detect(observations)
        dwell_by_visit = {(d["bus_id"], d["route_stop_position"], d["estimated_arrival_at"]): d for d in dwells}
        # A dwell is only known once the bus is seen outside the stop area.
        dwell_events = sorted(dwells, key=lambda d: datetime.fromisoformat(d["first_outside_at"]))
        next_dwell = 0
        last_leg, last_dwell, last_arrival = {}, {}, {}
        predictions = []
        fixes = matched_positions(observations, route)
        for timestamp, group in groupby(fixes, key=lambda fix: fix[2]):
            group = list(group)
            # Update state from everything known at this time, then predict.
            while (next_dwell < len(dwell_events)
                   and datetime.fromisoformat(dwell_events[next_dwell]["first_outside_at"]) <= timestamp):
                dwell = dwell_events[next_dwell]
                last_dwell[dwell["route_stop_position"]] = dwell["observed_dwell_seconds"]
                next_dwell += 1
            for bus_id, _, _, _, previous in group:
                if previous is None:
                    last_arrival.pop(bus_id, None)
                arrivals = arrivals_by_fix.get((bus_id, timestamp.isoformat()), [])
                if previous is not None:
                    # Several stops crossed in one sample: process them in travel order.
                    arrivals = sorted(arrivals, key=lambda a: (
                        route.stops[self.index[a["route_stop_position"]]]["progress"] - previous["progress"]
                    ) % route.length)
                for arrival in arrivals:
                    self._record_leg(last_leg, last_arrival.get(bus_id), arrival, dwell_by_visit, timestamp)
                    last_arrival[bus_id] = arrival
            for bus_id, coord, _, progress, _ in group:
                predictions.extend(self._predict_bus(
                    bus_id, coord, progress, timestamp, last_arrival.get(bus_id), last_leg, last_dwell))
        return predictions

    def predict_latest(self, observations):
        """Return only the predictions made at the newest fix (for live use)."""
        predictions = self.predict(observations)
        if not predictions:
            return []
        latest = max(p["prediction_observed_at"] for p in predictions)
        return [p for p in predictions if p["prediction_observed_at"] == latest]

    def _record_leg(self, last_leg, previous_arrival, arrival, dwell_by_visit, timestamp):
        """T_last = arrival at this stop - last time inside the previous stop."""
        if previous_arrival is None:
            return
        n = len(self.route.stops)
        if self.index[previous_arrival["route_stop_position"]] != (self.index[arrival["route_stop_position"]] - 1) % n:
            return
        start = previous_arrival["estimated_arrival_at"]
        dwell = dwell_by_visit.get((previous_arrival["bus_id"], previous_arrival["route_stop_position"], start))
        if dwell and datetime.fromisoformat(dwell["first_outside_at"]) <= timestamp:
            start = dwell["last_inside_at"]
        seconds = (datetime.fromisoformat(arrival["estimated_arrival_at"]) - datetime.fromisoformat(start)).total_seconds()
        if seconds > 0:
            last_leg[(previous_arrival["route_stop_position"], arrival["route_stop_position"])] = seconds

    def _leg_time(self, leg, timestamp, last_leg):
        """Weighted average of available sources, renormalized over those present."""
        s = self.settings
        estimates = []
        if leg in last_leg:
            estimates.append(("last", s.w_last, last_leg[leg]))
        tomtom = self._tomtom(leg, timestamp)
        if tomtom is not None:
            estimates.append(("tomtom", s.w_tomtom, tomtom))
        fallback = self.leg_lengths[leg] / s.default_speed_mps
        estimates.append(("fallback", s.w_fallback, fallback))
        weighted = [e for e in estimates if e[1] > 0]
        if not weighted:
            return fallback, "fallback"
        total = sum(weight for _, weight, _ in weighted)
        seconds = sum(weight * value for _, weight, value in weighted) / total
        return seconds, "+".join(name for name, _, _ in weighted)

    def _tomtom(self, leg, timestamp):
        if leg not in self.traffic:
            return None
        times, values = self.traffic[leg]
        i = bisect_right(times, timestamp)
        if not i or (timestamp - times[i - 1]).total_seconds() > self.settings.tomtom_max_age_s:
            return None
        return values[i - 1]

    def _dwell(self, position, last_dwell):
        return last_dwell.get(position, self.settings.default_dwell_s)

    def _predict_bus(self, bus_id, coord, progress, timestamp, last_arrival, last_leg, last_dwell):
        route = self.route
        stops, n = route.stops, len(route.stops)
        current = None
        for stop in stops:
            target = stop["progress"] + round((progress - stop["progress"]) / route.length) * route.length
            if abs(progress - target) <= route.radius and distance(coord, stop["coord"]) <= route.radius:
                current = stop
                break
        if current is not None:
            next_index = (self.index[current["position"]] + 1) % n
        else:
            next_index = min(range(n), key=lambda i: (stops[i]["progress"] - progress) % route.length)
        sequence = [stops[(next_index + k) % n] for k in range(self.max_stops)]

        # Partial current leg: t1 = T1 * (r / L1).
        first = sequence[0]
        leg = (stops[(next_index - 1) % n]["position"], first["position"])
        leg_seconds, source = self._leg_time(leg, timestamp, last_leg)
        remaining = (first["progress"] - progress) % route.length
        eta = leg_seconds * remaining / self.leg_lengths[leg]
        sources = [source]
        if current is not None:
            spent = 0.0
            if last_arrival is not None and last_arrival["route_stop_position"] == current["position"]:
                spent = (timestamp - datetime.fromisoformat(last_arrival["estimated_arrival_at"])).total_seconds()
            eta += max(0.0, self._dwell(current["position"], last_dwell) - spent)

        rows, seen = [], set()
        for k, stop in enumerate(sequence):
            if k:
                previous = sequence[k - 1]
                leg = (previous["position"], stop["position"])
                leg_seconds, source = self._leg_time(leg, timestamp, last_leg)
                eta += self._dwell(previous["position"], last_dwell) + leg_seconds
                sources.append(source)
            # Report the next visit of each physical stop only.
            if stop["id"] in seen:
                continue
            seen.add(stop["id"])
            rows.append({
                "session_id": route.session_id, "bus_id": bus_id, "route_id": route.route_id,
                "stop_id": stop["id"], "route_stop_position": stop["position"], "stops_away": k + 1,
                "prediction_observed_at": timestamp.isoformat(),
                "predicted_seconds": round(eta, 1),
                "predicted_arrival_at": (timestamp + timedelta(seconds=eta)).isoformat(),
                "current_stop_position": current["position"] if current else "",
                "leg_sources": ";".join(sources),
                "outdated": 0, "out_of_service": 0,
            })
        return rows
