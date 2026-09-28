import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Pane, Popup, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet.heat';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from 'recharts';

import {
  useCameras,
  useSummary,
  useDensity,
  useOdMatrix,
  useBottlenecks,
  useHeatmap,
  useLiveTraffic,
  useLiveTrafficHistory,
  useLiveTrafficWindow,
  useCameraRecentReads,
  useDelhiVehicleStats,
  useDelhiVehicleFleetTrend,
} from '../api/hooks';
import { KpiSkeleton, SkeletonBlock } from '../components/Skeleton';
import { EmptyState, ErrorState, StatePanel } from '../components/StatePanel';
import { arcPoints } from '../utils/geo';
import { API_BASE } from '../api/client';

const TIME_RANGE_MINUTES = {
  'Last 30 minutes': 30,
  'Last 1 hour': 60,
  'Last 6 hours': 360,
  Today: 1440,
};

const DEFAULT_CENTER = [28.6139, 77.209]; // Delhi (Connaught Place area)
const DEFAULT_ZOOM = 11;
// Esri's dark-gray canvas basemap — free and keyless, unlike CARTO's basemap tiles
// (which now gate anonymous access and serve an "API KEY REQUIRED" watermark tile).
const DARK_TILE_URL =
  'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
const DARK_TILE_ATTRIBUTION = '&copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors';

const CAMERA_HEAT_GRADIENT = {
  0.0: 'rgba(57,255,20,0)',
  0.3: 'rgba(57,255,20,0.35)',
  0.6: 'rgba(57,255,20,0.65)',
  1.0: '#39ff14',
};
// Congestion scale for the live layer: free-flowing green through amber to red.
const LIVE_HEAT_GRADIENT = {
  0.0: 'rgba(57,255,20,0)',
  0.25: 'rgba(57,255,20,0.55)',
  0.5: '#e6eb14',
  0.75: '#ff8c00',
  1.0: '#ff2d2d',
};

function HeatLayer({ points, gradient = CAMERA_HEAT_GRADIENT, radius = 38, blur = 28, max = 1.0, maxZoom = 15 }) {
  const map = useMap();

  useEffect(() => {
    if (!points.length) return undefined;
    const heat = L.heatLayer(points, { radius, blur, maxZoom, gradient, max }).addTo(map);
    return () => map.removeLayer(heat);
  }, [map, points, gradient, radius, blur, max, maxZoom]);

  return null;
}

// Data credit for the live-traffic feed, shown in the map's attribution strip whenever any of its
// layers (heat, road colours, point markers) are on the map.
function LiveDataAttribution({ active }) {
  const map = useMap();
  useEffect(() => {
    if (!active) return undefined;
    const text = `&copy; 1992 - ${new Date().getFullYear()} TomTom`;
    map.attributionControl.addAttribution(text);
    return () => map.attributionControl.removeAttribution(text);
  }, [map, active]);
  return null;
}

function congestionColor(congestion) {
  if (congestion >= 0.45) return '#ff2d2d';
  if (congestion >= 0.3) return '#ff8c00';
  if (congestion >= 0.15) return '#e6eb14';
  return '#39ff14';
}

function statusDotColor(status) {
  return status === 'Online' ? 'var(--accent)' : 'var(--text-faint)';
}

function densityRadius(level) {
  if (level === 'HIGH') return 13;
  if (level === 'MEDIUM') return 10;
  return 7;
}

function densityOpacity(level) {
  if (level === 'HIGH') return 0.95;
  if (level === 'MEDIUM') return 0.65;
  return 0.4;
}

function formatDelta(today, yesterday) {
  if (!yesterday || yesterday < 10) return { text: 'not enough prior-day data', neutral: true };
  const pct = ((today - yesterday) / yesterday) * 100;
  const sign = pct >= 0 ? '+' : '';
  return { text: `${sign}${pct.toFixed(1)}% vs yesterday`, neutral: false };
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="tooltip-label">{new Date(label).toLocaleTimeString()}</div>
      {payload.map((p) => (
        <div key={p.dataKey}>
          {p.name}: <strong>{p.value ?? '—'}</strong>
        </div>
      ))}
    </div>
  );
}

function TrendChart({ windowMinutes }) {
  // Snapshots are recorded every ~20 minutes, so short windows would hold 1-2 points; always show at least 6h.
  const hours = Math.max(6, Math.ceil(windowMinutes / 60));
  const historyQuery = useLiveTrafficHistory(hours);
  const points = historyQuery.data || [];

  return (
    <section className="glass-card map-card chart-card">
      <div className="section-heading">
        <div>
          <h2>Traffic Trend</h2>
          <p>City-wide average speed and congestion from the live traffic feed, recorded every 20 minutes</p>
        </div>
        <div className="chart-legend">
          <span className="chart-legend-item">
            <span className="chart-legend-swatch" style={{ background: '#39ff14' }} />
            Avg speed (km/h)
          </span>
          <span className="chart-legend-item">
            <span className="chart-legend-swatch" style={{ background: '#ff8c00' }} />
            Congestion (%)
          </span>
        </div>
      </div>

      {historyQuery.isLoading && <SkeletonBlock height={220} />}
      {historyQuery.isError && (
        <ErrorState message="Could not load trend data" onRetry={() => historyQuery.refetch()} />
      )}
      {historyQuery.data && points.length < 2 && (
        <EmptyState
          variant="empty"
          title="Recording live traffic"
          message="A new point is saved every 20 minutes, so the trend fills in as time passes."
        />
      )}
      {points.length >= 2 && (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={points} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid stroke="rgba(57,255,20,0.08)" vertical={false} />
            <XAxis
              dataKey="ts"
              tickFormatter={(v) => new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              stroke="var(--text-faint)"
              fontSize={11}
              fontFamily="var(--mono)"
              tickLine={false}
            />
            <YAxis yAxisId="left" stroke="var(--text-faint)" fontSize={11} fontFamily="var(--mono)" tickLine={false} />
            <YAxis
              yAxisId="right"
              orientation="right"
              stroke="var(--text-faint)"
              fontSize={11}
              fontFamily="var(--mono)"
              tickLine={false}
            />
            <Tooltip content={<ChartTooltip />} />
            <Area
              yAxisId="right"
              type="monotone"
              dataKey="congestion_pct"
              name="Congestion (%)"
              stroke="#ff8c00"
              fill="rgba(255,140,0,0.15)"
              strokeWidth={2}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="avg_speed_kmh"
              name="Avg speed (km/h)"
              stroke="#39ff14"
              strokeWidth={2}
              dot={{ r: 3 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </section>
  );
}

function CameraDetailPanel({ cameraId, camera, onClose }) {
  const recentReadsQuery = useCameraRecentReads(cameraId);
  const thumbs = (recentReadsQuery.data || []).filter((r) => r.image_ref).slice(0, 2);

  return (
    <div className="camera-detail-panel">
      <div className="camera-detail-header">
        <span className="camera-detail-title">
          {cameraId} — {camera?.name}
        </span>
        <button className="btn btn-sm btn-ghost" onClick={onClose}>
          Close
        </button>
      </div>

      {recentReadsQuery.isLoading && <SkeletonBlock height={60} />}
      {recentReadsQuery.isError && (
        <ErrorState message="Could not load recent reads" onRetry={() => recentReadsQuery.refetch()} />
      )}

      {recentReadsQuery.data && (
        <>
          <div className="camera-detail-stats">
            <span>
              Recent reads: <strong>{recentReadsQuery.data.length}</strong>
            </span>
            <span>
              Status: <strong>{camera?.status}</strong>
            </span>
            <span>
              Density: <strong>{camera?.density_level}</strong>
            </span>
          </div>

          {thumbs.length > 0 ? (
            <div className="camera-detail-thumbs">
              {thumbs.map((r, i) => (
                <img
                  key={i}
                  className="camera-detail-thumb"
                  src={r.image_ref}
                  alt={r.plate_text}
                  onError={(e) => (e.target.style.display = 'none')}
                />
              ))}
            </div>
          ) : (
            <p style={{ color: 'var(--text-faint)', fontSize: 11, margin: 0 }}>
              No plate-crop images available for this camera's recent reads.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function DelhiReferencePanel() {
  const statsQuery = useDelhiVehicleStats();

  return (
    <section className="glass-card map-card reference-panel" style={{ marginTop: 18 }}>
      <div className="section-heading">
        <div>
          <h2>Delhi Vehicle Registrations</h2>
          <p>External reference data — not from this platform's camera network</p>
        </div>
        <span className="reference-badge mono">EXTERNAL REFERENCE</span>
      </div>

      {statsQuery.isLoading && <SkeletonBlock height={80} />}
      {statsQuery.isError && (
        <ErrorState message="Could not load reference data" onRetry={() => statsQuery.refetch()} />
      )}

      {statsQuery.data && (
        <>
          <div className="reference-stat-grid">
            <div className="reference-stat">
              <span className="reference-stat-label">Total Registered Vehicles</span>
              <span className="reference-stat-value mono">
                {statsQuery.data.total_registered_vehicles.toLocaleString('en-IN')}
              </span>
            </div>
            <div className="reference-stat">
              <span className="reference-stat-label">YoY Growth</span>
              <span className="reference-stat-value mono">+{statsQuery.data.yoy_growth_pct}%</span>
            </div>
            <div className="reference-stat">
              <span className="reference-stat-label">Two-Wheeler Share</span>
              <span className="reference-stat-value mono">{statsQuery.data.two_wheeler_pct}%</span>
            </div>
            <div className="reference-stat">
              <span className="reference-stat-label">Vehicles / 1000 Population</span>
              <span className="reference-stat-value mono">{statsQuery.data.vehicles_per_1000_population}</span>
            </div>
          </div>
          <p className="reference-footnote">
            As of {statsQuery.data.as_of} · Source:{' '}
            <a href={statsQuery.data.source_url} target="_blank" rel="noreferrer">
              {statsQuery.data.source}
            </a>
          </p>
        </>
      )}
    </section>
  );
}

const FLEET_CATEGORY_LABELS = {
  cars_and_jeeps: 'Cars & Jeeps',
  motorcycles_scooters: 'Motorcycles & Scooters',
  auto_rickshaws: 'Auto Rickshaws',
  taxis: 'Taxis',
  buses: 'Buses',
  e_rickshaws_other: 'E-Rickshaws & Other',
  ambulances: 'Ambulances',
  tractors_goods_others: 'Tractors & Goods Vehicles',
};

function FleetTrendTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="tooltip-label">{label}</div>
      <div>
        Total plying: <strong>{payload[0].value.toLocaleString('en-IN')}</strong>
      </div>
    </div>
  );
}

function DelhiFleetTrendPanel() {
  const fleetQuery = useDelhiVehicleFleetTrend();

  const latestYear = fleetQuery.data?.years[fleetQuery.data.years.length - 1];
  const breakdown = useMemo(() => {
    if (!latestYear) return [];
    const total = latestYear.total_vehicles_plying;
    return Object.keys(FLEET_CATEGORY_LABELS)
      .map((key) => ({ key, label: FLEET_CATEGORY_LABELS[key], count: latestYear[key], pct: (latestYear[key] / total) * 100 }))
      .sort((a, b) => b.count - a.count);
  }, [latestYear]);

  return (
    <section className="glass-card map-card reference-panel" style={{ marginTop: 18 }}>
      <div className="section-heading">
        <div>
          <h2>Delhi Vehicle Fleet, 2015-25</h2>
          <p>External reference dataset — separate source from the summary above, figures don't reconcile exactly</p>
        </div>
        <span className="reference-badge mono">EXTERNAL REFERENCE</span>
      </div>

      {fleetQuery.isLoading && <SkeletonBlock height={220} />}
      {fleetQuery.isError && (
        <ErrorState message="Could not load fleet trend data" onRetry={() => fleetQuery.refetch()} />
      )}

      {fleetQuery.data && (
        <>
          <ResponsiveContainer width="100%" height={200}>
            <ComposedChart data={fleetQuery.data.years} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke="rgba(57,255,20,0.08)" vertical={false} />
              <XAxis dataKey="fiscal_year" stroke="var(--text-faint)" fontSize={11} fontFamily="var(--mono)" tickLine={false} />
              <YAxis
                stroke="var(--text-faint)"
                fontSize={11}
                fontFamily="var(--mono)"
                tickLine={false}
                tickFormatter={(v) => `${(v / 1000000).toFixed(1)}M`}
              />
              <Tooltip content={<FleetTrendTooltip />} />
              <Area
                type="monotone"
                dataKey="total_vehicles_plying"
                name="Total vehicles plying"
                stroke="#39ff14"
                fill="rgba(57,255,20,0.15)"
                strokeWidth={2}
              />
            </ComposedChart>
          </ResponsiveContainer>

          <div className="field-label" style={{ marginTop: 14 }}>
            Category breakdown — {latestYear.fiscal_year}
          </div>
          <ul className="bottleneck-list">
            {breakdown.map((b, i) => (
              <li key={b.key} className="bottleneck-row">
                <span className="segment mono" style={{ opacity: 0.4 + (breakdown.length - i) * 0.08 }}>
                  {b.label}
                </span>
                <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                  {b.count.toLocaleString('en-IN')}
                </span>
                <span className="ratio">{b.pct.toFixed(1)}%</span>
              </li>
            ))}
          </ul>

          <p className="reference-footnote">
            <span className={fleetQuery.data.is_live ? 'reference-live-tag live' : 'reference-live-tag'}>
              {fleetQuery.data.is_live ? '● LIVE-FETCHED' : '○ STATIC FALLBACK'}
            </span>
            {fleetQuery.data.last_fetched_at
              ? ` · last refreshed ${new Date(fleetQuery.data.last_fetched_at).toLocaleString()}`
              : ' · upstream fetch not yet completed since server start'}
            {' · '}Source:{' '}
            <a href={fleetQuery.data.source_url} target="_blank" rel="noreferrer">
              {fleetQuery.data.source}
            </a>
          </p>
        </>
      )}
    </section>
  );
}

export default function Dashboard() {
  const [timeRange, setTimeRange] = useState('Last 30 minutes');
  const [cameraStatus, setCameraStatus] = useState('All Cameras');
  const [trafficDensity, setTrafficDensity] = useState('All');
  const [selectedCameraId, setSelectedCameraId] = useState(null);

  const windowMinutes = TIME_RANGE_MINUTES[timeRange];

  const camerasQuery = useCameras();
  const summaryQuery = useSummary();
  const densityQuery = useDensity(windowMinutes);
  const odQuery = useOdMatrix();
  const bottlenecksQuery = useBottlenecks();
  const heatmapQuery = useHeatmap();
  const liveTrafficQuery = useLiveTraffic();
  const liveWindowQuery = useLiveTrafficWindow(windowMinutes);
  const [showLiveHeat, setShowLiveHeat] = useState(true);
  const [showRoads, setShowRoads] = useState(false);
  const [showCameraHeat, setShowCameraHeat] = useState(false);

  const densityByCameraId = useMemo(() => {
    const map = new Map();
    (densityQuery.data || []).forEach((d) => map.set(d.camera_id, d));
    return map;
  }, [densityQuery.data]);

  const cameraLookup = useMemo(() => {
    const map = new Map();
    (camerasQuery.data || []).forEach((c) => map.set(c.id, c));
    return map;
  }, [camerasQuery.data]);

  const enrichedCameras = useMemo(() => {
    return (camerasQuery.data || []).map((cam) => {
      const density = densityByCameraId.get(cam.id);
      return {
        ...cam,
        density_level: density ? density.density_level : 'LOW',
        vehicle_count: density ? density.vehicle_count : 0,
      };
    });
  }, [camerasQuery.data, densityByCameraId]);

  const filteredCameras = useMemo(() => {
    return enrichedCameras.filter((cam) => {
      const statusMatch = cameraStatus === 'All Cameras' || cam.status === cameraStatus;
      const trafficMatch =
        trafficDensity === 'All' || cam.density_level === trafficDensity.toUpperCase();
      return statusMatch && trafficMatch;
    });
  }, [enrichedCameras, cameraStatus, trafficDensity]);

  const heatPoints = useMemo(() => {
    return (heatmapQuery.data?.features || []).map((f) => [
      f.geometry.coordinates[1],
      f.geometry.coordinates[0],
      f.properties.density_intensity,
    ]);
  }, [heatmapQuery.data]);

  const live = liveTrafficQuery.data;
  const liveAvailable = !!live?.available;
  const liveCity = liveAvailable ? live.city : null;
  const liveWin = liveWindowQuery.data;
  const liveWinAvailable = !!liveWin?.available;
  const livePoints = useMemo(
    () => (liveWin?.points || []).map((p) => [p.lat, p.lon, p.intensity]),
    [liveWin],
  );

  const odArcs = useMemo(() => {
    if (!camerasQuery.data || !odQuery.data) return [];
    const maxTrips = Math.max(...odQuery.data.map((o) => o.trip_count), 1);
    return odQuery.data
      .map((od) => {
        const from = cameraLookup.get(od.origin);
        const to = cameraLookup.get(od.destination);
        if (!from || !to) return null;
        return {
          key: `${od.origin}->${od.destination}`,
          points: arcPoints([from.lat, from.lon], [to.lat, to.lon]),
          weight: 1 + (od.trip_count / maxTrips) * 5,
          opacity: 0.25 + (od.trip_count / maxTrips) * 0.55,
          trip_count: od.trip_count,
          origin: od.origin,
          destination: od.destination,
        };
      })
      .filter(Boolean);
  }, [odQuery.data, cameraLookup, camerasQuery.data]);

  const summary = summaryQuery.data;
  const vehiclesDelta = summary
    ? formatDelta(summary.vehicles_tracked_today, summary.vehicles_tracked_yesterday)
    : null;

  const selectedCamera = selectedCameraId ? cameraLookup.get(selectedCameraId) : null;

  return (
    <div>
      <header className="page-header">
        <div>
          <h1>City Traffic Analytics</h1>
          <p>Live road traffic across the city, plus plate reads ingested from the ANPR pipeline</p>
        </div>
      </header>

      {/* ---------------- KPI Row ---------------- */}
      <section className="kpi-grid">
        {summaryQuery.isLoading && [0, 1, 2, 3].map((i) => <KpiSkeleton key={i} />)}

        {summaryQuery.isError && (
          <div className="glass-card kpi-card" style={{ gridColumn: '1 / -1' }}>
            <ErrorState message="Could not load KPI summary" onRetry={() => summaryQuery.refetch()} />
          </div>
        )}

        {summary && (
          <>
            <div className="glass-card kpi-card">
              <p className="kpi-label">Vehicles Tracked Today</p>
              <h2>{summary.vehicles_tracked_today.toLocaleString()}</h2>
              <span className={`kpi-delta${vehiclesDelta.neutral ? ' neutral' : ''}`}>
                {vehiclesDelta.text}
              </span>
            </div>

            <div className="glass-card kpi-card">
              <p className="kpi-label">Average City Speed</p>
              <h2>{liveCity ? `${liveCity.avg_speed_kmh} km/h` : '—'}</h2>
              <span className="kpi-delta neutral">
                {liveCity ? `live road feed · ${liveCity.point_count} points, free-flow ${liveCity.avg_free_flow_kmh} km/h` : 'live feed unavailable'}
              </span>
            </div>

            <div className="glass-card kpi-card">
              <p className="kpi-label">Active Alerts</p>
              <h2>{String(summary.active_alerts).padStart(2, '0')}</h2>
              <span className="kpi-delta">requires attention</span>
            </div>

            <div className="glass-card kpi-card">
              <p className="kpi-label">Cameras Online</p>
              <h2>
                {summary.cameras_online} / {summary.cameras_total}
              </h2>
              <span className="kpi-delta">
                {summary.cameras_total
                  ? `${Math.round((summary.cameras_online / summary.cameras_total) * 100)}% operational`
                  : 'no cameras registered'}
              </span>
            </div>
          </>
        )}
      </section>

      {/* ---------------- Main Content ---------------- */}
      <main className="main-grid">
        <section className="glass-card map-card">
          <div className="section-heading">
            <div>
              <h2>Traffic Map</h2>
              <p>Live traffic heatmap, camera markers, and origin-destination flows</p>
            </div>
          </div>

          {camerasQuery.isLoading || heatmapQuery.isLoading ? (
            <SkeletonBlock height={520} />
          ) : camerasQuery.isError ? (
            <ErrorState message="Could not load camera locations" onRetry={() => camerasQuery.refetch()} />
          ) : (
            <MapContainer center={DEFAULT_CENTER} zoom={DEFAULT_ZOOM} scrollWheelZoom className="traffic-map">
              <TileLayer attribution={DARK_TILE_ATTRIBUTION} url={DARK_TILE_URL} />

              <LiveDataAttribution active={liveAvailable || liveWinAvailable} />
              {liveAvailable && showRoads && (
                // Own pane: the basemap's tile pane carries a hue-rotate tint (App.css) that would
                // recolour these road colours, so the overlay sits above it, untinted.
                <Pane name="live-roads" style={{ zIndex: 250 }}>
                  <TileLayer url={`${API_BASE}/api/v1/analytics/live-traffic/tiles/{z}/{x}/{y}.png`} opacity={0.85} />
                </Pane>
              )}
              {showCameraHeat && <HeatLayer points={heatPoints} />}
              {liveWinAvailable && showLiveHeat && (
                <HeatLayer points={livePoints} gradient={LIVE_HEAT_GRADIENT} radius={45} blur={35} max={0.9} maxZoom={DEFAULT_ZOOM} />
              )}
              {liveWinAvailable &&
                liveWin.points.map((p) => (
                  <CircleMarker
                    key={p.name}
                    center={[p.lat, p.lon]}
                    radius={4}
                    pathOptions={{ color: '#0a0d0a', weight: 1, fillColor: congestionColor(p.congestion), fillOpacity: 0.95 }}
                  >
                    <Popup>
                      <strong>{p.name}</strong>
                      <br />
                      {p.current_speed_kmh} km/h {liveWin.snapshots > 1 ? `(avg, ${timeRange.toLowerCase()})` : 'now'} · {p.free_flow_speed_kmh} km/h free-flow
                      <br />
                      {Math.round(p.congestion * 100)}% slower than free-flow
                      {p.road_closure && (
                        <>
                          <br />
                          Closure reported nearby
                        </>
                      )}
                    </Popup>
                  </CircleMarker>
                ))}

              {odArcs.map((arc) => (
                <Polyline
                  key={arc.key}
                  positions={arc.points}
                  pathOptions={{ color: '#39ff14', weight: arc.weight, opacity: arc.opacity }}
                >
                  <Popup>
                    <strong className="mono">
                      {arc.origin} → {arc.destination}
                    </strong>
                    <br />
                    {arc.trip_count} trips today
                  </Popup>
                </Polyline>
              ))}

              {filteredCameras.map((camera) => (
                <CircleMarker
                  key={camera.id}
                  center={[camera.lat, camera.lon]}
                  radius={densityRadius(camera.density_level)}
                  pathOptions={{
                    color: statusDotColor(camera.status),
                    fillColor: statusDotColor(camera.status),
                    fillOpacity: densityOpacity(camera.density_level),
                    weight: camera.status === 'Online' ? 2 : 1,
                  }}
                  eventHandlers={{ click: () => setSelectedCameraId(camera.id) }}
                >
                  <Popup>
                    <strong className="mono">{camera.id}</strong> — {camera.name}
                    <br />
                    Status: {camera.status}
                    <br />
                    Vehicles ({timeRange}): {camera.vehicle_count}
                    <br />
                    Density: {camera.density_level}
                  </Popup>
                </CircleMarker>
              ))}
            </MapContainer>
          )}

          <div className="live-legend">
            {liveWinAvailable ? (
              <>
                <span className="live-legend-title">Live traffic</span>
                <span>Free-flowing</span>
                <span className="live-legend-bar" />
                <span>Congested</span>
                <span className="live-legend-time">
                  {liveWin.snapshots > 1
                    ? `average of ${liveWin.snapshots} snapshots · ${timeRange.toLowerCase()} · `
                    : 'current reading · '}
                  updated {new Date(liveWin.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </>
            ) : (
              <span className="live-legend-time">
                {liveWindowQuery.isLoading ? 'Loading live traffic…' : 'Live traffic unavailable right now'}
              </span>
            )}
          </div>

          {!camerasQuery.isLoading && !camerasQuery.isError && filteredCameras.length === 0 && (
            <EmptyState
              variant="empty-search"
              title="No cameras match these filters"
              message="Try widening the camera status or traffic density filter."
            />
          )}

          {selectedCameraId && (
            <CameraDetailPanel
              cameraId={selectedCameraId}
              camera={cameraLookup.get(selectedCameraId)}
              onClose={() => setSelectedCameraId(null)}
            />
          )}
        </section>

        {/* ---------------- Filters ---------------- */}
        <aside className="glass-card filter-card">
          <h2>Filters</h2>

          <label className="field-label">Time Range</label>
          <select value={timeRange} onChange={(e) => setTimeRange(e.target.value)}>
            {Object.keys(TIME_RANGE_MINUTES).map((label) => (
              <option key={label}>{label}</option>
            ))}
          </select>

          <label className="field-label">Camera Status</label>
          <select value={cameraStatus} onChange={(e) => setCameraStatus(e.target.value)}>
            <option>All Cameras</option>
            <option>Online</option>
            <option>Offline</option>
          </select>

          <label className="field-label">Traffic Density</label>
          <select value={trafficDensity} onChange={(e) => setTrafficDensity(e.target.value)}>
            <option>All</option>
            <option>Low</option>
            <option>Medium</option>
            <option>High</option>
          </select>

          <label className="field-label">Map Layers</label>
          <label className="layer-toggle">
            <input type="checkbox" checked={showLiveHeat} onChange={(e) => setShowLiveHeat(e.target.checked)} />
            Live traffic heatmap
          </label>
          <label className="layer-toggle">
            <input type="checkbox" checked={showRoads} onChange={(e) => setShowRoads(e.target.checked)} />
            Live road colours
          </label>
          <label className="layer-toggle">
            <input type="checkbox" checked={showCameraHeat} onChange={(e) => setShowCameraHeat(e.target.checked)} />
            Camera detections
          </label>
        </aside>
      </main>

      <TrendChart windowMinutes={windowMinutes} />

      {/* ---------------- Bottleneck Panel ---------------- */}
      <section className="glass-card map-card" style={{ marginTop: 18 }}>
        <div className="section-heading">
          <div>
            <h2>Bottleneck Detection</h2>
            <p>Live segment transit time vs. seeded hour-of-day baseline</p>
          </div>
        </div>

        {bottlenecksQuery.isLoading && <SkeletonBlock height={80} />}
        {bottlenecksQuery.isError && (
          <ErrorState message="Could not load bottleneck analytics" onRetry={() => bottlenecksQuery.refetch()} />
        )}

        {bottlenecksQuery.data && bottlenecksQuery.data.length === 0 && (
          <StatePanel
            variant="success"
            title="No bottlenecks detected"
            message="All measured segments are running at or below their historical baseline."
          />
        )}

        {bottlenecksQuery.data && bottlenecksQuery.data.length > 0 && (
          <ul className="bottleneck-list">
            {bottlenecksQuery.data.map((b) => (
              <li key={b.segment} className="bottleneck-row">
                <span className="segment mono">{b.segment}</span>
                <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                  {b.current_sec}s vs {b.expected_sec}s expected
                </span>
                <span className="ratio">{(b.current_sec / b.expected_sec).toFixed(1)}×</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <DelhiReferencePanel />
      <DelhiFleetTrendPanel />

      <footer className="app-footer">Data refreshes automatically every 15–30s</footer>
    </div>
  );
}
