
"""Generate 25 realistic urban ANPR camera nodes for a Bengaluru grid.

Writes data/cameras.json using the Eetal camera schema:
  id, name, lat, lon, road_segment_id, lane_count, speed_limit_kmh

Cameras sit on named junctions across an ~15 km² central Bengaluru patch
(Cubbon Park / MG Road / Shivajinagar / Richmond / Ulsoor).
"""

from __future__ import annotations

import json
import math
from pathlib import Path


EARTH_R_KM = 6371.0


CITY = "Bengaluru"
ORIGIN_LAT = 12.9716
ORIGIN_LON = 77.5946


TARGET_AREA_KM2 = 15.0

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "cameras.json"



JUNCTIONS: list[dict] = [
    {
        "id": "cam_001",
        "name": "ANPR CAM – Vidhana Soudha / Dr Ambedkar Veedhi",
        "lat": 12.9796,
        "lon": 77.5907,
        "road_segment_id": "seg_ambedkar_veedhi_01",
        "lane_count": 6,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_002",
        "name": "ANPR CAM – Cubbon Park / Kasturba Road",
        "lat": 12.9763,
        "lon": 77.5929,
        "road_segment_id": "seg_kasturba_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_003",
        "name": "ANPR CAM – Indian Express Circle",
        "lat": 12.9842,
        "lon": 77.5951,
        "road_segment_id": "seg_queens_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_004",
        "name": "ANPR CAM – Anil Kumble Circle",
        "lat": 12.9784,
        "lon": 77.5997,
        "road_segment_id": "seg_mg_rd_west_01",
        "lane_count": 6,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_005",
        "name": "ANPR CAM – MG Road Metro Junction",
        "lat": 12.9756,
        "lon": 77.6066,
        "road_segment_id": "seg_mg_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_006",
        "name": "ANPR CAM – Brigade Road / MG Road",
        "lat": 12.9738,
        "lon": 77.6074,
        "road_segment_id": "seg_brigade_rd_01",
        "lane_count": 2,
        "speed_limit_kmh": 30.0,
    },
    {
        "id": "cam_007",
        "name": "ANPR CAM – Church Street / St Marks Road",
        "lat": 12.9741,
        "lon": 77.6038,
        "road_segment_id": "seg_church_st_01",
        "lane_count": 2,
        "speed_limit_kmh": 30.0,
    },
    {
        "id": "cam_008",
        "name": "ANPR CAM – St Marks Road / Residency Road",
        "lat": 12.9708,
        "lon": 77.6016,
        "road_segment_id": "seg_st_marks_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_009",
        "name": "ANPR CAM – Mayo Hall / MG Road",
        "lat": 12.9726,
        "lon": 77.6102,
        "road_segment_id": "seg_mg_rd_02",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_010",
        "name": "ANPR CAM – Trinity Circle",
        "lat": 12.9730,
        "lon": 77.6169,
        "road_segment_id": "seg_old_airport_rd_01",
        "lane_count": 6,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_011",
        "name": "ANPR CAM – Ulsoor Lake / Kensington Road",
        "lat": 12.9814,
        "lon": 77.6190,
        "road_segment_id": "seg_kensington_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_012",
        "name": "ANPR CAM – Halasuru Metro / Old Madras Road",
        "lat": 12.9786,
        "lon": 77.6264,
        "road_segment_id": "seg_old_madras_rd_01",
        "lane_count": 6,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_013",
        "name": "ANPR CAM – Commercial Street / Dispensary Road",
        "lat": 12.9826,
        "lon": 77.6087,
        "road_segment_id": "seg_commercial_st_01",
        "lane_count": 2,
        "speed_limit_kmh": 30.0,
    },
    {
        "id": "cam_014",
        "name": "ANPR CAM – Russell Market / Shivajinagar",
        "lat": 12.9839,
        "lon": 77.6054,
        "road_segment_id": "seg_shivajinagar_01",
        "lane_count": 3,
        "speed_limit_kmh": 30.0,
    },
    {
        "id": "cam_015",
        "name": "ANPR CAM – Bowring Hospital Junction",
        "lat": 12.9834,
        "lon": 77.6078,
        "road_segment_id": "seg_hospital_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_016",
        "name": "ANPR CAM – Infantry Road / Queen's Road",
        "lat": 12.9821,
        "lon": 77.5982,
        "road_segment_id": "seg_infantry_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_017",
        "name": "ANPR CAM – Cunningham Road / Ali Asker Road",
        "lat": 12.9872,
        "lon": 77.5941,
        "road_segment_id": "seg_cunningham_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_018",
        "name": "ANPR CAM – Palace Road / High Grounds",
        "lat": 12.9881,
        "lon": 77.5879,
        "road_segment_id": "seg_palace_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_019",
        "name": "ANPR CAM – Race Course Road / Chalukya Circle",
        "lat": 12.9840,
        "lon": 77.5848,
        "road_segment_id": "seg_race_course_rd_01",
        "lane_count": 6,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_020",
        "name": "ANPR CAM – Vittal Mallya Road / UB City",
        "lat": 12.9716,
        "lon": 77.5963,
        "road_segment_id": "seg_vittal_mallya_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_021",
        "name": "ANPR CAM – Richmond Circle",
        "lat": 12.9615,
        "lon": 77.5994,
        "road_segment_id": "seg_richmond_rd_01",
        "lane_count": 6,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_022",
        "name": "ANPR CAM – Double Road / Richmond",
        "lat": 12.9588,
        "lon": 77.5991,
        "road_segment_id": "seg_kanteerava_double_rd_01",
        "lane_count": 6,
        "speed_limit_kmh": 50.0,
    },
    {
        "id": "cam_023",
        "name": "ANPR CAM – Residency Road / Richmond Road",
        "lat": 12.9662,
        "lon": 77.6013,
        "road_segment_id": "seg_residency_rd_01",
        "lane_count": 4,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_024",
        "name": "ANPR CAM – Lavelle Road / Field Marshal Cariappa Road",
        "lat": 12.9694,
        "lon": 77.5978,
        "road_segment_id": "seg_lavelle_rd_01",
        "lane_count": 3,
        "speed_limit_kmh": 40.0,
    },
    {
        "id": "cam_025",
        "name": "ANPR CAM – Langford Town / Hosur Road approach",
        "lat": 12.9572,
        "lon": 77.6071,
        "road_segment_id": "seg_hosur_rd_01",
        "lane_count": 6,
        "speed_limit_kmh": 60.0,
    },
]

SCHEMA_KEYS = (
    "id",
    "name",
    "lat",
    "lon",
    "road_segment_id",
    "lane_count",
    "speed_limit_kmh",
)


BLR_LAT_RANGE = (12.90, 13.05)
BLR_LON_RANGE = (77.50, 77.70)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def bbox_area_km2(cameras: list[dict]) -> tuple[float, float, float]:
    lats = [c["lat"] for c in cameras]
    lons = [c["lon"] for c in cameras]
    height = haversine_km(min(lats), min(lons), max(lats), min(lons))
    width = haversine_km(min(lats), min(lons), min(lats), max(lons))
    return width * height, width, height


def validate(cameras: list[dict]) -> None:
    if len(cameras) != 25:
        raise ValueError(f"Expected 25 cameras, got {len(cameras)}")

    ids: set[str] = set()
    for cam in cameras:
        missing = [k for k in SCHEMA_KEYS if k not in cam]
        if missing:
            raise ValueError(f"Missing keys {missing} on {cam.get('id')}")
        extra = [k for k in cam if k not in SCHEMA_KEYS]
        if extra:
            raise ValueError(f"Unexpected keys {extra} on {cam['id']}")
        if not isinstance(cam["id"], str) or not cam["id"]:
            raise TypeError(f"id must be a non-empty str: {cam}")
        if cam["id"] in ids:
            raise ValueError(f"Duplicate camera id: {cam['id']}")
        ids.add(cam["id"])
        if not isinstance(cam["name"], str) or not cam["name"]:
            raise TypeError(f"name must be a non-empty str: {cam['id']}")
        if not isinstance(cam["lat"], float):
            raise TypeError(f"lat must be float: {cam['id']}")
        if not isinstance(cam["lon"], float):
            raise TypeError(f"lon must be float: {cam['id']}")
        if not (BLR_LAT_RANGE[0] <= cam["lat"] <= BLR_LAT_RANGE[1]):
            raise ValueError(f"lat out of Bengaluru range: {cam['id']} {cam['lat']}")
        if not (BLR_LON_RANGE[0] <= cam["lon"] <= BLR_LON_RANGE[1]):
            raise ValueError(f"lon out of Bengaluru range: {cam['id']} {cam['lon']}")
        if not isinstance(cam["road_segment_id"], str) or not cam["road_segment_id"]:
            raise TypeError(f"road_segment_id must be a non-empty str: {cam['id']}")
        if not isinstance(cam["lane_count"], int) or cam["lane_count"] < 1:
            raise TypeError(f"lane_count must be a positive int: {cam['id']}")
        if not isinstance(cam["speed_limit_kmh"], float) or cam["speed_limit_kmh"] <= 0:
            raise TypeError(f"speed_limit_kmh must be a positive float: {cam['id']}")

    area, width, height = bbox_area_km2(cameras)

    if not (8.0 <= area <= 25.0):
        raise ValueError(
            f"Camera bbox area {area:.2f} km² ( {width:.2f}×{height:.2f} km ) "
            f"is outside the expected ~{TARGET_AREA_KM2} km² urban grid"
        )


def build_cameras() -> list[dict]:
    cameras = []
    for raw in JUNCTIONS:
        cameras.append(
            {
                "id": raw["id"],
                "name": raw["name"],
                "lat": float(raw["lat"]),
                "lon": float(raw["lon"]),
                "road_segment_id": raw["road_segment_id"],
                "lane_count": int(raw["lane_count"]),
                "speed_limit_kmh": float(raw["speed_limit_kmh"]),
            }
        )
    return cameras


def main() -> None:
    cameras = build_cameras()
    validate(cameras)
    area, width, height = bbox_area_km2(cameras)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(cameras, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {len(cameras)} cameras to {OUTPUT_PATH}")
    print(f"City grid: {CITY} (origin {ORIGIN_LAT}, {ORIGIN_LON})")
    print(f"Coverage bbox: {width:.2f} km × {height:.2f} km ≈ {area:.2f} km²")
    print(
        f"Lat [{min(c['lat'] for c in cameras):.5f}, {max(c['lat'] for c in cameras):.5f}]  "
        f"Lon [{min(c['lon'] for c in cameras):.5f}, {max(c['lon'] for c in cameras):.5f}]"
    )


if __name__ == "__main__":
    main()
