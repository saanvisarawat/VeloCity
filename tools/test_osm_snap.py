
"""Standalone OSM road-snap / routing evaluation between two camera nodes.

Primary: public OSRM driving route (snaps coordinates onto the OSM graph).
Optional: osmnx + networkx local graph shortest-path if those packages exist
          and OSRM is unreachable.
Fallback: great-circle (haversine / geopy geodesic) interpolation.

Prints a GeoJSON LineString plus route distance and estimated driving duration.
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAMERAS_PATH = ROOT / "data" / "cameras.json"


OSRM_BASE = "https://router.project-osrm.org/route/v1/driving"
OSRM_TIMEOUT_S = 20

EARTH_R_KM = 6371.0

FALLBACK_SPEED_KMH = 35.0
INTERP_POINTS = 24


DEFAULT_ORIGIN = "cam_019"  # Race Course Road / Chalukya Circle
DEFAULT_DEST = "cam_012"  # Halasuru Metro / Old Madras Road


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    try:
        from geopy.distance import geodesic  # spec optional dependency

        return float(geodesic((lat1, lon1), (lat2, lon2)).kilometers)
    except Exception:
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
        return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def load_cameras() -> dict[str, dict]:
    if not CAMERAS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CAMERAS_PATH}. Run tools/generate_cameras.py first."
        )
    cameras = json.loads(CAMERAS_PATH.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in cameras}
    if not by_id:
        raise ValueError("cameras.json is empty")
    return by_id


def pick_camera(by_id: dict[str, dict], camera_id: str) -> dict:
    if camera_id not in by_id:
        known = ", ".join(sorted(by_id))
        raise KeyError(f"Unknown camera {camera_id}. Known ids: {known}")
    return by_id[camera_id]


def geojson_linestring(coordinates_lonlat: list[list[float]]) -> dict:
    if len(coordinates_lonlat) < 2:
        raise ValueError("LineString requires at least two positions")
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates_lonlat,
        },
    }


def path_length_km(coordinates_lonlat: list[list[float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coordinates_lonlat, coordinates_lonlat[1:]):
        total += haversine_km(lat1, lon1, lat2, lon2)
    return total


def interpolate_great_circle(
    lat1: float, lon1: float, lat2: float, lon2: float, n: int = INTERP_POINTS
) -> list[list[float]]:
    """Uniform interpolation on the unit sphere (lon, lat) GeoJSON order."""
    phi1, lam1 = math.radians(lat1), math.radians(lon1)
    phi2, lam2 = math.radians(lat2), math.radians(lon2)
    x1, y1, z1 = math.cos(phi1) * math.cos(lam1), math.cos(phi1) * math.sin(lam1), math.sin(phi1)
    x2, y2, z2 = math.cos(phi2) * math.cos(lam2), math.cos(phi2) * math.sin(lam2), math.sin(phi2)
    coords: list[list[float]] = []
    for i in range(n):
        t = i / (n - 1)
        x, y, z = x1 + t * (x2 - x1), y1 + t * (y2 - y1), z1 + t * (z2 - z1)
        norm = math.sqrt(x * x + y * y + z * z) or 1.0
        x, y, z = x / norm, y / norm, z / norm
        lat = math.degrees(math.asin(max(-1.0, min(1.0, z))))
        lon = math.degrees(math.atan2(y, x))
        coords.append([lon, lat])
    return coords


def _fetch_json(url: str) -> dict:
    """GET JSON; urllib first, then curl if TLS handshake fails (macOS system Python)."""
    req = urllib.request.Request(url, headers={"User-Agent": "eetal-test-osm-snap/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=OSRM_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        import subprocess

        completed = subprocess.run(
            [
                "curl",
                "-fsS",
                "--max-time",
                str(OSRM_TIMEOUT_S),
                "-A",
                "eetal-test-osm-snap/1.0",
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"urllib failed ({exc}); curl failed: {completed.stderr.strip() or completed.returncode}"
            ) from exc
        return json.loads(completed.stdout)


def route_osrm(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson"})
    url = f"{OSRM_BASE}/{lon1},{lat1};{lon2},{lat2}?{query}"
    payload = _fetch_json(url)
    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise RuntimeError(f"OSRM returned {payload.get('code')!r}")
    route = payload["routes"][0]
    geometry = route["geometry"]
    if geometry.get("type") != "LineString":
        raise RuntimeError("OSRM geometry is not a LineString")
    coords = geometry["coordinates"]
    distance_m = float(route["distance"])
    duration_s = float(route["duration"])
    feature = geojson_linestring(coords)
    feature["properties"] = {
        "source": "osrm",
        "profile": "driving",
        "distance_m": distance_m,
        "duration_s": duration_s,
    }
    return {
        "feature": feature,
        "distance_km": distance_m / 1000.0,
        "duration_s": duration_s,
        "source": "osrm",
    }


def route_osmnx(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    import networkx as nx
    import osmnx as ox

    mid_lat = (lat1 + lat2) / 2.0
    mid_lon = (lon1 + lon2) / 2.0
    dist_m = haversine_km(lat1, lon1, lat2, lon2) * 1000.0
    pad_m = max(1500.0, dist_m * 0.6 + 800.0)
    graph = ox.graph_from_point((mid_lat, mid_lon), dist=pad_m, network_type="drive")
    orig = ox.distance.nearest_nodes(graph, lon1, lat1)
    dest = ox.distance.nearest_nodes(graph, lon2, lat2)
    node_path = nx.shortest_path(graph, orig, dest, weight="length")
    coords = [[graph.nodes[n]["x"], graph.nodes[n]["y"]] for n in node_path]
    length_m = float(nx.path_weight(graph, node_path, weight="length"))
    duration_s = (length_m / 1000.0) / FALLBACK_SPEED_KMH * 3600.0
    feature = geojson_linestring(coords)
    feature["properties"] = {
        "source": "osmnx_networkx",
        "distance_m": length_m,
        "duration_s": duration_s,
    }
    return {
        "feature": feature,
        "distance_km": length_m / 1000.0,
        "duration_s": duration_s,
        "source": "osmnx_networkx",
    }


def route_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    coords = interpolate_great_circle(lat1, lon1, lat2, lon2)
    distance_km = path_length_km(coords)
    duration_s = (distance_km / FALLBACK_SPEED_KMH) * 3600.0
    feature = geojson_linestring(coords)
    feature["properties"] = {
        "source": "haversine_interpolation",
        "assumed_speed_kmh": FALLBACK_SPEED_KMH,
        "distance_m": distance_km * 1000.0,
        "duration_s": duration_s,
    }
    return {
        "feature": feature,
        "distance_km": distance_km,
        "duration_s": duration_s,
        "source": "haversine_interpolation",
    }


def compute_route(lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
    errors: list[str] = []
    try:
        return route_osrm(lat1, lon1, lat2, lon2)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError, OSError) as exc:
        errors.append(f"OSRM: {exc}")

    try:
        return route_osmnx(lat1, lon1, lat2, lon2)
    except ImportError as exc:
        errors.append(f"osmnx/networkx not installed: {exc}")
    except Exception as exc:  # graph download / snap failures
        errors.append(f"osmnx: {exc}")

    result = route_haversine(lat1, lon1, lat2, lon2)
    result["fallback_reasons"] = errors
    return result


def format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, sec = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {sec:02d}s"
    return f"{minutes}m {sec:02d}s"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snap two camera coordinates to an OSM driving path"
    )
    parser.add_argument("--origin", default=DEFAULT_ORIGIN, help="Origin camera id")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="Destination camera id")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    by_id = load_cameras()
    origin = pick_camera(by_id, args.origin)
    dest = pick_camera(by_id, args.dest)

    print(f"Origin      {origin['id']}  {origin['name']}")
    print(f"             ({origin['lat']}, {origin['lon']})")
    print(f"Destination {dest['id']}  {dest['name']}")
    print(f"             ({dest['lat']}, {dest['lon']})")
    print()

    result = compute_route(origin["lat"], origin["lon"], dest["lat"], dest["lon"])
    feature = result["feature"]
    feature["properties"].update(
        {
            "origin_camera_id": origin["id"],
            "dest_camera_id": dest["id"],
        }
    )

    print(json.dumps(feature, indent=2))
    print()
    print(f"Route source : {result['source']}")
    print(f"Distance     : {result['distance_km']:.3f} km")
    print(f"Duration     : {format_duration(result['duration_s'])} ({result['duration_s']:.1f} s)")
    if result.get("fallback_reasons"):
        print("Fallback notes:")
        for note in result["fallback_reasons"]:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
