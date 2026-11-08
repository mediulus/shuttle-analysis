"""Measure observed time inside stop areas using sampled GPS positions."""

from datetime import datetime

from ..arrivals.arrival_detector import ArrivalDetector
from ..shared.route_geometry import distance
from ..shared.vehicle_positions import matched_positions


class DwellDetector:
    """Return completed stop visits, using the same route and radius as arrivals.

    Dwell means time observed inside a stop area, not engine idle or time fully
    motionless. Missing data and visits without an observed exit are discarded.
    """

    def __init__(self, snapshot, radius_m=30, stop_segments=None):
        """Reuse arrival route setup, including reviewed stop placements."""
        self.route = ArrivalDetector(snapshot, radius_m, stop_segments)

    def detect(self, observations):
        """Return arrival fields plus last-inside time, first-outside time, and dwell."""
        dwells, buses = [], {}
        route = self.route
        for bus_id, coord, timestamp, progress, previous in matched_positions(observations, route):
            if previous is None:
                buses[bus_id] = {"visited": set(), "active": {}}
            state = buses[bus_id]
            # Close visits only when a reliable position is outside their area.
            for key, visit in list(state["active"].items()):
                stop, target, record = visit
                near = (abs(progress - target) <= route.radius
                        and distance(coord, stop["coord"]) <= route.radius)
                if near:
                    record["last_inside_at"] = timestamp.isoformat()
                else:
                    record["first_outside_at"] = timestamp.isoformat()
                    record["observed_dwell_seconds"] = (
                        datetime.fromisoformat(record["last_inside_at"])
                        - datetime.fromisoformat(record["estimated_arrival_at"])
                    ).total_seconds()
                    dwells.append(record)
                    del state["active"][key]
            for stop in route.stops:
                loop = round((progress - stop["progress"]) / route.length)
                target = stop["progress"] + loop * route.length
                key = (stop["position"], loop)
                near = (abs(progress - target) <= route.radius
                        and distance(coord, stop["coord"]) <= route.radius)
                passed = previous is not None and previous["progress"] < target <= progress
                if (near or passed) and key not in state["visited"]:
                    state["visited"].add(key)
                    # Crossing between samples supplies no observations of dwell.
                    # Starting inside does not establish an arrival either.
                    if near and previous is not None:
                        record = {
                            "session_id": route.session_id, "bus_id": bus_id,
                            "route_id": route.route_id, "stop_id": stop["id"],
                            "route_stop_position": stop["position"],
                            "estimated_arrival_at": timestamp.isoformat(),
                            "previous_observed_at": previous["time"].isoformat(),
                            "arrival_method": "near_stop",
                            "last_inside_at": timestamp.isoformat(),
                        }
                        state["active"][key] = (stop, target, record)
        return dwells
