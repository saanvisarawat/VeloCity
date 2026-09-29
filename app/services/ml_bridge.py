import httpx
import datetime
from fastapi import UploadFile, HTTPException

ML_API_URL = "https://backpack-perky-unrevised.ngrok-free.dev/process-video"
ML_API_KEY = "37fY8PrCvcbV9ClH_zGWtTbmWX1Kn99p"

async def process_video_via_ml(video_file: UploadFile, camera_id: str = "demo01"):
    headers = {"X-API-Key": ML_API_KEY}
    
    file_bytes = await video_file.read()
    files = {"video": (video_file.filename, file_bytes, video_file.content_type or "video/mp4")}
    data = {"camera_id": camera_id}

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(ML_API_URL, headers=headers, files=files, data=data)
            response.raise_for_status()
            ml_data = response.json()
            

            current_time = datetime.datetime.now(datetime.timezone.utc)
            
            clean_reads = []
            for read in ml_data.get("raw_reads", []):
                relative_sec = read.get("frame_ts", 0)
                absolute_ts = current_time + datetime.timedelta(seconds=relative_sec)
                
                clean_reads.append({
                    "camera_id": read.get("camera_id") or camera_id,
                    "track_id": read.get("track_id"),
                    "plate_text": read.get("plate_text") or read.get("plate_polygon") or "UNKNOWN",
                    "confidence": float(read.get("confidence", 0.95)),
                    "frame_ts": absolute_ts,
                    "image_ref": None  # Crops are not written to disk on her deployment
                })
                
            return clean_reads

        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"ML Service Error: {str(e)}")