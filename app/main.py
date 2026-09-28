from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncpg
import os
import json

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
import asyncio

app = FastAPI(title="PS127 City-Wide ANPR API")

# Dev-only: the frontend (Vite on :5173) is a different origin than the API (:8000).
# No cookies/credentials are used, so a wide-open dev policy is safe here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_URL = os.getenv("DATABASE_URL", "postgresql://ps127_admin:ps127_password@localhost:5432/ps127_db")

@app.on_event("startup")
async def launch_background_refreshers():
    asyncio.create_task(start_background_refresh())

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
@app.post("/api/v1/reads")
async def ingest_read(read: ReadIngest):
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

        