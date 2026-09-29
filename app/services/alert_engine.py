import redis.asyncio as redis
from datetime import datetime
import os



REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)

SEVERITY_BY_RULE = {
    "BLACKLIST_MATCH": "HIGH",
    "CURFEW_VIOLATION": "HIGH",
    "ROUTE_CIRCLING": "MEDIUM",
}

async def check_read_anomalies(plate_text: str, camera_id: str, frame_ts: datetime, read_confidence: float) -> dict | None:
    """
    Evaluates incoming reads against Redis caches and rule-based anomalies.
    Returns an explainability dictionary if an alert is triggered.
    """

    is_blacklisted = await redis_client.sismember("blacklist_exact", plate_text)
    
    if is_blacklisted:
        return {
            "rule": "BLACKLIST_MATCH",
            "confidence": read_confidence,
            "details": f"Exact matched plate {plate_text} in registry"
        }
    
    fuzzy_cached_variant = await redis_client.hget("blacklist_fuzzy", plate_text)
    if fuzzy_cached_variant:
        return {
            "rule": "BLACKLIST_MATCH",
            "confidence": read_confidence * 0.9, 
            "details": f"Fuzzy matched plate {plate_text} to {fuzzy_cached_variant}"
        }


    history_key = f"history:{plate_text}"
    read_event = f"{camera_id}|{frame_ts.timestamp()}"
    
    await redis_client.lpush(history_key, read_event)
    await redis_client.expire(history_key, 900) # 15 minutes TTL


    recent_reads = await redis_client.lrange(history_key, 0, -1)
    
    unique_cameras = set()
    for read in recent_reads:
        cam, _ = read.split('|')
        unique_cameras.add(cam)


    time_in_hours = frame_ts.hour + (frame_ts.minute / 60.0)
    
    if 2.0 <= time_in_hours <= 4.5:
        if len(unique_cameras) >= 3:
            return {
                "rule": "CURFEW_VIOLATION",
                "confidence": read_confidence,
                "details": f"Vehicle detected across {len(unique_cameras)} distinct cameras during active curfew hours."
            }



    if len(recent_reads) >= 4 and len(unique_cameras) == 3:
        return {
            "rule": "ROUTE_CIRCLING",
            "confidence": read_confidence,
            "details": f"Vehicle looped identical 3 camera nodes ({', '.join(unique_cameras)}) within 15 minutes."
        }

    return None