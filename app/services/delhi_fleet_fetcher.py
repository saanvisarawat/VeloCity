"""
Keeps the Delhi vehicle-fleet trend data (see external_reference.py) fresh by
periodically re-fetching the source CSV from OpenCity/portal.delhi.gov.in.

This is deliberately NOT done on every request to GET /api/v1/external/
delhi-vehicle-fleet-trend — that endpoint always serves from the in-memory
cache built here, so a slow/down upstream site never slows down or breaks
the dashboard. A background task refreshes the cache on startup and then
every REFRESH_INTERVAL_SECONDS.

If a fetch fails, or the CSV comes back in a shape we don't recognize (the
site restructures the file, a network proxy returns an HTML error page,
etc.), we log it and keep serving the last-known-good data rather than ever
serving corrupt/nonsensical numbers. The very first "last-known-good" value,
before any fetch has ever succeeded, is the manually-verified static snapshot
in external_reference.py.
"""
import asyncio
import csv
import io
from datetime import datetime, timezone

import httpx

from services.external_reference import DELHI_VEHICLE_FLEET_TREND, DELHI_VEHICLE_FLEET_TREND_SOURCE

CSV_URL = (
    "https://data.opencity.in/dataset/12106167-8fbb-44d5-9466-ede5517c3d15/"
    "resource/d7af951d-bdab-46f3-a234-db6fec96ba68/download/"
    "d7af951d-bdab-46f3-a234-db6fec96ba68.csv"
)
REFRESH_INTERVAL_SECONDS = 24 * 60 * 60  # daily

ROW_KEY_MAP = {
    "Cars and Jeeps": "cars_and_jeeps",
    "Motor Cycles and Scooters": "motorcycles_scooters",
    "Auto Rickshaws": "auto_rickshaws",
    "Taxis": "taxis",
    "Buses": "buses",
    "Other Passenger Vehicles [E-Rickshaw(p)]": "e_rickshaws_other",
    "Ambulances": "ambulances",
    "Tractors, All goods Vehicles & Others": "tractors_goods_others",
    "Total Vehicles Plying": "total_vehicles_plying",
    "No. of Vehicles taken NOC": "noc_taken",
    "No. of Vehicles Deregistered": "deregistered_cumulative",
    "No. of Vehicles Scrapped": "scrapped_cumulative",
}
REQUIRED_KEYS = {"cars_and_jeeps", "motorcycles_scooters", "total_vehicles_plying"}



_cache = {
    "years": DELHI_VEHICLE_FLEET_TREND,
    "source": DELHI_VEHICLE_FLEET_TREND_SOURCE["name"],
    "source_url": DELHI_VEHICLE_FLEET_TREND_SOURCE["url"],
    "last_fetched_at": None,
    "is_live": False,
}

def _parse_value(raw):
    raw = (raw or "").strip()
    if not raw or raw.upper() == "NA":
        return None
    try:
        return int(raw.replace(",", ""))
    except ValueError:
        return None

def _parse_csv(text):
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows or len(rows) < 2:
        raise ValueError("CSV has no data rows")

    header = [h.strip() for h in rows[0]]
    fiscal_years = header[1:]
    if len(fiscal_years) < 3:
        raise ValueError(f"Expected multiple year columns, got {len(fiscal_years)}")

    by_year = [{"fiscal_year": fy} for fy in fiscal_years]

    matched_keys = set()
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        row_name = row[0].strip()
        key = ROW_KEY_MAP.get(row_name)
        if not key:
            continue
        matched_keys.add(key)
        values = row[1:]
        for i, fy_entry in enumerate(by_year):
            fy_entry[key] = _parse_value(values[i]) if i < len(values) else None

    missing = REQUIRED_KEYS - matched_keys
    if missing:
        raise ValueError(f"CSV structure changed — missing expected rows: {missing}")

    for entry in by_year:
        total = entry.get("total_vehicles_plying")
        if total is not None and not (1_000_000 <= total <= 50_000_000):
            raise ValueError(f"Sanity check failed: total_vehicles_plying={total} for {entry['fiscal_year']} out of plausible range")



    return [e for e in by_year if e.get("total_vehicles_plying") is not None]

async def refresh_fleet_data():
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(CSV_URL)
            response.raise_for_status()
        parsed = _parse_csv(response.content.decode("utf-8-sig"))
        if len(parsed) < 3:
            raise ValueError(f"Only parsed {len(parsed)} usable year rows — too few to trust")

        _cache["years"] = parsed
        _cache["last_fetched_at"] = datetime.now(timezone.utc).isoformat()
        _cache["is_live"] = True
        print(f"[delhi_fleet_fetcher] Refreshed {len(parsed)} years from OpenCity CSV.")
    except Exception as e:

        print(f"[delhi_fleet_fetcher] Refresh failed, keeping cached data: {e}")

async def start_background_refresh():
    while True:
        await refresh_fleet_data()
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)

def get_cached_fleet_data():
    return _cache
