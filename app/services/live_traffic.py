"""
Live road-traffic congestion for the dashboard's city heatmap.

For a fixed set of sample points across Delhi (our six camera sites plus major junctions), asks an
external live-traffic feed for the current speed vs. the free-flow speed of the nearest road segment,
and turns the slowdown into a congestion score. This is city-wide road data from outside our camera
network -- it is served on its own endpoint and never mixed into raw_reads / the camera analytics.

Quota: the feed's free tier allows 2,500 data requests/day. With 24 sample points, one refresh costs
24 requests, so results are cached for CACHE_TTL_SECONDS (20 min => at most 72 refreshes = 1,728
requests/day, leaving headroom for testing). main.py's recorder refreshes on that same cadence and stores
a city-wide snapshot per refresh (the dashboard's trend chart); viewers just read the cache.

Set LIVE_TRAFFIC_API_KEY to enable; without it every function here reports "not_configured" cleanly.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

import httpx

API_KEY = os.getenv("LIVE_TRAFFIC_API_KEY", "")
FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
TILE_URL = "https://api.tomtom.com/traffic/map/4/tile/flow/relative/{z}/{x}/{y}.png"

CACHE_TTL_SECONDS = 20 * 60
MAX_CONGESTION = 0.6  # a road running 60%+ below free-flow speed counts as fully congested (intensity 1.0)

# (name, lat, lon): the six camera sites first, then major junctions spread across the city.
SAMPLE_POINTS = [
    ("Connaught Place", 28.6315, 77.2167),
    ("India Gate", 28.6129, 77.2295),
    ("Chandni Chowk", 28.6506, 77.2334),
    ("Karol Bagh", 28.6519, 77.1909),
    ("Lajpat Nagar", 28.5677, 77.2431),
    ("Dwarka Sector 21", 28.5921, 77.0460),
    ("ITO", 28.6285, 77.2410),
    ("Kashmere Gate", 28.6675, 77.2287),
    ("Ashram Chowk", 28.5710, 77.2610),
    ("AIIMS", 28.5672, 77.2100),
    ("Nehru Place", 28.5494, 77.2513),
    ("Saket", 28.5245, 77.2066),
    ("Dhaula Kuan", 28.5914, 77.1618),
    ("Rajouri Garden", 28.6492, 77.1216),
    ("Azadpur", 28.7076, 77.1751),
    ("Anand Vihar", 28.6469, 77.3161),
    ("Laxmi Nagar", 28.6304, 77.2773),
    ("Akshardham", 28.6127, 77.2773),
    ("Mahipalpur", 28.5451, 77.1264),
    ("Janakpuri", 28.6219, 77.0878),
    ("Pitampura", 28.7031, 77.1316),
    ("Sarai Kale Khan", 28.5880, 77.2580),
    ("Shahdara", 28.6710, 77.2890),
    ("Mayur Vihar", 28.6090, 77.2960),
]

_cache: dict = {"points": None, "fetched_at": 0.0}
_lock = asyncio.Lock()
_tile_client = httpx.AsyncClient(timeout=10.0)


async def _fetch_point(client: httpx.AsyncClient, sem: asyncio.Semaphore, name: str, lat: float, lon: float):
    """Returns (point_or_None, http_status_or_None). A point with no nearby road just returns None."""
    async with sem:
        try:
            resp = await client.get(FLOW_URL, params={"point": f"{lat},{lon}", "unit": "KMPH", "key": API_KEY})
        except httpx.HTTPError:
            return None, None
    if resp.status_code != 200:
        return None, resp.status_code
    try:
        seg = resp.json()["flowSegmentData"]
        current, free_flow = float(seg["currentSpeed"]), float(seg["freeFlowSpeed"])
    except (KeyError, ValueError, TypeError):
        return None, None

    closure = bool(seg.get("roadClosure"))
    # A closure flag alone doesn't mean a standstill (partial/lane closures still report moving traffic),
    # so only a zero current speed on a closed segment counts as fully blocked.
    if closure and current == 0:
        congestion = 1.0
    elif free_flow > 0:
        congestion = min(1.0, max(0.0, 1.0 - current / free_flow))
    else:
        congestion = 0.0
    return {
        "name": name,
        "lat": lat,
        "lon": lon,
        "current_speed_kmh": round(current),
        "free_flow_speed_kmh": round(free_flow),
        "congestion": round(congestion, 2),
        "intensity": round(min(1.0, congestion / MAX_CONGESTION), 2),
        "road_closure": closure,
    }, 200


async def _refresh_points() -> list[dict]:
    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(*(_fetch_point(client, sem, n, la, lo) for n, la, lo in SAMPLE_POINTS))
    return [p for p, _ in results if p is not None]


def city_summary(points: list[dict]) -> dict:
    """City-wide roll-up of one refresh: mean current/free-flow speed and mean congestion across points."""
    n = len(points)
    return {
        "avg_speed_kmh": round(sum(p["current_speed_kmh"] for p in points) / n, 1),
        "avg_free_flow_kmh": round(sum(p["free_flow_speed_kmh"] for p in points) / n, 1),
        "congestion_pct": round(100 * sum(p["congestion"] for p in points) / n, 1),
        "point_count": n,
    }


async def get_live_traffic() -> dict:
    if not API_KEY:
        return {"available": False, "reason": "not_configured", "points": []}

    async with _lock:
        age = time.time() - _cache["fetched_at"]
        if _cache["points"] is None or age > CACHE_TTL_SECONDS:
            points = await _refresh_points()
            if points:
                _cache["points"], _cache["fetched_at"] = points, time.time()
            elif _cache["points"] is None:
                return {"available": False, "reason": "upstream_error", "points": []}
            # else: refresh failed (quota / outage) -- keep serving the last good data, flagged stale below

        age = time.time() - _cache["fetched_at"]
        return {
            "available": True,
            "stale": age > CACHE_TTL_SECONDS,
            "updated_at": datetime.fromtimestamp(_cache["fetched_at"], tz=timezone.utc).isoformat(),
            "city": city_summary(_cache["points"]),
            "points": _cache["points"],
        }


async def fetch_tile(z: int, x: int, y: int) -> bytes | None:
    """One raster tile of live road colouring, proxied so the API key never reaches the browser."""
    if not API_KEY:
        return None
    try:
        resp = await _tile_client.get(TILE_URL.format(z=z, x=x, y=y), params={"key": API_KEY})
    except httpx.HTTPError:
        return None
    return resp.content if resp.status_code == 200 else None
