import httpx
import json
from datetime import datetime

# Substitution penalty matrix for Indian license plates
OCR_CONFUSION_PAIRS = {
    '8': 'B', 'B': '8',
    '0': 'D', 'D': '0', '0': 'O', 'O': '0',
    '1': 'I', 'I': '1',
    '5': 'S', 'S': '5',
    'Z': '2', '2': 'Z'
}

async def build_trajectory(conn, target_plate: str):
    await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    
    # Offload fuzzy matching, speed plausibility (140km/h), and GeoJSON generation to PostGIS
    query = """
        WITH matched_reads AS (
            SELECT r.plate_text, r.confidence, r.frame_ts, r.image_ref, 
                   c.id as camera_id, c.lat, c.lon, c.geom,
                   similarity(r.plate_text, $1) as sim_score
            FROM raw_reads r
            JOIN cameras c ON r.camera_id = c.id
            WHERE r.plate_text = $1 OR similarity(r.plate_text, $1) > 0.4
        ),
        ordered_reads AS (
            SELECT *,
                   LAG(geom) OVER (ORDER BY frame_ts) as prev_geom,
                   LAG(frame_ts) OVER (ORDER BY frame_ts) as prev_ts
            FROM matched_reads
        ),
        speed_filtered AS (
            SELECT *
            FROM ordered_reads
            WHERE prev_ts IS NULL
               OR EXTRACT(EPOCH FROM (frame_ts - prev_ts)) = 0
               OR (ST_Distance(geom::geography, prev_geom::geography) / 1000.0) / 
                  (EXTRACT(EPOCH FROM (frame_ts - prev_ts)) / 3600.0) <= 140.0
        )
        SELECT 
            (SELECT COALESCE(jsonb_agg(
                jsonb_build_object(
                    'type', 'Feature',
                    'geometry', jsonb_build_object('type', 'Point', 'coordinates', jsonb_build_array(lon, lat)),
                    'properties', jsonb_build_object(
                        'camera_id', camera_id,
                        'timestamp', frame_ts,
                        'confidence', confidence,
                        'plate_read', plate_text,
                        'fuzzy_score', sim_score,
                        'image_ref', image_ref
                    )
                )
            ), '[]'::jsonb) FROM speed_filtered) as waypoint_features,
            
            (SELECT ST_AsGeoJSON(ST_MakeLine(geom ORDER BY frame_ts))::jsonb 
             FROM speed_filtered) as db_fallback_geojson,
             
            (SELECT COALESCE(jsonb_agg(
                jsonb_build_object('lon', lon, 'lat', lat) ORDER BY frame_ts
            ), '[]'::jsonb) FROM speed_filtered) as raw_coords
    """
    
    row = await conn.fetchrow(query, target_plate)
    if not row or not json.loads(row['waypoint_features']):
        return {"type": "FeatureCollection", "features": []}
        
    features = json.loads(row['waypoint_features'])
    coords_list = json.loads(row['raw_coords'])
    
    # 3. Road Snapping via OSRM HTTP API
    if len(coords_list) > 1:
        coords_string = ";".join([f"{c['lon']},{c['lat']}" for c in coords_list])
        osrm_url = f"http://router.project-osrm.org/route/v1/driving/{coords_string}?geometries=geojson&overview=full"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(osrm_url, timeout=10.0)
                if response.status_code == 200:
                    route_data = response.json()
                    if route_data.get("code") == "Ok":
                        snapped_geometry = route_data["routes"][0]["geometry"]
                        features.append({
                            "type": "Feature",
                            "geometry": snapped_geometry,
                            "properties": {"type": "trajectory_path", "target_plate": target_plate, "snapped": True}
                        })
                        return {"type": "FeatureCollection", "features": features}
            except Exception as e:
                print(f"OSRM routing failed: {e}")
        
        # Bypassing Python-side geometric serialization per the Day 2.5 blueprint
        db_fallback = json.loads(row['db_fallback_geojson']) if row['db_fallback_geojson'] else None
        if db_fallback:
            features.append({
                "type": "Feature",
                "geometry": db_fallback,
                "properties": {"type": "trajectory_path", "target_plate": target_plate, "snapped": False}
            })

    return {
        "type": "FeatureCollection",
        "features": features
    }