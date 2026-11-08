"""Read reliable bus positions using the same rules for arrival and dwell detection."""

from datetime import datetime

from .route_geometry import coordinate


MAX_GAP_SECONDS = 60


def matched_positions(observations, route):
    """Yield bus ID, coordinate, time, route progress, and previous accepted fix.

    Missing buses, bad fixes, route changes, and gaps reset the previous fix.
    The route object supplies the saved geometry and matching function.
    """
    buses = {}
    observations = sorted(observations, key=lambda obs: datetime.fromisoformat(obs["request_started_at"]))
    for obs in observations:
        if obs.get("request_type", "vehicles") != "vehicles":
            continue
        if obs.get("session_id", route.session_id) != route.session_id:
            raise ValueError("Observation belongs to another session")
        data = obs.get("data")
        if obs.get("error") or not isinstance(data, dict) or not isinstance(data.get("buses"), dict):
            buses.clear()
            continue
        timestamp = datetime.fromisoformat(obs["response_received_at"])
        current_buses = {}
        for records in data["buses"].values():
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict) or record.get("busId") is None:
                    continue
                bus_id = str(record["busId"])
                if bus_id in current_buses or str(record.get("routeId")) != route.route_id:
                    continue
                if any(str(record.get(flag, 0)) not in ("0", "None") for flag in ("outdated", "outOfService")):
                    continue
                try:
                    coord = coordinate(record["latitude"], record["longitude"])
                except (KeyError, TypeError, ValueError):
                    continue
                previous = buses.get(bus_id)
                if previous and timestamp <= previous["time"]:
                    current_buses[bus_id] = previous
                    continue
                if previous and (timestamp - previous["time"]).total_seconds() > MAX_GAP_SECONDS:
                    previous = None
                progress = route._route_position(coord, previous)
                if progress is None:
                    continue
                current_buses[bus_id] = {"time": timestamp, "progress": progress}
                yield bus_id, coord, timestamp, progress, previous
        buses = current_buses
