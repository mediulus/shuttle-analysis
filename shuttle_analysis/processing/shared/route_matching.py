"""Match GPS coordinates to progress along a closed route."""

from .route_geometry import projections


MAX_FORWARD_METERS = 500
BACKWARD_TOLERANCE_METERS = 20
MAX_ROUTE_DISTANCE_METERS = 50
AMBIGUITY_METERS = 5


def match_route_position(coord, previous, shape, cumulative, radius_m):
    """Choose the nearest route projection within a fixed progress window."""
    length = cumulative[-1]
    candidates = []
    for candidate in projections(coord, shape, cumulative):
        if candidate["distance_m"] > MAX_ROUTE_DISTANCE_METERS:
            continue
        progress = candidate["s"]
        if previous is not None:
            change = progress - previous["progress"] % length
            if change < -BACKWARD_TOLERANCE_METERS:
                change += length
            elif change > length - BACKWARD_TOLERANCE_METERS:
                change -= length
            if not -BACKWARD_TOLERANCE_METERS - 1e-6 <= change <= MAX_FORWARD_METERS:
                continue
            progress = previous["progress"] + change
        candidates.append({**candidate, "progress": progress})
    if not candidates:
        return None
    nearest = candidates[0]
    for alternative in candidates[1:]:
        separation = abs(alternative["s"] - nearest["s"])
        separation = min(separation, length - separation)
        if (separation > 2 * radius_m
                and alternative["distance_m"] - nearest["distance_m"] <= AMBIGUITY_METERS):
            return None
    return nearest["progress"]

