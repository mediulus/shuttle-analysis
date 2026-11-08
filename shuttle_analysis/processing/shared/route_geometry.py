"""Small geometry primitives for offline route matching (meters and degrees)."""

import math

EARTH_RADIUS_M = 6_371_000


def coordinate(latitude, longitude):
    """Convert numeric strings and reject invalid or nonfinite GPS coordinates."""
    latitude, longitude = float(latitude), float(longitude)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Invalid latitude/longitude")
    return latitude, longitude


def distance(a, b):
    """Great-circle point-to-point distance; this is not road distance."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    haversine = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1, max(0, haversine))))


def project(point, a, b):
    """Return lateral distance and clamped fraction on a short route segment.

    Use a local equirectangular plane centered on the GPS point. A repeated
    coordinate is a zero-length segment and projects to its first endpoint.
    """
    origin_latitude, origin_longitude = map(math.radians, point)

    def local_coordinates(coord):
        latitude, longitude = map(math.radians, coord)
        return (
            EARTH_RADIUS_M * (longitude - origin_longitude) * math.cos(origin_latitude),
            EARTH_RADIUS_M * (latitude - origin_latitude),
        )

    start_x, start_y = local_coordinates(a)
    end_x, end_y = local_coordinates(b)
    delta_x, delta_y = end_x - start_x, end_y - start_y
    squared_length = delta_x * delta_x + delta_y * delta_y
    fraction = (
        max(0, min(1, -(start_x * delta_x + start_y * delta_y) / squared_length))
        if squared_length else 0
    )
    lateral_distance = math.hypot(start_x + fraction * delta_x, start_y + fraction * delta_y)
    return lateral_distance, fraction


def projections(point, shape, cumulative):
    """Project onto each route segment, sorted by sideways distance.

    The candidate key ``s`` means distance along the route in meters.
    """
    candidates = []
    for index, (start, end) in enumerate(zip(shape, shape[1:])):
        lateral_distance, fraction = project(point, start, end)
        candidates.append({
            "segment_index": index,
            "fraction": fraction,
            "distance_m": lateral_distance,
            "s": cumulative[index] + fraction * (cumulative[index + 1] - cumulative[index]),
        })
    return sorted(candidates, key=lambda candidate: candidate["distance_m"])
