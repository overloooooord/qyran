"""Dynamic Nearest-Unit Selection & Live OSRM Road Routing with Instant Offline Fallback."""
from __future__ import annotations

import logging
import math
from typing import Any

import httpx

logger = logging.getLogger("qyran.routing")

# Preferred unit classes per incident kind
KIND_UNIT_PREF: dict[str, list[str]] = {
    "fire_smoke": ["fire", "own"],
    "casualties": ["med", "own"],
    "crowd": ["pol", "own"],
    "infrastructure": ["grid", "fire", "own"],
    "drone": ["own", "pol"],
    "armed": ["own", "pol"],
    "neutralized": ["grid", "own"],
}


def haversine_m(a: list[float], b: list[float]) -> float:
    """Great-circle distance in meters between [lon, lat] points."""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000.0 * 2.0 * math.asin(min(1.0, math.sqrt(h)))


def select_best_unit(
    kind: str,
    target_coords: list[float],
    units: dict[str, dict[str, Any]],
    preferred_unit: str | None = None,
) -> tuple[str | None, float]:
    """Select the optimal available emergency unit by specialty match + proximity."""
    if preferred_unit and preferred_unit in units:
        return preferred_unit, haversine_m(units[preferred_unit]["pos"], target_coords)
    if not units:
        return None, 0.0

    prefs = KIND_UNIT_PREF.get(kind, ["own", "pol", "fire", "med", "grid"])
    for cls in prefs:
        cands = [(name, haversine_m(u["pos"], target_coords)) for name, u in units.items() if u.get("cls") == cls]
        if cands:
            cands.sort(key=lambda x: x[1])
            return cands[0]

    all_cands = [(name, haversine_m(u["pos"], target_coords)) for name, u in units.items()]
    all_cands.sort(key=lambda x: x[1])
    return all_cands[0]


def compute_road_route(
    origin: list[float],
    destination: list[float],
    cached_routes: dict[str, Any] | None = None,
    unit_route_key: str | None = None,
) -> dict[str, Any]:
    """Compute real street-level route via OSRM, reusing cache when endpoints match or falling back offline."""
    # Reuse cached scenario OSRM route if destination matches within 350m
    if cached_routes and unit_route_key and unit_route_key in cached_routes:
        rt = cached_routes[unit_route_key]
        coords = rt.get("coords") or []
        if coords and haversine_m(coords[-1], destination) < 350:
            return {
                "coords": coords,
                "dist": int(rt.get("dist", haversine_m(origin, destination))),
                "dur": int(rt.get("dur", 180)),
                "source": "OSRM_CACHED",
            }

    # Try live OSRM street routing (strictly non-AI public road geometry, fast 1.6s timeout)
    url = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{origin[0]:.6f},{origin[1]:.6f};{destination[0]:.6f},{destination[1]:.6f}"
        "?overview=full&geometries=geojson"
    )
    try:
        r = httpx.get(url, timeout=1.6)
        if r.status_code == 200:
            j = r.json()
            if j.get("routes"):
                rt = j["routes"][0]
                return {
                    "coords": rt["geometry"]["coordinates"],
                    "dist": max(50, int(round(rt["distance"]))),
                    "dur": max(30, int(round(rt["duration"]))),
                    "source": "OSRM_LIVE",
                }
    except Exception as exc:
        logger.debug("OSRM live routing unavailable, using offline fallback: %s", exc)

    # Instant offline fallback (smooth 20-point interpolated path + urban road factor 1.32x)
    straight = haversine_m(origin, destination)
    road_dist = max(100, int(round(straight * 1.32)))
    # Emergency response speed ~38 km/h (~10.5 m/s)
    eta_sec = max(45, int(round(road_dist / 10.5)))
    pts = [
        [
            round(origin[0] + (destination[0] - origin[0]) * (i / 20.0), 6),
            round(origin[1] + (destination[1] - origin[1]) * (i / 20.0), 6),
        ]
        for i in range(21)
    ]
    return {
        "coords": pts,
        "dist": road_dist,
        "dur": eta_sec,
        "source": "OFFLINE_ESTIMATE",
    }
