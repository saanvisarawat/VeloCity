
"""Generate synthetic ANPR reads across the Bengaluru camera grid.

Writes data/synthetic_reads.json using the Eetal raw_reads schema:
  camera_id, track_id, plate_text, confidence, frame_ts, image_ref

100 distinct Indian plates travel 4–8 adjacent cameras at 30–60 km/h.
~10% of reads receive a single OCR substitution from the spec matrix.
Pass --stream to POST records to http://localhost:8000/api/v1/reads.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import string
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAMERAS_PATH = ROOT / "data" / "cameras.json"
OUTPUT_PATH = ROOT / "data" / "synthetic_reads.json"
STREAM_URL = "http://localhost:8000/api/v1/reads"

BLACKLISTED_PLATES = [
    "DL04C9999",
    "MH12AB0007",
    "KA01EQ1234",
    "UP32AA4321",
    "DL01AB1234",
]

PLATE_COUNT = 100
HOP_RANGE = (4, 8)
SPEED_KMH_RANGE = (30.0, 60.0)
OCR_RATE = 0.10
NEIGHBOR_K = 5
RNG_SEED = 42

IST = timezone(timedelta(hours=5, minutes=30))
SIM_DAY = datetime(2026, 9, 24, 7, 0, 0, tzinfo=IST)

STATE_CODES = [
    "DL", "MH", "KA", "UP", "TN", "GJ", "RJ", "WB", "AP", "TS",
    "HR", "PB", "KL", "MP", "CG", "BR", "OR", "UK", "HP", "GA",
]


OCR_CONFUSION: dict[str, tuple[str, ...]] = {
    "8": ("B",),
    "B": ("8",),
    "0": ("D", "O"),
    "D": ("0",),
    "O": ("0",),
    "1": ("I",),
    "I": ("1",),
    "5": ("S",),
    "S": ("5",),
    "Z": ("2",),
    "2": ("Z",),
}

SCHEMA_KEYS = (
    "camera_id",
    "track_id",
    "plate_text",
    "confidence",
    "frame_ts",
    "image_ref",
)

EARTH_R_KM = 6371.0


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
    """k-nearest geographic neighbors for each camera (undirected)."""
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


def random_indian_plate(rng: random.Random, used: set[str]) -> str:
    """Compact Indian plate: SS00LL0000 (e.g. DL01AB1234)."""
    letters = string.ascii_uppercase
    for _ in range(10_000):
        state = rng.choice(STATE_CODES)
        rto = rng.randint(1, 99)
        series = "".join(rng.choice(letters) for _ in range(2))
        number = rng.randint(1, 9999)
        plate = f"{state}{rto:02d}{series}{number:04d}"
        if plate not in used:
            return plate
    raise RuntimeError("Unable to allocate a unique plate")


def generate_plates(rng: random.Random) -> list[str]:
    plates: list[str] = []
    used: set[str] = set()
    for plate in BLACKLISTED_PLATES:
        plates.append(plate)
        used.add(plate)
    while len(plates) < PLATE_COUNT:
        plate = random_indian_plate(rng, used)
        plates.append(plate)
        used.add(plate)
    return plates


def walk_path(
    rng: random.Random,
    cameras: list[dict],
    adjacency: dict[str, list[str]],
    hop_count: int,
) -> list[dict]:
    by_id = {c["id"]: c for c in cameras}
    current = rng.choice(cameras)
    path = [current]
    visited = {current["id"]}
    while len(path) < hop_count:
        nbrs = adjacency[current["id"]]
        unused = [nid for nid in nbrs if nid not in visited]
        pool = unused or [nid for nid in nbrs if nid != current["id"]]
        if not pool:
            leftover = [c for c in cameras if c["id"] not in visited]
            if not leftover:
                break
            nxt = min(
                leftover,
                key=lambda c: haversine_km(
                    current["lat"], current["lon"], c["lat"], c["lon"]
                ),
            )
            path.append(nxt)
            visited.add(nxt["id"])
            current = nxt
            continue
        nxt = by_id[rng.choice(pool)]
        path.append(nxt)
        visited.add(nxt["id"])
        current = nxt
    return path


def apply_ocr(plate: str, rng: random.Random) -> tuple[str, bool]:
    indexes = [i for i, ch in enumerate(plate) if ch in OCR_CONFUSION]
    if not indexes:
        return plate, False
    idx = rng.choice(indexes)
    chars = list(plate)
    chars[idx] = rng.choice(OCR_CONFUSION[chars[idx]])
    confused = "".join(chars)
    return confused, confused != plate


def iso8601(ts: datetime) -> str:

    return ts.isoformat(timespec="milliseconds")


def simulate_reads(cameras: list[dict], rng: random.Random) -> list[dict]:
    adjacency = build_adjacency(cameras)
    plates = generate_plates(rng)
    reads: list[dict] = []

    for track_id, plate in enumerate(plates, start=1):
        hop_count = rng.randint(*HOP_RANGE)
        path = walk_path(rng, cameras, adjacency, hop_count)
        if len(path) < HOP_RANGE[0]:
            raise RuntimeError(f"Could not build a {HOP_RANGE[0]}-hop path")

        start_offset = timedelta(seconds=rng.randint(0, 4 * 3600))
        ts = SIM_DAY + start_offset

        for hop_i, cam in enumerate(path):
            if hop_i > 0:
                prev = path[hop_i - 1]
                dist_km = haversine_km(prev["lat"], prev["lon"], cam["lat"], cam["lon"])
                dist_km = max(dist_km, 0.05)
                speed = rng.uniform(*SPEED_KMH_RANGE)
                travel_s = (dist_km / speed) * 3600.0
                ts = ts + timedelta(seconds=travel_s)

            reads.append(
                {
                    "camera_id": cam["id"],
                    "track_id": track_id,
                    "plate_text": plate,
                    "confidence": 0.0,  # filled after OCR pass
                    "frame_ts": iso8601(ts),
                    "image_ref": (
                        f"s3://eetal-anpr/frames/{cam['id']}/"
                        f"{ts.strftime('%Y%m%dT%H%M%S%f')}_{track_id:03d}.jpg"
                    ),
                    "_true_plate": plate,
                }
            )

    ocr_budget = max(1, round(len(reads) * OCR_RATE))
    confusable = [i for i, r in enumerate(reads) if any(ch in OCR_CONFUSION for ch in r["plate_text"])]
    rng.shuffle(confusable)
    confused_idx = set(confusable[:ocr_budget])

    for i, read in enumerate(reads):
        if i in confused_idx:
            text, changed = apply_ocr(read["plate_text"], rng)
            read["plate_text"] = text
            read["confidence"] = round(rng.uniform(0.55, 0.82), 3) if changed else round(rng.uniform(0.90, 0.99), 3)
        else:
            read["confidence"] = round(rng.uniform(0.92, 0.99), 3)
        del read["_true_plate"]

    reads.sort(key=lambda r: r["frame_ts"])
    return reads


def validate(reads: list[dict], cameras: list[dict]) -> None:
    camera_ids = {c["id"] for c in cameras}
    if not reads:
        raise ValueError("No reads generated")

    for read in reads:
        missing = [k for k in SCHEMA_KEYS if k not in read]
        if missing:
            raise ValueError(f"Missing keys {missing}: {read}")
        extra = [k for k in read if k not in SCHEMA_KEYS]
        if extra:
            raise ValueError(f"Unexpected keys {extra}: {read}")
        if read["camera_id"] not in camera_ids:
            raise ValueError(f"Unknown camera_id {read['camera_id']}")
        if not isinstance(read["track_id"], int):
            raise TypeError("track_id must be int")
        if not isinstance(read["plate_text"], str) or not read["plate_text"]:
            raise TypeError("plate_text must be a non-empty str")
        if not isinstance(read["confidence"], float) or not (0.0 <= read["confidence"] <= 1.0):
            raise TypeError("confidence must be a float in [0, 1]")
        datetime.fromisoformat(read["frame_ts"])
        if not isinstance(read["image_ref"], str) or not read["image_ref"]:
            raise TypeError("image_ref must be a non-empty str")

    by_track: dict[int, list[dict]] = {}
    for read in reads:
        by_track.setdefault(read["track_id"], []).append(read)

    if len(by_track) != PLATE_COUNT:
        raise ValueError(f"Expected {PLATE_COUNT} tracks, got {len(by_track)}")

    for track_id, track_reads in by_track.items():
        hop_n = len(track_reads)
        if not (HOP_RANGE[0] <= hop_n <= HOP_RANGE[1]):
            raise ValueError(f"track {track_id} has {hop_n} hops, expected {HOP_RANGE}")
        ordered = sorted(track_reads, key=lambda r: r["frame_ts"])
        for a, b in zip(ordered, ordered[1:]):
            if a["frame_ts"] >= b["frame_ts"]:
                raise ValueError(f"Non-increasing timestamps on track {track_id}")

    for plate in BLACKLISTED_PLATES:
        exact = [r for r in reads if r["plate_text"] == plate]
        if not exact:
            raise ValueError(f"Blacklisted plate {plate} never appears as exact plate_text")

    ocr_frac = sum(1 for r in reads if r["confidence"] < 0.85) / len(reads)
    if not (0.04 <= ocr_frac <= 0.18):
        raise ValueError(f"OCR confusion rate {ocr_frac:.1%} outside ~10% band")


def post_reads(reads: list[dict], url: str) -> None:
    ok = 0
    for read in reads:
        payload = json.dumps(read).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status} posting {read['track_id']}")
                ok += 1
        except urllib.error.URLError as exc:
            raise SystemExit(
                f"Failed to POST to {url}: {exc}\n"
                "Is the reads API running on localhost:8000?"
            ) from exc
    print(f"Streamed {ok}/{len(reads)} reads to {url}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic ANPR reads")
    parser.add_argument(
        "--stream",
        action="store_true",
        help=f"POST each read to {STREAM_URL} in chronological order",
    )
    parser.add_argument(
        "--endpoint",
        default=STREAM_URL,
        help="Override stream URL (only used with --stream)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(RNG_SEED)
    cameras = load_cameras()
    reads = simulate_reads(cameras, rng)
    validate(reads, cameras)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(reads, indent=2) + "\n", encoding="utf-8")

    n_tracks = len({r["track_id"] for r in reads})
    ocr_n = sum(1 for r in reads if r["confidence"] < 0.85)
    print(f"Wrote {len(reads)} reads ({n_tracks} plates) to {OUTPUT_PATH}")
    print(f"Hops per plate: {HOP_RANGE[0]}–{HOP_RANGE[1]}  |  speed {SPEED_KMH_RANGE[0]:.0f}–{SPEED_KMH_RANGE[1]:.0f} km/h")
    print(f"OCR substitutions: {ocr_n}/{len(reads)} ({ocr_n / len(reads):.1%})")
    print(f"Blacklisted plates: {', '.join(BLACKLISTED_PLATES)}")

    if args.stream:
        post_reads(reads, args.endpoint)


if __name__ == "__main__":
    main()
