from fastapi import FastAPI, File, Form, HTTPException, BackgroundTasks, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import asyncpg
import httpx
import os
import json
import re

from fastapi import File, UploadFile, Form, Depends
from services.ml_bridge import process_video_via_ml

from services.analytics_engine import (
    compute_density, compute_od_matrix, compute_heatmap,
    compute_cameras, compute_summary, compute_bottlenecks,
    compute_timeseries, compute_camera_recent_reads,
)
from services.trajectory_engine import build_trajectory
from services.alert_engine import check_read_anomalies, SEVERITY_BY_RULE, redis_client
from services.external_reference import get_delhi_vehicle_reference_stats
from services.delhi_fleet_fetcher import get_cached_fleet_data, start_background_refresh
from services.live_traffic import get_live_traffic, fetch_tile, CACHE_TTL_SECONDS as LIVE_TRAFFIC_TTL, MAX_CONGESTION
import asyncio

app = FastAPI(title="VeloCity API")

# Dev-only: the frontend (Vite on :5173) is a different origin than the API (:8000).
# No cookies/credentials are used, so a wide-open dev policy is safe here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_URL = os.getenv("DATABASE_URL", "postgresql://ps127_admin:ps127_password@localhost:5432/ps127_db")

# ML inference service (ml/serve/app.py) -- currently a free Colab GPU session behind a static ngrok
# domain (see ml/docs/RESUME_HERE.md DEPLOYMENT STATUS). Not always running: it needs the Colab tab
# kept open. Set these two env vars to point at whatever's live; every /api/v1/ml/* route below fails
# with a clean 503 (not a crash) if they're unset or the service is unreachable, so the frontend's
# built-in pre-recorded demo still works even when the live service is down.
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "").rstrip("/")
ML_SERVICE_API_KEY = os.getenv("ML_SERVICE_API_KEY", "")
ML_SERVICE_TIMEOUT = httpx.Timeout(600.0, connect=15.0)  # video processing can take minutes on a free GPU

@app.on_event("startup")
async def launch_background_refreshers():
    asyncio.create_task(start_background_refresh())
    asyncio.create_task(live_traffic_recorder())

# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except RuntimeError:
                # Client disconnected abruptly
                dead_connections.append(connection)
            except Exception as e:
                print(f"WebSocket broadcast error: {e}")
                dead_connections.append(connection)
                
        # Clean up dead connections so they don't block future alerts
        for dead in dead_connections:
            self.disconnect(dead)

manager = ConnectionManager()

# --- PYDANTIC MODELS ---
class ReadIngest(BaseModel):
    camera_id: str
    track_id: int
    plate_text: str
    confidence: float
    frame_ts: datetime
    image_ref: str | None = None

class BlacklistEntry(BaseModel):
    plate_text: str
    reason: str
    severity: str = "HIGH"

# --- CORE INGESTION, DEDUPLICATION & ALERTS ---
async def _ingest_read(read: ReadIngest):
    conn = await asyncpg.connect(DB_URL)
    try:
        # 1. Insert the raw read
        await conn.execute("""
            INSERT INTO raw_reads (camera_id, track_id, plate_text, confidence, frame_ts, image_ref)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, read.camera_id, read.track_id, read.plate_text, read.confidence, read.frame_ts, read.image_ref)

        # 2. Deduplication / Upsert into vehicle_tracks (5-second threshold)
        await conn.execute("""
            INSERT INTO vehicle_tracks (track_id, camera_id, first_seen, last_seen, plate_text_final, confidence_avg)
            VALUES ($1, $2, $3, $3, $4, $5)
            ON CONFLICT (track_id, camera_id, first_seen) 
            DO UPDATE SET 
                last_seen = GREATEST(vehicle_tracks.last_seen, EXCLUDED.last_seen),
                confidence_avg = (vehicle_tracks.confidence_avg + EXCLUDED.confidence_avg) / 2
            WHERE EXTRACT(EPOCH FROM (EXCLUDED.last_seen - vehicle_tracks.last_seen)) < 5;
        """, read.track_id, read.camera_id, read.frame_ts, read.plate_text, read.confidence)
        
        # 3. Real-Time Alert Engine Trigger
        alert_payload = await check_read_anomalies(
            read.plate_text, 
            read.camera_id, 
            read.frame_ts, 
            read.confidence
        )
        if alert_payload:
            severity = SEVERITY_BY_RULE.get(alert_payload["rule"], "MEDIUM")

            # Write an entry to alerts table
            alert_id = await conn.fetchval("""
                INSERT INTO alerts (plate_text, camera_id, type, confidence, severity, status, acknowledged, explanation, ts)
                VALUES ($1, $2, $3, $4, $5, 'NEW', FALSE, $6, $7)
                RETURNING id
            """, read.plate_text, read.camera_id, alert_payload["rule"], alert_payload["confidence"], severity, json.dumps(alert_payload), read.frame_ts)

            # Immediately broadcast the payload to all connected clients
            await manager.broadcast({
                "id": alert_id,
                "type": alert_payload["rule"],
                "plate": read.plate_text,
                "camera": read.camera_id,
                "confidence": alert_payload["confidence"],
                "severity": severity,
                "status": "NEW",
                "acknowledged": False,
                "explanation": alert_payload,
                "ts": read.frame_ts.isoformat()
            })

        return {"status": "ingested", "plate": read.plate_text}
    finally:
        await conn.close()

@app.post("/api/v1/reads")
async def ingest_read(read: ReadIngest):
    return await _ingest_read(read)

# --- TRAJECTORY RECONSTRUCTION ENGINE ---
@app.get("/api/v1/trajectory/{plate}")
async def get_trajectory(plate: str, from_ts: str = None, to_ts: str = None):
    conn = await asyncpg.connect(DB_URL)
    try:
        return await build_trajectory(conn, plate)
    finally:
        await conn.close()

# --- ALERTS WEBSOCKET ---
@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    await manager.connect(websocket)
    await websocket.send_json({"type": "SYSTEM_CONNECTED", "message": "Listening for real-time alerts..."})
    try:
        while True:
            await websocket.receive_text() # Keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- MACRO TRAFFIC ANALYTICS ENGINE (Module D) ---
@app.get("/api/v1/analytics/density")
async def get_density(window_minutes: int = 15):
    conn = await asyncpg.connect(DB_URL)
    try:
        return await compute_density(conn, window_minutes)
    finally:
        await conn.close()

@app.get("/api/v1/analytics/od-matrix")
async def get_od_matrix(hour: int = None, date: str = None):
    conn = await asyncpg.connect(DB_URL)
    try:
        return await compute_od_matrix(conn, hour, date)
    finally:
        await conn.close()

@app.get("/api/v1/analytics/heatmap")
async def get_heatmap(time_bucket: str = None):
    conn = await asyncpg.connect(DB_URL)
    try:
        return await compute_heatmap(conn, time_bucket)
    finally:
        await conn.close()

@app.get("/api/v1/analytics/live-traffic")
async def live_traffic():
    return await get_live_traffic()

@app.get("/api/v1/analytics/live-traffic/tiles/{z}/{x}/{y}.png")
async def live_traffic_tile(z: int, x: int, y: int):
    if not 0 <= z <= 22:
        raise HTTPException(status_code=404, detail="zoom out of range")
    tile = await fetch_tile(z, x, y)
    if tile is None:
        return Response(status_code=204)
    return Response(content=tile, media_type="image/png", headers={"Cache-Control": "public, max-age=120"})

# --- LIVE TRAFFIC HISTORY (city-wide speed/congestion snapshots for the dashboard trend chart) ---
LIVE_HISTORY_DDL = """
    CREATE TABLE IF NOT EXISTS live_traffic_history (
        ts TIMESTAMPTZ PRIMARY KEY,
        avg_speed_kmh REAL NOT NULL,
        avg_free_flow_kmh REAL NOT NULL,
        congestion_pct REAL NOT NULL,
        point_count INT NOT NULL
    );
"""

LIVE_POINTS_DDL = """
    CREATE TABLE IF NOT EXISTS live_traffic_points (
        ts TIMESTAMPTZ NOT NULL,
        name TEXT NOT NULL,
        lat DOUBLE PRECISION NOT NULL,
        lon DOUBLE PRECISION NOT NULL,
        current_speed_kmh REAL NOT NULL,
        free_flow_kmh REAL NOT NULL,
        congestion REAL NOT NULL,
        PRIMARY KEY (ts, name)
    );
"""

async def live_traffic_recorder():
    """Stores one city-wide snapshot per live-traffic refresh. Idle (no requests) when no key is set."""
    last_saved = None
    while True:
        try:
            data = await get_live_traffic()
            if data.get("available") and not data.get("stale") and data["updated_at"] != last_saved:
                city = data["city"]
                conn = await asyncpg.connect(DB_URL)
                try:
                    await conn.execute(LIVE_HISTORY_DDL)
                    await conn.execute(LIVE_POINTS_DDL)
                    snapshot_ts = datetime.fromisoformat(data["updated_at"])
                    await conn.executemany(
                        "INSERT INTO live_traffic_points (ts, name, lat, lon, current_speed_kmh, free_flow_kmh, congestion) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (ts, name) DO NOTHING",
                        [(snapshot_ts, p["name"], p["lat"], p["lon"], p["current_speed_kmh"],
                          p["free_flow_speed_kmh"], p["congestion"]) for p in data["points"]],
                    )
                    await conn.execute(
                        "INSERT INTO live_traffic_history (ts, avg_speed_kmh, avg_free_flow_kmh, congestion_pct, point_count) "
                        "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (ts) DO NOTHING",
                        datetime.fromisoformat(data["updated_at"]), city["avg_speed_kmh"],
                        city["avg_free_flow_kmh"], city["congestion_pct"], city["point_count"],
                    )
                finally:
                    await conn.close()
                last_saved = data["updated_at"]
        except Exception as e:
            print(f"live traffic recorder error: {e}")
        await asyncio.sleep(LIVE_TRAFFIC_TTL + 5)

@app.get("/api/v1/analytics/live-traffic/history")
async def live_traffic_history(hours: int = 6):
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute(LIVE_HISTORY_DDL)
        rows = await conn.fetch(
            "SELECT ts, avg_speed_kmh, avg_free_flow_kmh, congestion_pct FROM live_traffic_history "
            "WHERE ts >= NOW() - make_interval(hours => $1) ORDER BY ts",
            max(1, min(hours, 72)),
        )
        return [
            {"ts": r["ts"].isoformat(), "avg_speed_kmh": round(r["avg_speed_kmh"], 1),
             "avg_free_flow_kmh": round(r["avg_free_flow_kmh"], 1), "congestion_pct": round(r["congestion_pct"], 1)}
            for r in rows
        ]
    finally:
        await conn.close()

@app.get("/api/v1/analytics/live-traffic/window")
async def live_traffic_window(minutes: int = 30):
    """Per-point average of the recorded live snapshots over the last `minutes` -- what the dashboard's
    Time Range filter drives. Falls back to the current reading while no history has accumulated yet."""
    minutes = max(5, min(minutes, 1440))
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute(LIVE_POINTS_DDL)
        rows = await conn.fetch(
            "SELECT name, lat, lon, AVG(current_speed_kmh) AS cur, AVG(free_flow_kmh) AS free, "
            "AVG(congestion) AS cong, COUNT(*) AS n, MAX(ts) AS last "
            "FROM live_traffic_points WHERE ts >= NOW() - make_interval(mins => $1) GROUP BY name, lat, lon",
            minutes,
        )
    finally:
        await conn.close()

    if not rows:
        data = await get_live_traffic()
        return {"available": data.get("available", False), "window_minutes": minutes, "snapshots": 0,
                "updated_at": data.get("updated_at"), "points": data.get("points", [])}
    return {
        "available": True,
        "window_minutes": minutes,
        "snapshots": max(r["n"] for r in rows),
        "updated_at": max(r["last"] for r in rows).isoformat(),
        "points": [
            {"name": r["name"], "lat": r["lat"], "lon": r["lon"],
             "current_speed_kmh": round(r["cur"]), "free_flow_speed_kmh": round(r["free"]),
             "congestion": round(r["cong"], 2),
             "intensity": round(min(1.0, r["cong"] / MAX_CONGESTION), 2)}
            for r in rows
        ],
    }

@app.get("/api/v1/analytics/bottlenecks")
async def get_bottlenecks(window_minutes: int = 60, threshold_factor: float = 1.5):
    conn = await asyncpg.connect(DB_URL)
    try:
        return await compute_bottlenecks(conn, window_minutes, threshold_factor)
    finally:
        await conn.close()

# --- CAMERAS & KPI SUMMARY ---
@app.get("/api/v1/cameras")
async def get_cameras():
    conn = await asyncpg.connect(DB_URL)
    try:
        return await compute_cameras(conn)
    finally:
        await conn.close()

@app.get("/api/v1/analytics/summary")
async def get_summary():
    conn = await asyncpg.connect(DB_URL)
    try:
        return await compute_summary(conn)
    finally:
        await conn.close()

@app.get("/api/v1/analytics/timeseries")
async def get_timeseries(window_minutes: int = 120, bucket_minutes: int = 10):
    conn = await asyncpg.connect(DB_URL)
    try:
        return await compute_timeseries(conn, window_minutes, bucket_minutes)
    finally:
        await conn.close()

@app.get("/api/v1/external/delhi-vehicle-stats")
async def get_delhi_vehicle_stats():
    # Static reference snapshot (not a live external call) — see services/external_reference.py
    return get_delhi_vehicle_reference_stats()

@app.get("/api/v1/external/delhi-vehicle-fleet-trend")
async def get_delhi_vehicle_fleet_trend_endpoint():
    # Separate dataset/source from the snapshot above — see the module docstring
    # in services/external_reference.py for why these aren't merged.
    # Always serves from an in-memory cache kept warm by a background task
    # (services/delhi_fleet_fetcher.py) — never blocks on the upstream site.
    return get_cached_fleet_data()

@app.get("/api/v1/cameras/{camera_id}/recent-reads")
async def get_camera_recent_reads(camera_id: str, limit: int = 8):
    conn = await asyncpg.connect(DB_URL)
    try:
        return await compute_camera_recent_reads(conn, camera_id, limit)
    finally:
        await conn.close()

# --- ALERTS ---
@app.get("/api/v1/alerts")
async def get_alerts(limit: int = 10, unacknowledged_only: bool = True):
    conn = await asyncpg.connect(DB_URL)
    try:
        if unacknowledged_only:
            query = """
                SELECT id, plate_text, camera_id, type, confidence, severity, status, acknowledged, explanation, ts
                FROM alerts WHERE acknowledged = FALSE
                ORDER BY ts DESC LIMIT $1;
            """
        else:
            query = """
                SELECT id, plate_text, camera_id, type, confidence, severity, status, acknowledged, explanation, ts
                FROM alerts
                ORDER BY ts DESC LIMIT $1;
            """
        records = await conn.fetch(query, limit)
        results = []
        for r in records:
            row = dict(r)
            row["explanation"] = json.loads(row["explanation"])
            row["ts"] = row["ts"].isoformat()
            results.append(row)
        return results
    finally:
        await conn.close()

@app.post("/api/v1/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    return await _set_alert_status(alert_id, "ACKNOWLEDGED", acknowledged=True)

@app.post("/api/v1/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: int):
    return await _set_alert_status(alert_id, "DISMISSED", acknowledged=True)

@app.post("/api/v1/alerts/{alert_id}/escalate")
async def escalate_alert(alert_id: int):
    return await _set_alert_status(alert_id, "ESCALATED", acknowledged=True)

async def _set_alert_status(alert_id: int, status: str, acknowledged: bool):
    conn = await asyncpg.connect(DB_URL)
    try:
        result = await conn.fetchrow("""
            UPDATE alerts SET status = $2, acknowledged = $3
            WHERE id = $1
            RETURNING id, status, acknowledged;
        """, alert_id, status, acknowledged)
        if not result:
            raise HTTPException(status_code=404, detail="Alert not found")
        return dict(result)
    finally:
        await conn.close()

# --- BLACKLIST MANAGEMENT ---
@app.get("/api/v1/blacklist")
async def list_blacklist():
    conn = await asyncpg.connect(DB_URL)
    try:
        records = await conn.fetch("SELECT plate_text, reason, severity FROM blacklist ORDER BY plate_text;")
        return [dict(r) for r in records]
    finally:
        await conn.close()

@app.post("/api/v1/blacklist")
async def add_blacklist(entry: BlacklistEntry):
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute("""
            INSERT INTO blacklist (plate_text, reason, severity)
            VALUES ($1, $2, $3)
            ON CONFLICT (plate_text) DO UPDATE SET reason = EXCLUDED.reason, severity = EXCLUDED.severity;
        """, entry.plate_text, entry.reason, entry.severity)
        # Keep the alert engine's Redis cache in sync so the next read triggers a live alert
        await redis_client.sadd("blacklist_exact", entry.plate_text)
        return {"status": "added", "plate": entry.plate_text}
    finally:
        await conn.close()

@app.post("/api/v1/upload-video")
async def upload_traffic_video(
    video: UploadFile = File(...),
    camera_id: str = Form("demo01")
    # Line 314 removed: 'conn = Depends(get_db)' is deleted to fix the Pylance error
):
    # 1. Run video through the remote ML model
    extracted_reads = await process_video_via_ml(video, camera_id)
    
    # 2. Ingest reads into PostGIS & trigger alerts
    ingested_count = 0
    for read in extracted_reads:
        # Re-use the existing ReadIngest model (line 61) and ingest_read function (line 71)
        read_obj = ReadIngest(
            camera_id=read["camera_id"],
            track_id=read["track_id"],
            plate_text=read["plate_text"],
            confidence=read["confidence"],
            frame_ts=read["frame_ts"],
            image_ref=read["image_ref"]
        )
        # This replaces evaluate_alerts and handles DB connections, deduplication, and WebSocket broadcasts automatically
        await ingest_read(read_obj) 
        ingested_count += 1
        
    return {
        "status": "success",
        "camera_id": camera_id,
        "processed_reads": ingested_count, 
        "data": extracted_reads
    }

@app.delete("/api/v1/blacklist/{plate}")
async def delete_blacklist(plate: str):
    conn = await asyncpg.connect(DB_URL)
    try:
        result = await conn.execute("DELETE FROM blacklist WHERE plate_text = $1;", plate)
        await redis_client.srem("blacklist_exact", plate)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Plate not found in blacklist")
        return {"status": "removed", "plate": plate}
    finally:
        await conn.close()

# --- ML INFERENCE PROXY (Module A/B live demo -- "Test the Model" screen) ---
# Thin forwarders to the ml/ service's own /health, /process-video, /process-image (see
# ml/serve/app.py). Kept as a proxy rather than having the frontend call the ML service directly so
# the ngrok/Colab URL and its API key live in one place (this backend's env vars), not in frontend
# code, and so the frontend only ever needs to know about this one backend origin.
ML_UPLOAD_MAX_BYTES = 150 * 1024 * 1024  # 150MB -- generous for a demo clip, kept below the ml
                                          # service's own 500MB cap to protect this backend's memory


def _require_ml_service() -> None:
    if not ML_SERVICE_URL:
        raise HTTPException(
            status_code=503,
            detail="ML_SERVICE_URL is not configured on this backend -- live processing is unavailable "
                   "right now. The pre-recorded demo footage still works without this.",
        )


@app.get("/api/v1/ml/status")
async def ml_service_status():
    if not ML_SERVICE_URL:
        return {"available": False, "reason": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{ML_SERVICE_URL}/health")
        return {"available": resp.status_code == 200}
    except httpx.HTTPError:
        return {"available": False, "reason": "unreachable"}


async def _forward_upload(endpoint: str, file: UploadFile, extra_fields: dict) -> dict:
    _require_ml_service()

    data = await file.read()
    if len(data) > ML_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {ML_UPLOAD_MAX_BYTES // (1024 * 1024)}MB limit",
        )

    headers = {"X-API-Key": ML_SERVICE_API_KEY} if ML_SERVICE_API_KEY else {}
    field_name = "video" if endpoint == "process-video" else "image"
    files = {field_name: (file.filename or "upload", data, file.content_type or "application/octet-stream")}

    try:
        async with httpx.AsyncClient(timeout=ML_SERVICE_TIMEOUT) as client:
            resp = await client.post(f"{ML_SERVICE_URL}/{endpoint}", files=files, data=extra_fields, headers=headers)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="ML service timed out processing this upload")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"ML service unreachable: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"ML service error: {resp.text[:500]}")
    return resp.json()


PLATE_FORMAT = re.compile(r"^[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}$")  # same grammar as ml/src/config.py PLATE_REGEX


def _video_reads_for_ingest(result: dict) -> list[dict]:
    """One read per voted track (valid plate format only), timed at the track's first sighting in the clip."""
    first_seen: dict = {}
    for r in result.get("raw_reads", []):
        first_seen[r["track_id"]] = min(first_seen.get(r["track_id"], r["frame_ts"]), r["frame_ts"])
    return [
        {"track_id": v["track_id"], "plate_text": v["plate_text"], "confidence": v["confidence"],
         "offset_s": first_seen.get(v["track_id"], 0.0)}
        for v in result.get("voted_reads", [])
        if PLATE_FORMAT.match(v.get("plate_text") or "")
    ]


def _image_reads_for_ingest(result: dict) -> list[dict]:
    return [
        {"track_id": d["track_id"], "plate_text": d["plate_text"], "confidence": d["confidence"], "offset_s": 0.0}
        for d in result.get("detections", [])
        if PLATE_FORMAT.match(d.get("plate_text") or "")
    ]


async def _ingest_ml_reads(camera_id: str, reads: list[dict]) -> dict:
    """Feeds ML-service plate reads through the same ingestion path as any camera read (raw_reads, vehicle
    tracks, alert rules, WebSocket broadcast), timed so the clip's last sighting lands at 'now'. Track ids are
    offset per call so separate uploads to one camera never collide in the per-camera distinct-track counts."""
    if not reads:
        return {"ingested": 0}
    conn = await asyncpg.connect(DB_URL)
    try:
        known = await conn.fetchval("SELECT 1 FROM cameras WHERE id = $1", camera_id)
    finally:
        await conn.close()
    if not known:
        return {"ingested": 0, "ingest_skipped": f"'{camera_id}' is not a registered camera"}

    now = datetime.now(timezone.utc)
    span = max(r["offset_s"] for r in reads)
    id_base = (int(now.timestamp()) % 1_000_000) * 1000
    for r in reads:
        await _ingest_read(ReadIngest(
            camera_id=camera_id,
            track_id=id_base + int(r["track_id"]) % 1000,
            plate_text=r["plate_text"],
            confidence=float(r["confidence"]),
            frame_ts=now - timedelta(seconds=span - r["offset_s"]),
            image_ref=None,
        ))
    return {"ingested": len(reads)}


@app.post("/api/v1/ml/process-video")
async def ml_process_video(
    video: UploadFile = File(...),
    camera_id: str = Form("demo01"),
    max_frames: int | None = Form(None),
):
    extra = {"camera_id": camera_id}
    if max_frames is not None:
        extra["max_frames"] = str(max_frames)
    result = await _forward_upload("process-video", video, extra)
    result.update(await _ingest_ml_reads(camera_id, _video_reads_for_ingest(result)))
    return result


@app.post("/api/v1/ml/process-image")
async def ml_process_image(
    image: UploadFile = File(...),
    camera_id: str = Form("demo01"),
):
    result = await _forward_upload("process-image", image, {"camera_id": camera_id})
    result.update(await _ingest_ml_reads(camera_id, _image_reads_for_ingest(result)))
    return result
