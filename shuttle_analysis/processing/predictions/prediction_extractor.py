"""Turn saved Passio ETA responses into individual prediction records."""

from datetime import datetime, timezone


class PredictionExtractor:
    """Extract predictions without matching arrivals or calculating errors."""

    def __init__(self, snapshot):
        """Use the collection session identity; preserve predictions for all routes."""
        self.session_id = snapshot["session_id"]

    def extract(self, observations):
        """Return one record per prediction, keeping repeated polls and service flags.

        Skip failed requests and entries missing a bus, route, stop, or usable
        arrivalTimestamp. Optional trip and Passio stop positions may be None.
        Receipt time means when we collected a prediction, not when Passio made it.
        """
        predictions = []
        observations = sorted(observations, key=lambda obs: datetime.fromisoformat(obs["request_started_at"]))
        for obs in observations:
            if obs.get("request_type", "eta") != "eta":
                continue
            if obs.get("session_id", self.session_id) != self.session_id:
                raise ValueError("Observation belongs to another session")
            data = obs.get("data")
            if obs.get("error") or not isinstance(data, dict) or not isinstance(data.get("ETAs"), dict):
                continue
            observed_at = datetime.fromisoformat(obs["response_received_at"]).astimezone(timezone.utc).isoformat()
            for stop_id, entries in data["ETAs"].items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    bus_id, route_id = entry.get("busId"), entry.get("routeId")
                    if bus_id is None or route_id is None or not str(stop_id):
                        continue
                    if entry.get("stopId") is not None and str(entry["stopId"]) != str(stop_id):
                        continue
                    try:
                        seconds = entry["arrivalTimestamp"]
                        if isinstance(seconds, bool):
                            continue
                        arrival_at = datetime.fromtimestamp(float(seconds), timezone.utc).isoformat()
                    except (KeyError, TypeError, ValueError, OverflowError, OSError):
                        continue
                    stop = entry.get("theStop")
                    position = stop.get("position") if isinstance(stop, dict) else None
                    trip_id = entry.get("tripId")
                    predictions.append({
                        "session_id": self.session_id, "bus_id": str(bus_id),
                        "route_id": str(route_id), "stop_id": str(stop_id),
                        "prediction_observed_at": observed_at,
                        "predicted_arrival_at": arrival_at,
                        "trip_id": str(trip_id) if trip_id is not None else None,
                        "passio_stop_position": str(position) if position is not None else None,
                        "outdated": entry.get("outdated"),
                        "out_of_service": entry.get("OOS"),
                    })
        return predictions
