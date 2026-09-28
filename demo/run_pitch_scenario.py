#!/usr/bin/env python3
"""
Deliverable 6: Pitch Presentation Orchestrator.
Simulates live background traffic, registers an alert on a blacklisted plate,
and transmits sequential sightings across adjacent cameras.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
READS_FILE = DATA_DIR / "synthetic_reads.json"

TARGET_PLATE = "DL04C9999"

def print_banner(text: str) -> None:
    print(f"\n\033[1;36m{'=' * 65}\033[0m")
    print(f"\033[1;36m  {text}\033[0m")
    print(f"\033[1;36m{'=' * 65}\033[0m\n")

def stage_1_background_traffic(base_url: str, count: int = 50) -> None:
    print(f"\033[1;33m[STAGE 1] Ingesting {count} background traffic reads...\033[0m")
    if not READS_FILE.exists():
        print(f"  \033[31m[!] {READS_FILE} not found. Skipping background traffic.\033[0m")
        return

    with open(READS_FILE, "r") as f:
        reads = json.load(f)

    background_reads = [r for r in reads if r.get("plate_text") != TARGET_PLATE][:count]
    successes = 0

    for r in background_reads:
        try:
            res = requests.post(f"{base_url}/api/v1/reads", json=r, timeout=2.0)
            if res.status_code in (200, 201, 202):
                successes += 1
        except requests.RequestException:
            pass

    print(f"  -> Successfully posted {successes}/{len(background_reads)} reads to {base_url}/api/v1/reads\n")

def stage_2_register_blacklist(base_url: str) -> None:
    print(f"\033[1;33m[STAGE 2] Registering Blacklist Alert for: {TARGET_PLATE}...\033[0m")
    payload = {
        "plate_text": TARGET_PLATE,
        "reason": "Stolen Vehicle - Immediate Intercept",
        "severity": "CRITICAL",
    }
    try:
        res = requests.post(f"{base_url}/api/v1/blacklist", json=payload, timeout=2.0)
        print(f"  -> Response [{res.status_code}]: {res.text}")
    except requests.RequestException as e:
        print(f"  -> [Simulated Mode] Backend not running yet: {e}")

def stage_3_sequential_intercept(base_url: str, delay_sec: float = 3.0) -> None:
    print(f"\n\033[1;33m[STAGE 3] Injecting sequential target hops for tracking and alerts...\033[0m")
    
    # Reverted to lowercase to match the seeded PostGIS database
    demo_hops = [
        {"camera_id": "cam_001", "track_id": 9901, "confidence": 0.98},
        {"camera_id": "cam_004", "track_id": 9902, "confidence": 0.96},
        {"camera_id": "cam_008", "track_id": 9903, "confidence": 0.92},
        {"camera_id": "cam_012", "track_id": 9904, "confidence": 0.97},
    ]

    for idx, hop in enumerate(demo_hops, 1):
        ts = datetime.now(timezone.utc).isoformat()
        payload = {
            "camera_id": hop["camera_id"],
            "track_id": hop["track_id"],
            "plate_text": TARGET_PLATE,
            "confidence": hop["confidence"],
            "frame_ts": ts,
            "image_ref": f"s3://anpr-frames/{hop['camera_id']}_{TARGET_PLATE}_{hop['track_id']}.jpg",
        }
        print(f"  Hop {idx}/{len(demo_hops)}: Camera {hop['camera_id']} detected {TARGET_PLATE} (conf: {hop['confidence']})")
        try:
            requests.post(f"{base_url}/api/v1/reads", json=payload, timeout=2.0)
        except requests.RequestException:
            pass

        if idx < len(demo_hops):
            time.sleep(delay_sec)

def main() -> None:
    parser = argparse.ArgumentParser(description="Run live ANPR pitch presentation scenario")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Target FastAPI backend URL")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between sequential target hops")
    args = parser.parse_args()

    print_banner("ANPR LIVE DEMO: PITCH SCENARIO ORCHESTRATOR")
    
    stage_1_background_traffic(args.base_url, count=50)
    time.sleep(1.0)
    
    stage_2_register_blacklist(args.base_url)
    time.sleep(1.5)
    
    stage_3_sequential_intercept(args.base_url, delay_sec=args.delay)
    print("\n\033[1;32m[COMPLETE] Demo scenario finished.\033[0m\n")

if __name__ == "__main__":
    main()