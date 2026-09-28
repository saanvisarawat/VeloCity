import { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { useCameras } from '../api/hooks';

// Built-in pre-recorded demos -- precomputed once on the real pipeline (see
// ml/docs/RESUME_HERE.md), so this section always works even when the live ML service (a free
// Colab GPU session behind an ngrok tunnel) isn't currently running. `reads` is fetched lazily,
// only after the user clicks to start (not on page load).
const BUILTIN_DEMOS = [
  { id: 'demo1', label: 'Clear Day', video: '/demo/demo1_video.mp4', reads: '/demo/demo1_reads.json' },
  { id: 'demo2', label: 'Rain', video: '/demo/demo2_video.mp4', reads: '/demo/demo2_reads.json' },
  { id: 'demo3', label: 'Night', video: '/demo/demo3_video.mp4', reads: '/demo/demo3_reads.json' },
];

const RECENCY_SECONDS = 0.5; // how long a detection stays drawn after its frame_ts
const NEW_DETECTION_FLASH_MS = 500; // pulse duration when a track's plate first appears

// Groups raw_reads by track_id, sorted by frame_ts, so a lookup for "current time" is a short
// linear scan per track rather than searching the whole flat list every animation frame.
function groupByTrack(reads) {
  const byTrack = new Map();
  for (const r of reads || []) {
    if (!byTrack.has(r.track_id)) byTrack.set(r.track_id, []);
    byTrack.get(r.track_id).push(r);
  }
  for (const list of byTrack.values()) list.sort((a, b) => a.frame_ts - b.frame_ts);
  return byTrack;
}

// Finds the most recent read for a track at or before `t`, within RECENCY_SECONDS -- returns null
// once too much time has passed since that track was last seen (so a box doesn't linger forever).
function currentReadForTrack(sortedReads, t) {
  let best = null;
  for (const r of sortedReads) {
    if (r.frame_ts > t) break;
    best = r;
  }
  if (best && t - best.frame_ts <= RECENCY_SECONDS) return best;
  return null;
}

function drawDetection(ctx, read, scaleX, scaleY, flashProgress) {
  const [px1, py1, px2, py2] = read.plate_box;
  const [vx1, vy1, vx2, vy2] = read.vehicle_box;

  ctx.strokeStyle = 'rgba(57, 255, 20, 0.35)';
  ctx.lineWidth = 1.5;
  ctx.strokeRect(vx1 * scaleX, vy1 * scaleY, (vx2 - vx1) * scaleX, (vy2 - vy1) * scaleY);

  const pulse = flashProgress != null ? 1 + 0.15 * (1 - flashProgress) : 1;
  const pw = (px2 - px1) * scaleX;
  const ph = (py2 - py1) * scaleY;
  const cx = ((px1 + px2) / 2) * scaleX;
  const cy = ((py1 + py2) / 2) * scaleY;

  ctx.save();
  ctx.translate(cx, cy);
  ctx.scale(pulse, pulse);
  ctx.strokeStyle = flashProgress != null ? `rgba(57, 255, 20, ${0.6 + 0.4 * (1 - flashProgress)})` : '#39ff14';
  ctx.lineWidth = 2.5;
  ctx.strokeRect(-pw / 2, -ph / 2, pw, ph);
  ctx.restore();

  const label = `${read.plate_text}${read.confidence != null ? ` (${Math.round(read.confidence * 100)}%)` : ''}`;
  ctx.font = '13px "JetBrains Mono", monospace';
  const textWidth = ctx.measureText(label).width;
  const labelX = px1 * scaleX;
  const labelY = py1 * scaleY - 6;
  ctx.fillStyle = 'rgba(3, 4, 2, 0.85)';
  ctx.fillRect(labelX - 3, labelY - 15, textWidth + 6, 18);
  ctx.fillStyle = '#39ff14';
  ctx.fillText(label, labelX, labelY - 2);
}

// Shared canvas-overlay engine: given a size source (video or image element) and a set of reads
// grouped by track, keeps a <canvas> sized to match the rendered element and redraws detections
// either every animation frame (video, `live: true`) or once (image, `live: false`).
function useOverlayCanvas({ mediaRef, canvasRef, byTrack, frameWidth, frameHeight, live, getTime }) {
  const lastSeenRef = useRef(new Map()); // track_id -> {plateText, firstShownAt}

  useEffect(() => {
    const media = mediaRef.current;
    const canvas = canvasRef.current;
    if (!media || !canvas) return undefined;

    let rafId = null;

    const resize = () => {
      const rect = media.getBoundingClientRect();
      canvas.width = rect.width;
      canvas.height = rect.height;
    };

    const render = () => {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!frameWidth || !frameHeight || canvas.width === 0) {
        if (live) rafId = requestAnimationFrame(render);
        return;
      }
      const scaleX = canvas.width / frameWidth;
      const scaleY = canvas.height / frameHeight;
      const t = getTime();
      const now = performance.now();

      for (const [trackId, sortedReads] of byTrack.entries()) {
        const read = currentReadForTrack(sortedReads, t);
        if (!read) continue;

        const seen = lastSeenRef.current.get(trackId);
        if (!seen || seen.plateText !== read.plate_text) {
          lastSeenRef.current.set(trackId, { plateText: read.plate_text, firstShownAt: now });
        }
        const shownAt = lastSeenRef.current.get(trackId).firstShownAt;
        const elapsed = now - shownAt;
        const flashProgress = elapsed < NEW_DETECTION_FLASH_MS ? elapsed / NEW_DETECTION_FLASH_MS : null;

        drawDetection(ctx, read, scaleX, scaleY, flashProgress);
      }

      if (live) rafId = requestAnimationFrame(render);
    };

    resize();
    render();
    // For the non-live (image) case, the element's box can still be 0-sized here if the image
    // hasn't finished loading yet -- redraw (not just resize) whenever that box actually changes,
    // otherwise the overlay never appears once the image's real dimensions resolve.
    const resizeObserver = new ResizeObserver(() => {
      resize();
      render();
    });
    resizeObserver.observe(media);

    if (live) rafId = requestAnimationFrame(render);

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
    };
  }, [mediaRef, canvasRef, byTrack, frameWidth, frameHeight, live, getTime]);
}

function PlateOverlayPlayer({ videoSrc, reads, frameWidth, frameHeight }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const byTrack = useMemo(() => groupByTrack(reads), [reads]);
  const [dims, setDims] = useState({ w: frameWidth, h: frameHeight });

  useOverlayCanvas({
    mediaRef: videoRef,
    canvasRef,
    byTrack,
    frameWidth: dims.w,
    frameHeight: dims.h,
    live: true,
    getTime: () => videoRef.current?.currentTime ?? 0,
  });

  return (
    <div className="overlay-player">
      <video
        ref={videoRef}
        src={videoSrc}
        autoPlay
        loop
        muted
        playsInline
        onLoadedMetadata={(e) => {
          if (!frameWidth || !frameHeight) {
            setDims({ w: e.target.videoWidth, h: e.target.videoHeight });
          }
        }}
      />
      <canvas ref={canvasRef} className="overlay-canvas" />
    </div>
  );
}

function ImageOverlay({ imageSrc, detections, frameWidth, frameHeight }) {
  const imgRef = useRef(null);
  const canvasRef = useRef(null);
  const byTrack = useMemo(() => groupByTrack((detections || []).map((d) => ({ ...d, frame_ts: 0 }))), [detections]);

  useOverlayCanvas({
    mediaRef: imgRef,
    canvasRef,
    byTrack,
    frameWidth,
    frameHeight,
    live: false,
    getTime: () => 0,
  });

  return (
    <div className="overlay-player">
      <img ref={imgRef} src={imageSrc} alt="Uploaded frame" />
      <canvas ref={canvasRef} className="overlay-canvas" />
    </div>
  );
}

function useMlServiceStatus() {
  const [status, setStatus] = useState({ checked: false, available: false });
  useEffect(() => {
    let cancelled = false;
    api
      .get('/api/v1/ml/status')
      .then((res) => !cancelled && setStatus({ checked: true, available: !!res.available }))
      .catch(() => !cancelled && setStatus({ checked: true, available: false }));
    return () => {
      cancelled = true;
    };
  }, []);
  return status;
}

// Which registered camera an upload counts as: the ML reads are ingested against it, so the dashboard's
// counts, heatmap and alert rules pick them up like any other camera read.
function useCameraChoice() {
  const cameras = useCameras().data || [];
  const [picked, setPicked] = useState('');
  return { cameras, cameraId: picked || cameras[0]?.id || '', setCameraId: setPicked };
}

function CameraPicker({ cameras, cameraId, onChange }) {
  return (
    <label className="ml-camera-picker">
      <span>Count as camera</span>
      <select value={cameraId} onChange={(e) => onChange(e.target.value)}>
        {cameras.map((c) => (
          <option key={c.id} value={c.id}>
            {c.id} · {c.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function IngestNote({ result, cameraId }) {
  if (result.ingested > 0) {
    return (
      <p>
        {result.ingested} plate read{result.ingested === 1 ? '' : 's'} added to the dashboard as {cameraId}.
      </p>
    );
  }
  return result.ingest_skipped ? <p>Not added to the dashboard: {result.ingest_skipped}.</p> : null;
}

function VideoTestCard() {
  const [file, setFile] = useState(null);
  const [objectUrl, setObjectUrl] = useState(null);
  const [state, setState] = useState('idle'); // idle | uploading | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const mlStatus = useMlServiceStatus();
  const { cameras, cameraId, setCameraId } = useCameraChoice();
  const queryClient = useQueryClient();

  const handleFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setObjectUrl(URL.createObjectURL(f));
    setResult(null);
    setError(null);
    setState('idle');
  };

  const submit = async () => {
    if (!file) return;
    setState('uploading');
    setError(null);
    try {
      const form = new FormData();
      form.append('video', file);
      form.append('camera_id', cameraId || 'demo01');
      const res = await api.postForm('/api/v1/ml/process-video', form);
      setResult(res);
      queryClient.invalidateQueries();
      setState('done');
    } catch (e) {
      setError(e.message || 'Processing failed');
      setState('error');
    }
  };

  const frameWidth = result?.raw_reads?.[0]?.frame_width;
  const frameHeight = result?.raw_reads?.[0]?.frame_height;

  return (
    <div className="glass-card ml-test-card">
      <h3>Upload a video</h3>
      <p className="ml-test-caption">
        Runs the real pipeline (tracking + plate localization + OCR + multi-frame voting) on the live
        ML service.
      </p>
      <div className={`ml-status-pill${mlStatus.available ? ' online' : ' offline'}`}>
        <span className="dot" /> {mlStatus.checked ? (mlStatus.available ? 'Live ML: online' : 'Live ML: offline') : 'Checking…'}
      </div>

      <CameraPicker cameras={cameras} cameraId={cameraId} onChange={setCameraId} />
      <input type="file" accept="video/*" onChange={handleFile} />
      <button className="btn-pill btn-pill-sm" disabled={!file || state === 'uploading'} onClick={submit}>
        {state === 'uploading' ? 'Processing on GPU…' : 'Process video'}
      </button>

      {state === 'error' && (
        <p className="ml-test-error">
          {error} — the live service may be offline (it runs on a free Colab GPU session that has to
          be manually kept running). Try the built-in demo above instead.
        </p>
      )}

      {objectUrl && state !== 'error' && (
        <PlateOverlayPlayer videoSrc={objectUrl} reads={result?.raw_reads || []} frameWidth={frameWidth} frameHeight={frameHeight} />
      )}

      {result && (
        <div className="ml-test-summary">
          <p>Processed in {result.processing_seconds}s.</p>
          <IngestNote result={result} cameraId={cameraId} />
          <div className="ml-plate-chip-row">
            {(result.voted_reads || []).map((v) => (
              <span key={v.track_id} className={`ml-plate-chip${v.is_valid_format ? ' valid' : ''}`}>
                {v.plate_text} · {Math.round(v.confidence * 100)}%
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ImageTestCard() {
  const { cameras, cameraId, setCameraId } = useCameraChoice();
  const queryClient = useQueryClient();
  const [file, setFile] = useState(null);
  const [objectUrl, setObjectUrl] = useState(null);
  const [state, setState] = useState('idle');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setObjectUrl(URL.createObjectURL(f));
    setResult(null);
    setError(null);
    setState('idle');
  };

  const submit = async () => {
    if (!file) return;
    setState('uploading');
    setError(null);
    try {
      const form = new FormData();
      form.append('image', file);
      form.append('camera_id', cameraId || 'demo01');
      const res = await api.postForm('/api/v1/ml/process-image', form);
      setResult(res);
      queryClient.invalidateQueries();
      setState('done');
    } catch (e) {
      setError(e.message || 'Processing failed');
      setState('error');
    }
  };

  const frameWidth = result?.detections?.[0]?.frame_width;
  const frameHeight = result?.detections?.[0]?.frame_height;

  return (
    <div className="glass-card ml-test-card">
      <h3>Upload an image</h3>
      <p className="ml-test-caption">One detection pass -- no tracking or multi-frame voting, just whatever plates are visible.</p>

      <CameraPicker cameras={cameras} cameraId={cameraId} onChange={setCameraId} />
      <input type="file" accept="image/*" onChange={handleFile} />
      <button className="btn-pill btn-pill-sm" disabled={!file || state === 'uploading'} onClick={submit}>
        {state === 'uploading' ? 'Processing on GPU…' : 'Process image'}
      </button>

      {state === 'error' && (
        <p className="ml-test-error">
          {error} — the live service may be offline right now. Try the built-in demo above instead.
        </p>
      )}

      {objectUrl && state !== 'error' && (
        <ImageOverlay imageSrc={objectUrl} detections={result?.detections || []} frameWidth={frameWidth} frameHeight={frameHeight} />
      )}

      {result && (
        <div className="ml-test-summary">
          <p>Processed in {result.processing_seconds}s · {result.detections.length} plate(s) found.</p>
          <IngestNote result={result} cameraId={cameraId} />
          <div className="ml-plate-chip-row">
            {result.detections.map((d, i) => (
              <span key={i} className="ml-plate-chip">
                {d.plate_text} · {Math.round(d.confidence * 100)}%
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function MLDemo() {
  const [started, setStarted] = useState(false);
  const [demoIndex, setDemoIndex] = useState(0);
  const [demoReads, setDemoReads] = useState(null);
  const [demoDims, setDemoDims] = useState({ w: null, h: null });
  const demo = BUILTIN_DEMOS[demoIndex];

  useEffect(() => {
    if (!started) return undefined;
    let cancelled = false;
    setDemoReads(null);
    fetch(demo.reads)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        setDemoReads(data.raw_reads || []);
        setDemoDims({ w: data.raw_reads?.[0]?.frame_width, h: data.raw_reads?.[0]?.frame_height });
      })
      .catch(() => !cancelled && setDemoReads([]));
    return () => {
      cancelled = true;
    };
  }, [started, demo.reads]);

  return (
    <div className="ml-demo-page">
      <div className="landing-section-header">
        <p className="landing-eyebrow">Live Model Test</p>
        <h2 className="landing-section-heading">See The Model Read Plates</h2>
      </div>

      <div className="glass-card ml-test-card ml-demo-builtin">
        <div className="ml-demo-selector">
          {BUILTIN_DEMOS.map((d, i) => (
            <button
              key={d.id}
              className={`btn-pill btn-pill-sm${i === demoIndex ? '' : ' btn-pill-outline'}`}
              onClick={() => setDemoIndex(i)}
            >
              {d.label}
            </button>
          ))}
        </div>
        {!started ? (
          <div className="ml-demo-start">
            <button className="btn-pill" onClick={() => setStarted(true)}>
              ▶ Test
            </button>
          </div>
        ) : demoReads ? (
          <PlateOverlayPlayer videoSrc={demo.video} reads={demoReads} frameWidth={demoDims.w} frameHeight={demoDims.h} />
        ) : (
          <p className="ml-test-caption">Loading demo…</p>
        )}
      </div>

      <div className="ml-test-grid">
        <VideoTestCard />
        <ImageTestCard />
      </div>
    </div>
  );
}
