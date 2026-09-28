import './App.css';
import { BrowserRouter, Routes, Route, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import NavBar from './components/NavBar';
import SystemStatusStrip from './components/SystemStatusStrip';
import ToastContainer from './components/ToastContainer';
import Landing from './screens/Landing';
import Dashboard from './screens/Dashboard';
import Trajectory from './screens/Trajectory';
import Alerts from './screens/Alerts';
import MLDemo from './screens/MLDemo';
import { AlertSocketProvider, useAlertSocketContext } from './api/AlertSocketContext';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

// Layout for every screen except the landing page — this is the only place NavBar renders.
function AppShell() {
  const { connectionStatus, liveAlerts } = useAlertSocketContext();
  const latestAlertKey = liveAlerts[0] ? `${liveAlerts[0].id}-${liveAlerts[0].receivedAt}` : null;

  return (
    <div className="app-shell">
      <div className="app-bg-texture" aria-hidden="true" />
      <NavBar live={connectionStatus === 'connected'} alertPulseKey={latestAlertKey} />
      <SystemStatusStrip />
      <ToastContainer />
      <div className="app-content">
        <Outlet />
      </div>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AlertSocketProvider>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route element={<AppShell />}>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/trajectory" element={<Trajectory />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/test" element={<MLDemo />} />
            </Route>
          </Routes>
        </AlertSocketProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
