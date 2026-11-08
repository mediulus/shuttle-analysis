"""Select Passio predictions at observed upstream stop arrivals."""

from collections import defaultdict
from datetime import datetime

from ..processing.arrivals.arrival_detector import ArrivalDetector
from ..processing.shared.vehicle_positions import matched_positions


def match_predictions(snapshot, observations, arrivals, predictions, max_stops=4, max_age_seconds=30):
    """Return paired predictions and checkpoint coverage rows.

    Match only within continuous GPS history. Route order identifies the next
    downstream visit; predicted time is never used to choose an arrival.
    """
    if not isinstance(max_stops, int) or not 1 <= max_stops:
        raise ValueError("max_stops must be a positive integer")
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be nonnegative")
    route = ArrivalDetector(snapshot)
    raw = snapshot["metadata"]["stop_metadata"]
    # Drop the repeated starting occurrence, keeping the ending occurrence.
    stops = raw["routes"][route.route_id][3:]
    if max_stops >= len(stops):
        raise ValueError("Checkpoints must be less than one full loop apart")
    positions = {str(position): i for i, (position, _, _) in enumerate(stops)}
    run_numbers, fix_runs = {}, {}
    for bus_id, _, timestamp, _, previous in matched_positions(observations, route):
        if previous is None:
            run_numbers[bus_id] = run_numbers.get(bus_id, 0) + 1
        fix_runs[(bus_id, timestamp.isoformat())] = run_numbers[bus_id]
    visits = defaultdict(list)
    for arrival in arrivals:
        if arrival["session_id"] != route.session_id or arrival["route_id"] != route.route_id:
            continue
        run = fix_runs.get((arrival["bus_id"], arrival["estimated_arrival_at"]))
        if run is not None:
            visits[(arrival["bus_id"], run)].append(arrival)
    usable = defaultdict(list)
    for prediction in predictions:
        if prediction["session_id"] != route.session_id or prediction["route_id"] != route.route_id:
            continue
        # Missing flags are not assumed to mean fresh/in service.
        if any(str(prediction.get(flag)) != "0" for flag in ("outdated", "out_of_service")):
            continue
        usable[(prediction["bus_id"], prediction["stop_id"])].append(prediction)
    pairs, coverage = [], []
    for (bus_id, _), bus_visits in visits.items():
        bus_visits.sort(key=lambda row: datetime.fromisoformat(row["estimated_arrival_at"]))
        for index, checkpoint in enumerate(bus_visits):
            checkpoint_time = datetime.fromisoformat(checkpoint["estimated_arrival_at"])
            targets, steps = {}, 0
            last_position = positions[checkpoint["route_stop_position"]]
            for target in bus_visits[index + 1:]:
                position = positions[target["route_stop_position"]]
                steps += (position - last_position) % len(stops) or len(stops)
                if steps > max_stops:
                    break
                targets[steps] = target
                last_position = position
            for ahead in range(1, max_stops + 1):
                target_position = (positions[checkpoint["route_stop_position"]] + ahead) % len(stops)
                position, stop_id, _ = stops[target_position]
                row = {
                    "session_id": route.session_id, "bus_id": bus_id, "route_id": route.route_id,
                    "stop_id": str(stop_id), "route_stop_position": str(position),
                    "checkpoint_stop_id": checkpoint["stop_id"],
                    "checkpoint_route_stop_position": checkpoint["route_stop_position"],
                    "checkpoint_at": checkpoint["estimated_arrival_at"],
                    "checkpoint_previous_observed_at": checkpoint["previous_observed_at"],
                    "checkpoint_arrival_method": checkpoint["arrival_method"], "stops_ahead": ahead,
                }
                target = targets.get(ahead)
                if target is None:
                    coverage.append({**row, "status": "no_target_arrival"})
                    continue
                candidates = []
                for prediction in usable[(bus_id, str(stop_id))]:
                    age = (checkpoint_time - datetime.fromisoformat(prediction["prediction_observed_at"])).total_seconds()
                    if 0 <= age <= max_age_seconds:
                        candidates.append(prediction)
                if not candidates:
                    coverage.append({**row, "status": "no_prediction"})
                    continue
                latest = max(datetime.fromisoformat(p["prediction_observed_at"]) for p in candidates)
                candidates = [p for p in candidates if datetime.fromisoformat(p["prediction_observed_at"]) == latest]
                if len({(p["predicted_arrival_at"], p.get("trip_id"), p.get("passio_stop_position")) for p in candidates}) > 1:
                    coverage.append({**row, "status": "ambiguous_prediction"})
                    continue
                prediction = candidates[0]
                pairs.append({**row,
                    "prediction_observed_at": prediction["prediction_observed_at"],
                    "predicted_arrival_at": prediction["predicted_arrival_at"],
                    "estimated_arrival_at": target["estimated_arrival_at"],
                    "target_previous_observed_at": target["previous_observed_at"],
                    "arrival_method": target["arrival_method"],
                })
                coverage.append({**row, "status": "matched"})
    return pairs, coverage
