
"""Seed 7 days of urban traffic baseline metrics for analytics_cache.

Writes data/historical_analytics_baseline.json:
  metric_type, node_or_segment_id, time_bucket (ISO 8601), value (dict)

Models Bengaluru diurnal flow: morning rush 08:00–10:30, evening rush
17:30–20:30, low late-night volumes, and inflated adjacent-camera travel
times so bottleneck detection has a delay baseline.

Pass --db-url to INSERT into PostgreSQL analytics_cache when available.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAMERAS_PATH = ROOT / "data" / "cameras.json"
OUTPUT_PATH = ROOT / "data" / "historical_analytics_baseline.json"

IST = timezone(timedelta(hours=5, minutes=30))

START_DAY = datetime(2026, 9, 17, 0, 0, 0, tzinfo=IST)
DAYS = 7
BUCKET_MINUTES = 30
NEIGHBOR_K = 5
RNG_SEED = 7
CBD_LAT, CBD_LON = 12.9716, 77.5946
FREEFLOW_FLOOR_KMH = 28.0
EARTH_R_KM = 6371.0

SCHEMA_KEYS = ("metric_type", "node_or_segment_id", "time_bucket", "value")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def load_cameras() -> list[dict]:
    if not CAMERAS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CAMERAS_PATH}. Run tools/generate_cameras.py first."
        )
    cameras = json.loads(CAMERAS_PATH.read_text(encoding="utf-8"))
    if not cameras:
        raise ValueError("cameras.json is empty")
    return cameras


def build_adjacency(cameras: list[dict], k: int = NEIGHBOR_K) -> dict[str, list[str]]:
    by_id = {c["id"]: c for c in cameras}
    ids = [c["id"] for c in cameras]
    graph: dict[str, set[str]] = {cid: set() for cid in ids}
    for cid in ids:
        others = []
        for oid in ids:
            if oid == cid:
                continue
            dist = haversine_km(
                by_id[cid]["lat"], by_id[cid]["lon"],
                by_id[oid]["lat"], by_id[oid]["lon"],
            )
            others.append((dist, oid))
        others.sort()
        for _, oid in others[:k]:
            graph[cid].add(oid)
            graph[oid].add(cid)
    return {cid: sorted(nbrs) for cid, nbrs in graph.items()}


def directed_segments(cameras: list[dict]) -> list[dict]:
    """One directed hop per adjacent camera pair, with free-flow travel time."""
    by_id = {c["id"]: c for c in cameras}
    adjacency = build_adjacency(cameras)
    seen: set[tuple[str, str]] = set()
    segments: list[dict] = []
    for src_id, nbrs in adjacency.items():
        src = by_id[src_id]
        for dst_id in nbrs:
            if src_id == dst_id or (src_id, dst_id) in seen:
                continue
            seen.add((src_id, dst_id))
            dst = by_id[dst_id]
            dist_km = max(0.08, haversine_km(src["lat"], src["lon"], dst["lat"], dst["lon"]))
            limit = min(float(src["speed_limit_kmh"]), float(dst["speed_limit_kmh"]))
            ff_kmh = max(FREEFLOW_FLOOR_KMH, min(limit, 50.0))
            src_cbd = haversine_km(src["lat"], src["lon"], CBD_LAT, CBD_LON)
            dst_cbd = haversine_km(dst["lat"], dst["lon"], CBD_LAT, CBD_LON)
            segments.append(
                {
                    "id": f"{src_id}->{dst_id}",
                    "from_id": src_id,
                    "to_id": dst_id,
                    "distance_km": dist_km,
                    "free_flow_s": (dist_km / ff_kmh) * 3600.0,
                    "inbound_cbd": dst_cbd < src_cbd,
                    "lane_count": min(int(src["lane_count"]), int(dst["lane_count"])),
                }
            )
    return segments


def is_weekend(ts: datetime) -> bool:
    return ts.weekday() >= 5


def demand_factor(ts: datetime) -> float:
    """Relative urban demand in [~0.08, ~1.35]. Rush windows match the spec."""
    minutes = ts.hour * 60 + ts.minute
    weekend = is_weekend(ts)

    def peak(center: float, half_width: float, amplitude: float) -> float:
        return amplitude * math.exp(-0.5 * ((minutes - center) / half_width) ** 2)


    base = 0.10

    if 0 <= minutes < 5 * 60:
        base = 0.08
    morning = peak(9 * 60 + 15, 70, 1.05)  # 08:00–10:30, centre ~09:15
    midday = peak(14 * 60, 150, 0.42)
    evening = peak(19 * 60, 85, 1.18)  # 17:30–20:30, centre ~19:00
    factor = base + morning + midday + evening
    if weekend:
        factor = 0.08 + 0.55 * morning + 0.85 * midday + 0.62 * evening
    return max(0.06, min(1.45, factor))


def congestion_multiplier(ts: datetime, inbound_cbd: bool) -> float:
    """Travel-time inflation vs free-flow. Directional CBD bias for bottleneck work."""
    demand = demand_factor(ts)
    minutes = ts.hour * 60 + ts.minute
    morning_rush = 8 * 60 <= minutes < 10 * 60 + 30
    evening_rush = 17 * 60 + 30 <= minutes < 20 * 60 + 30
    directional = 1.0
    if morning_rush and inbound_cbd:
        directional = 1.22
    elif morning_rush and not inbound_cbd:
        directional = 0.92
    elif evening_rush and not inbound_cbd:
        directional = 1.25
    elif evening_rush and inbound_cbd:
        directional = 0.94
    if is_weekend(ts):
        directional = 0.5 * directional + 0.5

    return 1.02 + 1.15 * (demand ** 1.4) * directional


def iso_bucket(ts: datetime) -> str:
    return ts.isoformat(timespec="minutes")


def generate_records(cameras: list[dict], rng: random.Random) -> list[dict]:
    segments = directed_segments(cameras)
    records: list[dict] = []
    buckets: list[datetime] = []
    cursor = START_DAY
    end = START_DAY + timedelta(days=DAYS)
    step = timedelta(minutes=BUCKET_MINUTES)
    while cursor < end:
        buckets.append(cursor)
        cursor += step

    for cam in cameras:
        lanes = int(cam["lane_count"])
        limit = float(cam["speed_limit_kmh"])

        base_count = 18.0 * lanes * (0.75 + 0.25 * (limit / 50.0))
        for ts in buckets:
            demand = demand_factor(ts)
            noise = rng.uniform(0.88, 1.12)
            count = max(0, int(round(base_count * demand * noise * (BUCKET_MINUTES / 15.0))))

            speed = limit * (0.42 + 0.50 * (1.0 - min(1.0, demand)))
            speed = max(12.0, min(limit, speed * rng.uniform(0.94, 1.06)))
            occupancy = min(92.0, 8.0 + 62.0 * demand * rng.uniform(0.92, 1.08))
            records.append(
                {
                    "metric_type": "node_flow",
                    "node_or_segment_id": cam["id"],
                    "time_bucket": iso_bucket(ts),
                    "value": {
                        "vehicle_count": count,
                        "avg_speed_kmh": round(speed, 2),
                        "occupancy_pct": round(occupancy, 2),
                        "lane_count": lanes,
                    },
                }
            )
            records.append(
                {
                    "metric_type": "segment_congestion",
                    "node_or_segment_id": cam["road_segment_id"],
                    "time_bucket": iso_bucket(ts),
                    "value": {
                        "congestion_index": round(min(1.0, demand * rng.uniform(0.9, 1.1)), 3),
                        "avg_speed_kmh": round(speed, 2),
                        "camera_id": cam["id"],
                    },
                }
            )

    for seg in segments:
        for ts in buckets:
            mult = congestion_multiplier(ts, seg["inbound_cbd"]) * rng.uniform(0.93, 1.07)
            mean_s = seg["free_flow_s"] * mult
            p50_s = mean_s * rng.uniform(0.94, 1.02)
            p95_s = mean_s * rng.uniform(1.18, 1.45)
            delay_s = max(0.0, mean_s - seg["free_flow_s"])
            sample = max(3, int(round(14 * demand_factor(ts) * seg["lane_count"] * rng.uniform(0.8, 1.2))))
            records.append(
                {
                    "metric_type": "segment_travel_time",
                    "node_or_segment_id": seg["id"],
                    "time_bucket": iso_bucket(ts),
                    "value": {
                        "mean_travel_time_s": round(mean_s, 2),
                        "p50_travel_time_s": round(p50_s, 2),
                        "p95_travel_time_s": round(p95_s, 2),
                        "free_flow_travel_time_s": round(seg["free_flow_s"], 2),
                        "delay_s": round(delay_s, 2),
                        "distance_km": round(seg["distance_km"], 4),
                        "sample_count": sample,
                        "from_camera_id": seg["from_id"],
                        "to_camera_id": seg["to_id"],
                    },
                }
            )

    records.sort(key=lambda r: (r["time_bucket"], r["metric_type"], r["node_or_segment_id"]))
    return records


def validate(records: list[dict], cameras: list[dict]) -> None:
    if not records:
        raise ValueError("No analytics records generated")
    for rec in records:
        missing = [k for k in SCHEMA_KEYS if k not in rec]
        if missing:
            raise ValueError(f"Missing keys {missing}")
        extra = [k for k in rec if k not in SCHEMA_KEYS]
        if extra:
            raise ValueError(f"Unexpected keys {extra}")
        if not isinstance(rec["metric_type"], str) or not rec["metric_type"]:
            raise TypeError("metric_type must be a non-empty str")
        if not isinstance(rec["node_or_segment_id"], str) or not rec["node_or_segment_id"]:
            raise TypeError("node_or_segment_id must be a non-empty str")
        datetime.fromisoformat(rec["time_bucket"])
        if not isinstance(rec["value"], dict) or not rec["value"]:
            raise TypeError("value must be a non-empty dict")

    days = {r["time_bucket"][:10] for r in records}
    if len(days) != DAYS:
        raise ValueError(f"Expected {DAYS} distinct days, got {sorted(days)}")

    cam_ids = {c["id"] for c in cameras}
    seg_ids = {c["road_segment_id"] for c in cameras}
    flow_ids = {r["node_or_segment_id"] for r in records if r["metric_type"] == "node_flow"}
    cong_ids = {r["node_or_segment_id"] for r in records if r["metric_type"] == "segment_congestion"}
    hop_ids = {r["node_or_segment_id"] for r in records if r["metric_type"] == "segment_travel_time"}
    if flow_ids != cam_ids:
        raise ValueError("node_flow ids do not match camera ids")
    if cong_ids != seg_ids:
        raise ValueError("segment_congestion ids do not match road_segment_id values")
    if not hop_ids:
        raise ValueError("No adjacent-camera travel_time records")

    sample_cam = next(iter(sorted(cam_ids)))
    flows = [r for r in records if r["metric_type"] == "node_flow" and r["node_or_segment_id"] == sample_cam]

    def mean_count(pred) -> float:
        vals = [r["value"]["vehicle_count"] for r in flows if pred(datetime.fromisoformat(r["time_bucket"]))]
        return sum(vals) / max(1, len(vals))

    morning = mean_count(lambda t: 8 <= t.hour < 10 or (t.hour == 10 and t.minute < 30))
    night = mean_count(lambda t: t.hour < 5)
    evening = mean_count(lambda t: (t.hour == 17 and t.minute >= 30) or 18 <= t.hour < 20 or (t.hour == 20 and t.minute < 30))
    if not (morning > 3 * night and evening > 3 * night):
        raise ValueError(
            f"Rush-hour peaks are too weak vs late night (morning={morning:.1f}, evening={evening:.1f}, night={night:.1f})"
        )

    hops = [r for r in records if r["metric_type"] == "segment_travel_time"]
    rush_delay = [r["value"]["delay_s"] for r in hops if _in_rush(datetime.fromisoformat(r["time_bucket"]))]
    night_delay = [r["value"]["delay_s"] for r in hops if datetime.fromisoformat(r["time_bucket"]).hour < 5]
    if sum(rush_delay) / len(rush_delay) <= sum(night_delay) / len(night_delay):
        raise ValueError("Rush-hour segment delays are not higher than late-night delays")


def _in_rush(ts: datetime) -> bool:
    minutes = ts.hour * 60 + ts.minute
    return (8 * 60 <= minutes < 10 * 60 + 30) or (17 * 60 + 30 <= minutes < 20 * 60 + 30)


def seed_postgres(db_url: str, records: list[dict]) -> None:
    """Insert into analytics_cache. Does not CREATE the table (owned by Saanvi)."""
    rows = [
        (r["metric_type"], r["node_or_segment_id"], r["time_bucket"], r["value"])
        for r in records
    ]
    try:
        import psycopg2
        from psycopg2.extras import Json, execute_batch
    except ImportError:
        psycopg2 = None  # type: ignore[assignment]
    else:
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                execute_batch(
                    cur,
                    """
                    INSERT INTO analytics_cache
                        (metric_type, node_or_segment_id, time_bucket, value)
                    VALUES (%s, %s, %s, %s)
                    """,
                    [(m, n, t, Json(v)) for m, n, t, v in rows],
                    page_size=500,
                )
            conn.commit()
        finally:
            conn.close()
        print(f"Seeded {len(rows)} rows into analytics_cache via psycopg2")
        return

    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise SystemExit(
            "PostgreSQL seeding requires psycopg2 or psycopg. "
            "Install one of them, or omit --db-url to write JSON only."
        ) from exc

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO analytics_cache
                    (metric_type, node_or_segment_id, time_bucket, value)
                VALUES (%s, %s, %s, %s)
                """,
                [(m, n, t, Jsonb(v)) for m, n, t, v in rows],
            )
        conn.commit()
    print(f"Seeded {len(rows)} rows into analytics_cache via psycopg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed 7-day historical analytics baseline")
    parser.add_argument(
        "--db-url",
        default=None,
        help="PostgreSQL URL (e.g. postgresql://user:pass@localhost:5432/eetal) "
        "to INSERT into analytics_cache",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(RNG_SEED)
    cameras = load_cameras()
    records = generate_records(cameras, rng)
    validate(records, cameras)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(records) + "\n", encoding="utf-8")

    types = {}
    for rec in records:
        types[rec["metric_type"]] = types.get(rec["metric_type"], 0) + 1
    days = sorted({r["time_bucket"][:10] for r in records})
    print(f"Wrote {len(records)} analytics_cache rows to {OUTPUT_PATH}")
    print(f"Days: {days[0]} → {days[-1]} ({len(days)} days, {BUCKET_MINUTES}-min buckets, IST)")
    print("Metric counts: " + ", ".join(f"{k}={v}" for k, v in sorted(types.items())))
    print(f"Cameras: {len(cameras)}  |  travel-time hops: {types.get('segment_travel_time', 0) // (DAYS * 24 * 60 // BUCKET_MINUTES)}")

    if args.db_url:
        seed_postgres(args.db_url, records)


if __name__ == "__main__":
    main()
