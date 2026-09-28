import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from './client';

// -------------------------
// Dashboard (Screen 1)
// -------------------------
export function useCameras() {
  return useQuery({
    queryKey: ['cameras'],
    queryFn: () => api.get('/api/v1/cameras'),
    refetchInterval: 15000,
  });
}

export function useSummary() {
  return useQuery({
    queryKey: ['summary'],
    queryFn: () => api.get('/api/v1/analytics/summary'),
    refetchInterval: 15000,
  });
}

export function useDensity(windowMinutes) {
  return useQuery({
    queryKey: ['density', windowMinutes],
    queryFn: () => api.get(`/api/v1/analytics/density?window_minutes=${windowMinutes}`),
    refetchInterval: 15000,
  });
}

export function useOdMatrix() {
  return useQuery({
    queryKey: ['od-matrix'],
    queryFn: () => api.get('/api/v1/analytics/od-matrix'),
    refetchInterval: 30000,
  });
}

export function useBottlenecks() {
  return useQuery({
    queryKey: ['bottlenecks'],
    queryFn: () => api.get('/api/v1/analytics/bottlenecks'),
    refetchInterval: 30000,
  });
}

export function useHeatmap() {
  return useQuery({
    queryKey: ['heatmap'],
    queryFn: () => api.get('/api/v1/analytics/heatmap'),
    refetchInterval: 30000,
  });
}

// City-wide live road congestion (backend caches ~15 min to respect the feed's daily quota, so polling
// every couple of minutes is cheap). Separate from useHeatmap, which is our own camera detections.
export function useLiveTraffic() {
  return useQuery({
    queryKey: ['live-traffic'],
    queryFn: () => api.get('/api/v1/analytics/live-traffic'),
    refetchInterval: 120000,
  });
}

// Live points averaged over the selected Time Range from the recorded snapshots (falls back to the
// current reading until history accumulates). keepPreviousData avoids a blank map while switching ranges.
export function useLiveTrafficWindow(minutes) {
  return useQuery({
    queryKey: ['live-traffic-window', minutes],
    queryFn: () => api.get(`/api/v1/analytics/live-traffic/window?minutes=${minutes}`),
    refetchInterval: 120000,
    placeholderData: keepPreviousData,
  });
}

// Recorded city-wide snapshots of the live feed (one every ~20 min), for the trend chart.
export function useLiveTrafficHistory(hours) {
  return useQuery({
    queryKey: ['live-traffic-history', hours],
    queryFn: () => api.get(`/api/v1/analytics/live-traffic/history?hours=${hours}`),
    refetchInterval: 120000,
  });
}

export function useTimeseries(windowMinutes = 120, bucketMinutes = 10) {
  return useQuery({
    queryKey: ['timeseries', windowMinutes, bucketMinutes],
    queryFn: () =>
      api.get(`/api/v1/analytics/timeseries?window_minutes=${windowMinutes}&bucket_minutes=${bucketMinutes}`),
    refetchInterval: 30000,
  });
}

export function useCameraRecentReads(cameraId) {
  return useQuery({
    queryKey: ['camera-recent-reads', cameraId],
    queryFn: () => api.get(`/api/v1/cameras/${encodeURIComponent(cameraId)}/recent-reads?limit=6`),
    enabled: !!cameraId,
  });
}

// Static external reference snapshot (Economic Survey of Delhi) — not live-polled,
// since it only changes when a new annual survey is published.
export function useDelhiVehicleStats() {
  return useQuery({
    queryKey: ['delhi-vehicle-stats'],
    queryFn: () => api.get('/api/v1/external/delhi-vehicle-stats'),
    staleTime: Infinity,
  });
}

// Separate dataset/source from useDelhiVehicleStats — deliberately not merged
// (see the backend's services/external_reference.py docstring for why).
export function useDelhiVehicleFleetTrend() {
  return useQuery({
    queryKey: ['delhi-vehicle-fleet-trend'],
    queryFn: () => api.get('/api/v1/external/delhi-vehicle-fleet-trend'),
    staleTime: Infinity,
  });
}

// Lightweight, frequently-polled DB-backed endpoint used purely as a liveness signal
// for the system-status strip (also doubles as "last sync" time).
export function useHealthCheck() {
  return useQuery({
    queryKey: ['health-check'],
    queryFn: () => api.get('/api/v1/cameras'),
    refetchInterval: 15000,
    retry: 1,
  });
}

// -------------------------
// Trajectory (Screen 2)
// -------------------------
export function useTrajectory(plate) {
  return useQuery({
    queryKey: ['trajectory', plate],
    queryFn: () => api.get(`/api/v1/trajectory/${encodeURIComponent(plate)}`),
    enabled: !!plate,
    retry: false,
  });
}

// -------------------------
// Alerts & Blacklist (Screen 3)
// -------------------------
export function useAlerts(unacknowledgedOnly) {
  return useQuery({
    queryKey: ['alerts', unacknowledgedOnly],
    queryFn: () => api.get(`/api/v1/alerts?limit=50&unacknowledged_only=${unacknowledgedOnly}`),
    refetchInterval: 20000,
  });
}

export function useAlertAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }) => api.post(`/api/v1/alerts/${id}/${action}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  });
}

export function useBlacklist() {
  return useQuery({
    queryKey: ['blacklist'],
    queryFn: () => api.get('/api/v1/blacklist'),
  });
}

export function useAddBlacklist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entry) => api.post('/api/v1/blacklist', entry),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['blacklist'] }),
  });
}

export function useRemoveBlacklist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (plate) => api.del(`/api/v1/blacklist/${encodeURIComponent(plate)}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['blacklist'] }),
  });
}
