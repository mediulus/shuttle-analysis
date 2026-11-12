"""Select independent route views without changing a collected snapshot."""

from ...route_config import PROJECT_ROUTE_IDS


def analysis_route_ids(snapshot):
    """Select Boston Daytime and Boston East, retaining explicit standalone custom routes."""
    metadata = snapshot["metadata"]
    routes = metadata["stop_metadata"]["routes"]
    selected = [route_id for route_id in PROJECT_ROUTE_IDS if route_id in routes]
    if selected:
        return selected
    # Preserve the detector's explicit custom-route interface (also used in tests).
    if metadata.get("stop_segments"):
        return [str(metadata["route_id"])]
    raise ValueError("No Boston Daytime or Saferide Boston East route in this session")



def route_snapshot(snapshot, route_id):
    """Share immutable raw metadata, but select route-specific configuration."""
    route_id = str(route_id)
    metadata = dict(snapshot["metadata"])
    if route_id not in metadata["stop_metadata"]["routes"]:
        raise ValueError(f"Route {route_id} is absent from this session")
    if route_id != str(metadata["route_id"]):
        metadata.pop("stop_segments", None)
    metadata["route_id"] = route_id
    return {**snapshot, "metadata": metadata}


def loop_occurrences(raw, route_id):
    """Deduplicate only an explicitly repeated start/end occurrence."""
    occurrences = raw["routes"][str(route_id)][2:]
    if str(occurrences[0][1]) == str(occurrences[-1][1]):
        return occurrences[1:]
    return occurrences
