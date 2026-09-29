
"""
Replays real ANPR-pipeline output (plates read from the recorded demo footage) into the running backend
through the normal ingestion route, so the dashboard, trajectories and alert rules run on genuine model
reads instead of synthetic ones. Each clip is assigned to one camera (see data/footage_replay.json) and its
last sighting is stamped "now", so the rolling-window panels (cameras online, density, heatmap) light up.

This is a replay of recorded footage, not live cameras -- say so if you show it. Run it again whenever the
camera-derived panels have aged out (cameras go offline after 5 minutes without reads).

Usage:  python demo/replay_footage_reads.py [--base-url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "footage_replay.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay recorded-footage plate reads into the backend")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    clips = json.loads(DATA_FILE.read_text(encoding="utf-8"))["clips"]
    now = datetime.now(timezone.utc)
    id_base = (int(time.time()) % 1_000_000) * 1000  # keeps track ids unique across repeated runs

    total = 0
    with httpx.Client(base_url=args.base_url, timeout=10.0) as client:
        for clip in clips:
            span = max(r["offset_s"] for r in clip["reads"])
            sent = 0
            for r in clip["reads"]:
                payload = {
                    "camera_id": clip["camera_id"],
                    "track_id": id_base + r["track_id"] % 1000,
                    "plate_text": r["plate_text"],
                    "confidence": r["confidence"],
                    "frame_ts": (now - timedelta(seconds=span - r["offset_s"])).isoformat(),
                }
                resp = client.post("/api/v1/reads", json=payload)
                sent += resp.status_code == 200
            print(f"{clip['camera_id']}: {sent}/{len(clip['reads'])} reads from {clip['source_video']}")
            total += sent
    print(f"Replayed {total} reads into {args.base_url}")


if __name__ == "__main__":
    main()
