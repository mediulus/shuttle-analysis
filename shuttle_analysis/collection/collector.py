from datetime import datetime, timezone
import time

import requests


def collection_routes(stop_metadata, daytime_route_id):
    """Select Boston Daytime and all named Saferide routes from API metadata.

    Keep unique stop IDs in route order for polling. The unmodified metadata
    still preserves repeated occurrences for later analysis.
    """
    daytime_route_id = str(daytime_route_id)
    routes = {}
    for route_id, route in stop_metadata["routes"].items():
        route_id = str(route_id)
        if route_id != daytime_route_id and "saferide" not in str(route[0]).lower():
            continue
        stop_ids = list(dict.fromkeys(str(entry[1]) for entry in route[2:] if entry != 0))
        if not stop_ids:
            raise ValueError(f"Route {route_id} has no polling stops")
        routes[route_id] = {"name": str(route[0]), "stop_ids": stop_ids}
    if daytime_route_id not in routes:
        raise ValueError("The configured daytime route is missing from stop metadata")
    return routes


class Collector:
    """Coordinate timestamped ETA and vehicle observations for configured routes.

    Use a supplied PassioAPI client for requests and optional storage for
    saving observations. Print collection summaries. Do not detect
    arrivals, calculate stops away, or evaluate prediction errors here.
    """

    def __init__(self, api, stop_ids, interval=30, storage=None, routes=None):
        """Configure collection without making requests or starting a loop.

        Args:
            api: A configured PassioAPI instance.
            stop_ids: Unique stop IDs to poll. Repeated route occurrences
                belong in route metadata, not in this polling list.
            interval: Positive interval in seconds between cycle starts.
                Overrunning cycles are followed immediately by the next
                cycle. ETA and vehicle requests share one collection cycle.
            storage: Optional storage object with save_observation(). When
                omitted, observations are returned without being saved.
            routes: Optional route-ID mapping from collection_routes(). In
                this mode, request vehicles first and poll the unique stops
                of each reported active route. Without it, preserve the
                original single-route behavior.
        """
        self.api = api
        self.stop_ids = list(stop_ids)
        self.interval = interval
        self.storage = storage
        self.routes = None if routes is None else {
            str(route_id): {"name": route["name"],
                            "stop_ids": list(dict.fromkeys(map(str, route["stop_ids"])))}
            for route_id, route in routes.items()
        }
        self._last_active_routes = None

    def collect_once(self):
        """Perform one collection cycle without sleeping or repeating.

        With routes configured, request system-wide vehicles once, then
        ETAs for each stop of every reported active configured route. This
        automatically follows daytime/Saferide changes and overlapping
        service without fixed clock-based switching. Each ETA observation
        includes the requested route_id, including empty/failed results.

        Otherwise request the original stop list followed by vehicles once.
        Retain complete responses and UTC timestamps in both modes.

        Report temporary request or JSON decoding failures and continue
        with the remaining requests. Distinguish failures from successful
        responses containing no predictions or vehicles. Print a brief
        request summary without filtering or discarding raw data.

        If storage is configured, save each observation immediately after
        the request completes, including request failures. Storage errors
        propagate and stop collection; they are not treated as API errors.

        Returns:
            A list of dictionaries, one per request, with request_type
            ("eta" or "vehicles"), stop_id (a string or None for vehicles),
            request_started_at, request_finished_at, response_received_at,
            data (the complete decoded response), and error.

            Timestamps are UTC ISO 8601 strings. On success, error is None
            and response_received_at equals request_finished_at. This is
            measured after the API method returns, including JSON decoding,
            rather than at network receipt. On request or decoding failure,
            data and response_received_at are None and error describes the
            exception. A server diagnostic inside decoded JSON remains in
            data and does not set error. Response shapes are not validated
            here. Collection timestamps are not GPS fix timestamps.
        """
        if self.routes is None:
            observations = [self._collect_request("eta", stop_id) for stop_id in self.stop_ids]
            observations.append(self._collect_request("vehicles"))
            return observations

        vehicles = self._collect_request("vehicles")
        observations = [vehicles]
        active_routes = self._active_routes(vehicles)
        names = ", ".join(self.routes[route_id]["name"] for route_id in active_routes)
        print(f"ETA routes this cycle: {names or 'none reported active'}")
        for route_id in active_routes:
            for stop_id in self.routes[route_id]["stop_ids"]:
                observations.append(self._collect_request("eta", stop_id, route_id))
        return observations

    def _active_routes(self, vehicle_observation):
        """Select assignments from GPS; reuse known assignments on request failure.

        Before any usable vehicle response, fall back to all configured
        routes rather than lose predictions during a GPS endpoint failure.
        A successful empty response means no configured routes are active.
        """
        data = vehicle_observation["data"]
        usable = isinstance(data, dict) and isinstance(data.get("buses"), dict)
        if usable:
            usable = all(isinstance(records, list) and all(isinstance(bus, dict) for bus in records)
                         for records in data["buses"].values())
        if vehicle_observation["error"] or not usable:
            print("Vehicle route selection unavailable; using previous routes or startup fallback.")
            return list(self.routes) if self._last_active_routes is None else self._last_active_routes
        reported = {
            str(bus.get("routeId"))
            for records in data["buses"].values() for bus in records
            if all(str(bus.get(flag, 0)) in ("0", "None") for flag in ("outdated", "outOfService"))
        }
        self._last_active_routes = [route_id for route_id in self.routes if route_id in reported]
        return self._last_active_routes

    def _collect_request(self, request_type, stop_id=None, route_id=None):
        """Timestamp one request and save its result outside API-error handling."""
        observation = {
            "request_type": request_type,
            "stop_id": str(stop_id) if stop_id is not None else None,
            "request_started_at": datetime.now(timezone.utc).isoformat(),
            "request_finished_at": None,
            "response_received_at": None,
            "data": None,
            "error": None,
        }
        if route_id is not None:
            observation["route_id"] = str(route_id)
        try:
            if request_type == "vehicles":
                data = self.api.get_vehicles()
            elif route_id is None:
                data = self.api.get_etas(stop_id)
            else:
                data = self.api.get_etas(stop_id, route_id=route_id)
        except (requests.RequestException, ValueError) as error:
            observation["request_finished_at"] = datetime.now(timezone.utc).isoformat()
            observation["error"] = f"{type(error).__name__}: {error}"
        else:
            finished_at = datetime.now(timezone.utc).isoformat()
            observation.update(request_finished_at=finished_at, response_received_at=finished_at, data=data)
        if self.storage is not None:
            self.storage.save_observation(observation)
        label = f"ETA for stop {stop_id}" if request_type == "eta" else "System vehicles"
        if route_id is not None:
            label += f" on route {route_id}"
        status = f"failed ({observation['error']})" if observation["error"] else "response collected"
        print(f"{label}: {status}{' [saved]' if self.storage is not None else ''}")
        return observation

    def run(self):
        """Repeat collection cycles at the configured interval until Ctrl+C.

        Start the first cycle immediately. Subtract each cycle's duration
        from the interval before sleeping. If a cycle overruns, start the
        next immediately without replaying missed cycles. Use a monotonic
        clock for elapsed time so wall-clock adjustments do not affect waits.

        Stop cleanly on Ctrl+C during collection or sleep. Completed writes
        remain saved when storage is configured. Without storage, responses
        are not retained across cycles. Use collect_once() to inspect them.
        Collection and saving time both count toward the cycle duration.

        Raises:
            ValueError: If the interval is not positive and finite.
        """
        if not 0 < self.interval < float("inf"):
            raise ValueError("interval must be positive and finite")

        print(f"Collecting every {self.interval} seconds. Press Ctrl+C to stop.")
        try:
            while True:
                started_at = time.monotonic()
                print(f"\nCycle started: {datetime.now(timezone.utc).isoformat()}")
                self.collect_once()
                elapsed = time.monotonic() - started_at
                remaining = self.interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        except KeyboardInterrupt:
            if self.storage is not None:
                print("\nCollection stopped. Completed writes remain saved.")
            else:
                print("\nCollection stopped. Observations were not saved.")

def main():
    """Start a new collection session using the project data directory."""
    from pathlib import Path
    from uuid import uuid4

    from .passio_api import PassioAPI
    from ..storage import CSVStorage

    session_id = str(uuid4())
    data_dir = Path(__file__).resolve().parents[2] / "data"
    storage = CSVStorage(session_id=session_id, data_dir=data_dir)
    api = PassioAPI()
    print(f"Session ID: {session_id}")
    print(f"Saving observations to: {data_dir}")
    metadata_started_at = datetime.now(timezone.utc)
    stop_metadata = api.get_stops()
    metadata_received_at = datetime.now(timezone.utc)
    routes = collection_routes(stop_metadata, api.route_id)
    collector = Collector(
        api,
        stop_ids=routes[str(api.route_id)]["stop_ids"],
        storage=storage,
        routes=routes,
    )
    print("Configured ETA routes: " + ", ".join(route["name"] for route in routes.values()))
    metadata_path = storage.save_session_metadata({
        "system_id": collector.api.system_id,
        "route_id": collector.api.route_id,
        "stop_ids": collector.stop_ids,
        "interval_seconds": collector.interval,
        "timeout_seconds": collector.api.timeout,
        "api_url": collector.api.url,
        "eta_routes": routes,
        "eta_route_selection": "reported_active_routes_with_failure_fallback",
        "request_started_at": metadata_started_at.isoformat(),
        "response_received_at": metadata_received_at.isoformat(),
        "stop_metadata": stop_metadata,
    })
    print(f"Session metadata saved to: {metadata_path}")
    collector.run()


if __name__ == "__main__":
    main()
