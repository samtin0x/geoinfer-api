"""Geographic clustering for prediction results."""

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0


@dataclass
class Point:
    lat: float
    lon: float
    confidence: float = 1.0


@dataclass
class Cluster:
    center_lat: float
    center_lon: float
    radius_km: float
    points: list[Point]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _centroid(points: list[Point]) -> tuple[float, float]:
    """Compute geographic centroid weighted by confidence."""
    if not points:
        return 0.0, 0.0
    if len(points) == 1:
        return points[0].lat, points[0].lon

    total = sum(p.confidence for p in points)
    x = y = z = 0.0
    for p in points:
        lat_r, lon_r = math.radians(p.lat), math.radians(p.lon)
        x += p.confidence * math.cos(lat_r) * math.cos(lon_r)
        y += p.confidence * math.cos(lat_r) * math.sin(lon_r)
        z += p.confidence * math.sin(lat_r)
    x, y, z = x / total, y / total, z / total
    return math.degrees(math.atan2(z, math.sqrt(x * x + y * y))), math.degrees(
        math.atan2(y, x)
    )


def _max_radius(points: list[Point], clat: float, clon: float) -> float:
    if len(points) <= 1:
        return 0.0
    return max(haversine_km(clat, clon, p.lat, p.lon) for p in points)


def cluster_points(points: list[Point], distance_km: float = 25.0) -> list[Cluster]:
    """Cluster points by proximity using agglomerative clustering."""
    if not points:
        return []

    groups: list[list[Point]] = [[p] for p in points]

    def min_dist(g1: list[Point], g2: list[Point]) -> float:
        return min(haversine_km(a.lat, a.lon, b.lat, b.lon) for a in g1 for b in g2)

    while len(groups) > 1:
        best_d, bi, bj = float("inf"), -1, -1
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                d = min_dist(groups[i], groups[j])
                if d < best_d:
                    best_d, bi, bj = d, i, j
        if best_d > distance_km:
            break
        groups[bi] = groups[bi] + groups[bj]
        groups.pop(bj)

    result = []
    for g in groups:
        clat, clon = _centroid(g)
        result.append(Cluster(clat, clon, _max_radius(g, clat, clon), g))
    result.sort(key=lambda c: len(c.points), reverse=True)
    return result
