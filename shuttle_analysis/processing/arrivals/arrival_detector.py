"""Estimate stop arrivals from sampled GPS positions along a saved route."""

from ..shared.route_geometry import coordinate, distance, project
from ..shared.route_matching import MAX_ROUTE_DISTANCE_METERS, match_route_position
from ..shared.vehicle_positions import matched_positions
from ..shared.stop_segments import BOSTON_DAYTIME_STOPS


class ArrivalDetector:
    """Record the first sampled entry near each stop, once per bus and loop.

    Stop proximity must agree both geographically and along the route.
    Collection times are estimates, not exact GPS fix or boarding times.
    """

    def __init__(self, snapshot, radius_m=30, stop_segments=None):
        """Load one session's route. Optional segments map stop positions to indices."""
        if not 0 < radius_m <= MAX_ROUTE_DISTANCE_METERS:
            raise ValueError("radius_m must be between 0 and 50 meters")
        self.radius = radius_m
        self.session_id = snapshot["session_id"]
        metadata = snapshot["metadata"]
        self.route_id = str(metadata["route_id"])
        raw = metadata["stop_metadata"]
        parts = raw["routePoints"][self.route_id]
        if len(parts) != 1 or len(parts[0]) < 2:
            raise ValueError("Expected one route coordinate sequence")
        self.shape = [coordinate(point["lat"], point["lng"]) for point in parts[0]]
        self.cumulative = [0.0]
        for start, end in zip(self.shape, self.shape[1:]):
            self.cumulative.append(self.cumulative[-1] + distance(start, end))
        self.length = self.cumulative[-1]
        if self.length == 0 or distance(self.shape[0], self.shape[-1]) > 20:
            raise ValueError("Expected a nonzero closed route loop")

        occurrences = raw["routes"][self.route_id][2:]
        if stop_segments is None:
            stop_segments = metadata.get("stop_segments")
        using_default = stop_segments is None
        if using_default:
            ids = [str(stop_id) for _, stop_id, _ in occurrences]
            if (self.route_id != "71342" or len(self.shape) != 384
                    or ids != [stop_id for stop_id, _ in BOSTON_DAYTIME_STOPS]):
                raise ValueError("Provide stop_segments for this route")
            stop_segments = {str(i + 1): segment for i, (_, segment) in enumerate(BOSTON_DAYTIME_STOPS)}
        if set(stop_segments) != {str(position) for position, _, _ in occurrences}:
            raise ValueError("Provide one segment index per route stop position")
        if str(occurrences[0][1]) != str(occurrences[-1][1]):
            raise ValueError("Expected the first stop repeated at the loop end")
        records = {str(stop["id"]): stop for stop in raw["stops"].values()}
        self.stops = []
        last_progress = -1
        for i, (position, stop_id, _) in enumerate(occurrences):
            segment = stop_segments[str(position)]
            if isinstance(segment, bool) or not isinstance(segment, int) or not 0 <= segment < len(self.shape) - 1:
                raise ValueError("Invalid stop segment index")
            record = records[str(stop_id)]
            coord = coordinate(record["latitude"], record["longitude"])
            offset, fraction = project(coord, self.shape[segment], self.shape[segment + 1])
            progress = self.cumulative[segment] + fraction * (self.cumulative[segment + 1] - self.cumulative[segment])
            if i in (0, len(occurrences) - 1):
                progress = 0.0 if i == 0 else self.length
                offset = distance(coord, self.shape[0 if i == 0 else -1])
            if offset > MAX_ROUTE_DISTANCE_METERS or progress <= last_progress:
                raise ValueError("Check stop segments: stops must be near the route and in route order")
            last_progress = progress
            # The repeated first stop is represented by the ending occurrence.
            # Skip the unresolved Silber Way placement in the default table.
            if i and not (using_default and str(stop_id) == "3042"):
                self.stops.append({"id": str(stop_id), "position": str(position),
                                   "coord": coord, "progress": progress})

    def _route_position(self, coord, previous):
        """Use the shared route matcher for one GPS observation."""
        return match_route_position(coord, previous, self.shape, self.cumulative, self.radius)

    def detect(self, observations):
        """Return arrival dictionaries. Missing or unreliable fixes reset bus history."""
        arrivals, visited_by_bus = [], {}
        for bus_id, coord, timestamp, progress, previous in matched_positions(observations, self):
            visited = visited_by_bus.setdefault(bus_id, set()) if previous else set()
            visited_by_bus[bus_id] = visited
            for stop in self.stops:
                loop = round((progress - stop["progress"]) / self.length)
                target = stop["progress"] + loop * self.length
                key = (stop["position"], loop)
                near_stop = (abs(progress - target) <= self.radius
                             and distance(coord, stop["coord"]) <= self.radius)
                passed_stop = previous is not None and previous["progress"] < target <= progress
                if (near_stop or passed_stop) and key not in visited:
                    visited.add(key)
                    # Starting inside does not establish when the bus arrived.
                    if previous:
                        arrivals.append({
                            "session_id": self.session_id, "bus_id": bus_id, "route_id": self.route_id,
                            "stop_id": stop["id"], "route_stop_position": stop["position"],
                            "estimated_arrival_at": timestamp.isoformat(),
                            "previous_observed_at": previous["time"].isoformat(),
                            "arrival_method": "near_stop" if near_stop else "between_samples",
                        })
        return arrivals
