from datetime import datetime, timedelta, timezone

CAMERA_OFFLINE_AFTER_MINUTES = 5

async def compute_density(conn, window_minutes: int = 15):
    """Aggregates vehicle count per camera_id within the rolling time window."""
    query = """
        SELECT camera_id, COUNT(DISTINCT track_id) as vehicle_count,
               CASE
                   WHEN COUNT(DISTINCT track_id) > 50 THEN 'HIGH'
                   WHEN COUNT(DISTINCT track_id) > 20 THEN 'MEDIUM'
                   ELSE 'LOW'
               END as density_level
        FROM raw_reads
        WHERE frame_ts >= NOW() - $1::interval
        GROUP BY camera_id;
    """
    # asyncpg encodes an `interval` parameter from a Python timedelta, not a string
    records = await conn.fetch(query, timedelta(minutes=window_minutes))
    return [dict(r) for r in records]

async def compute_od_matrix(conn, hour: int = None, date_str: str = None):
    """Finds vehicle trajectories between Camera A and Camera B."""
    # This simplified query finds the first and last camera seen for each vehicle track today
    query = """
        WITH trip_ends AS (
            SELECT track_id, 
                   FIRST_VALUE(camera_id) OVER (PARTITION BY track_id ORDER BY frame_ts ASC) as origin,
                   FIRST_VALUE(camera_id) OVER (PARTITION BY track_id ORDER BY frame_ts DESC) as destination
            FROM raw_reads
            WHERE frame_ts >= CURRENT_DATE
        )
        SELECT origin, destination, COUNT(DISTINCT track_id) as trip_count
        FROM trip_ends
        WHERE origin != destination
        GROUP BY origin, destination
        ORDER BY trip_count DESC;
    """
    records = await conn.fetch(query)
    return [dict(r) for r in records]

async def compute_heatmap(conn, time_bucket: str = None):
    """Aggregates detection density into a GeoJSON FeatureCollection."""
    query = """
        SELECT c.id, c.lat, c.lon, COUNT(r.id) as read_count
        FROM cameras c
        LEFT JOIN raw_reads r ON c.id = r.camera_id
        WHERE r.frame_ts >= NOW() - INTERVAL '1 hour'
        GROUP BY c.id, c.lat, c.lon;
    """
    records = await conn.fetch(query)
    
    features = []
    max_reads = max([r['read_count'] for r in records]) if records else 1
    
    for r in records:
        intensity = r['read_count'] / max_reads
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r['lon'], r['lat']]},
            "properties": {
                "camera_id": r['id'],
                "density_intensity": round(intensity, 2),
                "raw_count": r['read_count']
            }
        })
        
    return {
        "type": "FeatureCollection",
        "features": features
    }

async def compute_cameras(conn):
    """Returns every camera with a live status/traffic reading derived from recent raw_reads."""
    query = """
        SELECT c.id, c.name, c.lat, c.lon,
               MAX(r.frame_ts) as last_seen,
               COUNT(r.id) FILTER (WHERE r.frame_ts >= NOW() - INTERVAL '15 minutes') as recent_reads
        FROM cameras c
        LEFT JOIN raw_reads r ON r.camera_id = c.id
        GROUP BY c.id, c.name, c.lat, c.lon
        ORDER BY c.id;
    """
    records = await conn.fetch(query)
    max_recent = max([r['recent_reads'] for r in records], default=0) or 1

    cameras = []
    for r in records:
        is_online = r['last_seen'] is not None and (
            datetime.now(r['last_seen'].tzinfo) - r['last_seen']
        ).total_seconds() / 60.0 <= CAMERA_OFFLINE_AFTER_MINUTES

        recent = r['recent_reads']
        density_level = 'HIGH' if recent > 50 else 'MEDIUM' if recent > 20 else 'LOW'

        cameras.append({
            "id": r['id'],
            "name": r['name'],
            "lat": r['lat'],
            "lon": r['lon'],
            "status": "Online" if is_online else "Offline",
            "last_seen": r['last_seen'].isoformat() if r['last_seen'] else None,
            "recent_reads": recent,
            "density_level": density_level,
            "intensity": round(recent / max_recent, 2)
        })
    return cameras

async def compute_summary(conn):
    """City-wide KPI aggregate for the dashboard header row."""
    vehicles_today = await conn.fetchval("""
        SELECT COUNT(DISTINCT track_id) FROM raw_reads WHERE frame_ts >= CURRENT_DATE;
    """)
    vehicles_yesterday = await conn.fetchval("""
        SELECT COUNT(DISTINCT track_id) FROM raw_reads
        WHERE frame_ts >= CURRENT_DATE - INTERVAL '1 day' AND frame_ts < CURRENT_DATE;
    """)

    # Average speed across consecutive camera-to-camera hops today, using PostGIS
    # sphere distance between camera geoms and the elapsed time between reads.
    avg_speed = await conn.fetchval("""
        WITH ordered AS (
            SELECT track_id, camera_id, frame_ts,
                   LEAD(camera_id) OVER w as next_camera,
                   LEAD(frame_ts) OVER w as next_ts
            FROM raw_reads
            WHERE frame_ts >= CURRENT_DATE
            WINDOW w AS (PARTITION BY track_id ORDER BY frame_ts ASC)
        ),
        hops AS (
            SELECT o.track_id,
                   ST_DistanceSphere(c1.geom, c2.geom) / 1000.0 as dist_km,
                   EXTRACT(EPOCH FROM (o.next_ts - o.frame_ts)) / 3600.0 as hours
            FROM ordered o
            JOIN cameras c1 ON c1.id = o.camera_id
            JOIN cameras c2 ON c2.id = o.next_camera
            WHERE o.next_camera IS NOT NULL AND o.next_camera != o.camera_id
              AND o.next_ts > o.frame_ts
        )
        SELECT AVG(dist_km / hours) FROM hops
        WHERE (dist_km / hours) BETWEEN 1 AND 140;
    """)

    active_alerts = await conn.fetchval("""
        SELECT COUNT(*) FROM alerts WHERE status != 'DISMISSED';
    """)

    camera_counts = await conn.fetchrow("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (
                   WHERE camera_id IN (
                       SELECT DISTINCT camera_id FROM raw_reads
                       WHERE frame_ts >= NOW() - INTERVAL '5 minutes'
                   )
               ) as online
        FROM (SELECT id as camera_id FROM cameras) c;
    """)

    return {
        "vehicles_tracked_today": vehicles_today or 0,
        "vehicles_tracked_yesterday": vehicles_yesterday or 0,
        "avg_speed_kmh": round(avg_speed, 1) if avg_speed else None,
        "active_alerts": active_alerts or 0,
        "cameras_online": camera_counts['online'] or 0,
        "cameras_total": camera_counts['total'] or 0,
    }

async def compute_bottlenecks(conn, window_minutes: int = 60, threshold_factor: float = 1.5):
    """
    Compares live camera-to-camera transit times against the seeded historical
    baseline (analytics_cache, metric_type='BOTTLENECK_BASELINE') for the
    current hour-of-day, and flags segments running slower than expected by >= threshold_factor.
    """
    baseline_rows = await conn.fetch("""
        SELECT node_or_segment_id,
               AVG((value->>'avg_travel_time_sec')::float) as expected_sec
        FROM analytics_cache
        WHERE metric_type = 'BOTTLENECK_BASELINE'
          AND EXTRACT(HOUR FROM time_bucket) = EXTRACT(HOUR FROM NOW())
        GROUP BY node_or_segment_id;
    """)
    baseline = {r['node_or_segment_id']: r['expected_sec'] for r in baseline_rows}

    if not baseline:
        return []

    current_rows = await conn.fetch("""
        WITH ordered AS (
            SELECT track_id, camera_id, frame_ts,
                   LEAD(camera_id) OVER w as next_camera,
                   LEAD(frame_ts) OVER w as next_ts
            FROM raw_reads
            WHERE frame_ts >= NOW() - ($1 || ' minutes')::interval
            WINDOW w AS (PARTITION BY track_id ORDER BY frame_ts ASC)
        )
        SELECT camera_id || '->' || next_camera as segment,
               AVG(EXTRACT(EPOCH FROM (next_ts - frame_ts)))::float as current_sec
        FROM ordered
        WHERE next_camera IS NOT NULL AND next_camera != camera_id
          AND next_ts > frame_ts
        GROUP BY segment;
    """, str(window_minutes))

    bottlenecks = []
    for r in current_rows:
        expected = baseline.get(r['segment'])
        if expected is None:
            continue
        # Flag if current transit time exceeds baseline by >= threshold_factor (1.5x)
        if r['current_sec'] >= (expected * threshold_factor):
            bottlenecks.append({
                "segment": r['segment'],
                "expected_sec": round(expected, 1),
                "current_sec": round(r['current_sec'], 1),
                "congestion_factor": round(r['current_sec'] / expected, 2)
            })

    bottlenecks.sort(key=lambda b: b['current_sec'] - b['expected_sec'], reverse=True)
    return bottlenecks

async def compute_timeseries(conn, window_minutes: int = 120, bucket_minutes: int = 10):
    """Buckets raw_reads into fixed-width time windows for the dashboard trend chart."""
    count_rows = await conn.fetch("""
        SELECT date_trunc('minute', frame_ts) - make_interval(mins => (extract(minute from frame_ts)::int % $2)) as bucket,
               COUNT(DISTINCT track_id) as vehicle_count
        FROM raw_reads
        WHERE frame_ts >= NOW() - make_interval(mins => $1)
        GROUP BY bucket
        ORDER BY bucket;
    """, window_minutes, bucket_minutes)

    speed_rows = await conn.fetch("""
        WITH ordered AS (
            SELECT track_id, camera_id, frame_ts,
                   LEAD(camera_id) OVER w as next_camera,
                   LEAD(frame_ts) OVER w as next_ts
            FROM raw_reads
            WHERE frame_ts >= NOW() - make_interval(mins => $1)
            WINDOW w AS (PARTITION BY track_id ORDER BY frame_ts ASC)
        ),
        hops AS (
            SELECT date_trunc('minute', o.frame_ts) - make_interval(mins => (extract(minute from o.frame_ts)::int % $2)) as bucket,
                   ST_DistanceSphere(c1.geom, c2.geom) / 1000.0 as dist_km,
                   EXTRACT(EPOCH FROM (o.next_ts - o.frame_ts)) / 3600.0 as hours
            FROM ordered o
            JOIN cameras c1 ON c1.id = o.camera_id
            JOIN cameras c2 ON c2.id = o.next_camera
            WHERE o.next_camera IS NOT NULL AND o.next_camera != o.camera_id
              AND o.next_ts > o.frame_ts
        )
        SELECT bucket, AVG(dist_km / hours) as avg_speed_kmh
        FROM hops
        WHERE (dist_km / hours) BETWEEN 1 AND 140
        GROUP BY bucket
        ORDER BY bucket;
    """, window_minutes, bucket_minutes)

    speed_by_bucket = {r['bucket']: r['avg_speed_kmh'] for r in speed_rows}
    counts_by_bucket = {r['bucket']: r['vehicle_count'] for r in count_rows}

    # Fill every bucket in the window (even empty ones) so the chart has no gaps.
    now = datetime.now(timezone.utc)
    num_buckets = max(window_minutes // bucket_minutes, 1)
    start = now - timedelta(minutes=window_minutes)
    aligned_start = start - timedelta(minutes=start.minute % bucket_minutes, seconds=start.second, microseconds=start.microsecond)

    result = []
    for i in range(num_buckets + 1):
        bucket_dt = aligned_start + timedelta(minutes=i * bucket_minutes)
        if bucket_dt > now:
            break
        avg_speed = speed_by_bucket.get(bucket_dt)
        result.append({
            "bucket": bucket_dt.isoformat(),
            "vehicle_count": counts_by_bucket.get(bucket_dt, 0),
            "avg_speed_kmh": round(avg_speed, 1) if avg_speed else None,
        })
    return result

async def compute_camera_recent_reads(conn, camera_id: str, limit: int = 8):
    """Recent raw_reads for a single camera, for the Dashboard's camera detail panel."""
    records = await conn.fetch("""
        SELECT plate_text, confidence, frame_ts, image_ref
        FROM raw_reads
        WHERE camera_id = $1
        ORDER BY frame_ts DESC
        LIMIT $2;
    """, camera_id, limit)
    return [
        {
            "plate_text": r['plate_text'],
            "confidence": r['confidence'],
            "frame_ts": r['frame_ts'].isoformat(),
            "image_ref": r['image_ref'],
        }
        for r in records
    ]