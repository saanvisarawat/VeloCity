"""
Seeds the blacklist table with FICTIONAL demo entries for the Alerts screen.

These are NOT real vehicles, owners, or enforcement records. Plate numbers use
real, currently-valid Delhi RTO zone-code prefixes (DL01-DL14, verified against
the Delhi Transport Department's own zonal-office list at
https://transport.delhi.gov.in/transport/zonal-offices as of 2026) followed by
a fictional series letter pair and 4-digit number, so they look authentic in a
demo without corresponding to any real, currently-issued registration. Series
letters/numbers were deliberately chosen not to overlap with any plate used in
this project's own self-captured/simulated traffic data (e.g. DL01AB1234,
DL05ZZ9999).

A future task may add real-time Delhi RTO-code *validation* against this same
verified code list (rejecting malformed plates); that is deferred and not
implemented here.
"""
import asyncio
import asyncpg
import os
import redis.asyncio as redis

DB_URL = os.getenv("DATABASE_URL", "postgresql://ps127_admin:ps127_password@localhost:5432/ps127_db")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))


DEMO_BLACKLIST = [
    ("DL01CX7743", "Reported stolen — FIR #0442/2025, Kotwali PS (North Delhi)", "HIGH"),
    ("DL02BQ1190", "Suspended registration — pollution compliance pending", "MEDIUM"),
    ("DL03LK4407", "Flagged for repeated signal violations", "MEDIUM"),
    ("DL04MZ2265", "Reported stolen — FIR #1187/2025, Janakpuri PS (West Delhi)", "HIGH"),
    ("DL05TR8834", "Suspicious vehicle — flagged by beat patrol (North East Delhi)", "MEDIUM"),
    ("DL06HN3321", "Suspended registration — insurance lapse", "MEDIUM"),
    ("DL07YB9956", "Flagged for repeated signal violations", "MEDIUM"),
    ("DL08GX4470", "Reported stolen — FIR #0765/2025, Pitampura PS (North West Delhi)", "HIGH"),
    ("DL09VC1123", "Suspicious activity — flagged during checkpoint (South West Delhi)", "MEDIUM"),
    ("DL11PW6689", "Suspended registration — court order", "HIGH"),
    ("DL12KD2298", "Flagged for repeated signal violations", "MEDIUM"),
]

async def seed():
    conn = await asyncpg.connect(DB_URL)
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    print(f"Seeding {len(DEMO_BLACKLIST)} fictional demo blacklist entries...")
    try:
        for plate, reason, severity in DEMO_BLACKLIST:
            await conn.execute("""
                INSERT INTO blacklist (plate_text, reason, severity)
                VALUES ($1, $2, $3)
                ON CONFLICT (plate_text) DO UPDATE SET reason = EXCLUDED.reason, severity = EXCLUDED.severity;
            """, plate, reason, severity)


            await r.sadd("blacklist_exact", plate)
            print(f"  {plate} [{severity}] — {reason}")
        print("Done.")
    finally:
        await conn.close()
        await r.aclose()

if __name__ == "__main__":
    asyncio.run(seed())
