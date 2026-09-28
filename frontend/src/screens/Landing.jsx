import { Fragment } from 'react';
import { Link } from 'react-router-dom';
import { APP_NAME } from '../constants';
import { useSummary } from '../api/hooks';
import HeroGraphic from '../components/HeroGraphic';

const SUBHEADLINE = 'See It. Track It. Flag It.';
const TAGLINE =
  'A real-time ANPR traffic intelligence platform that unifies live density mapping, cross-camera vehicle trajectory reconstruction, and automated blacklist alerting into a single, continuously updating view of the city.';

const HERO_CAPABILITIES = [
  { to: '/dashboard', label: 'Live Density Heatmap' },
  { to: '/dashboard', label: 'Origin–Destination Flows' },
  { to: '/dashboard', label: 'Bottleneck Detection' },
  { to: '/alerts', label: 'Blacklist Alerts' },
];

const FEATURE_CARDS = [
  {
    to: '/dashboard',
    label: 'Dashboard',
    description: 'Live density, heatmaps, and origin-destination flow across the city.',
    icon: 'dashboard',
  },
  {
    to: '/trajectory',
    label: 'Trajectory',
    description: "Search and replay a vehicle's route across cameras.",
    icon: 'trajectory',
  },
  {
    to: '/alerts',
    label: 'Alerts',
    description: 'Real-time blacklist hits and anomaly alerts.',
    icon: 'alerts',
  },
  {
    to: '/dashboard',
    label: 'Bottleneck Detection',
    description: 'Live segment transit times checked against seeded historical baselines to catch slowdowns as they happen.',
    icon: 'bottleneck',
  },
  {
    to: '/trajectory',
    label: 'Fuzzy Plate Matching',
    description: 'OCR-confusion-aware matching reconstructs a route even from partial or misread plates.',
    icon: 'fuzzy',
  },
  {
    to: '/alerts',
    label: 'Blacklist Manager',
    description: 'Add or remove flagged plates and see every hit the moment it is read.',
    icon: 'blacklist',
  },
  {
    to: '/alerts',
    label: 'Live Alert Feed',
    description: 'WebSocket-pushed alerts the instant a blacklist or behavioral rule fires.',
    icon: 'live',
  },
  {
    to: '/alerts',
    label: 'CSV Export',
    description: "Export the current alert list or a trajectory's waypoints for offline review.",
    icon: 'export',
  },
];

const PIPELINE_STEPS = [
  { label: 'Camera Read', icon: 'camera' },
  { label: 'Track Dedup', icon: 'dedup' },
  { label: 'Alert Engine', icon: 'alerts' },
  { label: 'Live Broadcast', icon: 'live' },
];

function DashboardIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <rect x="3" y="3" width="18" height="18" rx="2.5" fill="none" stroke="#39ff14" strokeOpacity="0.3" />
      <line x1="3" y1="11" x2="21" y2="11" stroke="#39ff14" strokeOpacity="0.2" />
      <line x1="11" y1="3" x2="11" y2="21" stroke="#39ff14" strokeOpacity="0.2" />
      <circle cx="11" cy="11" r="1.8" fill="#39ff14" />
      <circle cx="16.5" cy="16.5" r="1.5" fill="#39ff14" opacity="0.6" />
    </svg>
  );
}

function TrajectoryIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M4 20 L9 11 L14 16 L20 5" fill="none" stroke="#39ff14" strokeOpacity="0.45" strokeWidth="1.5" strokeDasharray="2.5 2.5" />
      <circle cx="4" cy="20" r="1.6" fill="#39ff14" opacity="0.5" />
      <circle cx="9" cy="11" r="1.6" fill="#39ff14" opacity="0.75" />
      <circle cx="20" cy="5" r="2" fill="#39ff14" />
    </svg>
  );
}

function AlertsIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M12 3 L21 20 L3 20 Z" fill="none" stroke="#39ff14" strokeOpacity="0.45" strokeWidth="1.5" strokeLinejoin="round" />
      <line x1="12" y1="9.5" x2="12" y2="14.5" stroke="#39ff14" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="17" r="1.1" fill="#39ff14" />
    </svg>
  );
}

function BottleneckIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="8.5" fill="none" stroke="#39ff14" strokeOpacity="0.3" strokeWidth="1.5" />
      <line x1="12" y1="12" x2="12" y2="6.5" stroke="#39ff14" strokeWidth="1.6" strokeLinecap="round" />
      <line x1="12" y1="12" x2="16" y2="14" stroke="#39ff14" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="12" cy="12" r="1.2" fill="#39ff14" />
    </svg>
  );
}

function FuzzyIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <circle cx="10" cy="10" r="6.5" fill="none" stroke="#39ff14" strokeOpacity="0.4" strokeWidth="1.5" />
      <line x1="14.7" y1="14.7" x2="21" y2="21" stroke="#39ff14" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="8" cy="8" r="0.9" fill="#39ff14" opacity="0.8" />
      <circle cx="11" cy="12" r="0.9" fill="#39ff14" opacity="0.5" />
      <circle cx="7" cy="12" r="0.9" fill="#39ff14" opacity="0.3" />
    </svg>
  );
}

function BlacklistIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path d="M12 3 L20 6 V12 C20 17 16.5 19.8 12 21 C7.5 19.8 4 17 4 12 V6 Z" fill="none" stroke="#39ff14" strokeOpacity="0.4" strokeWidth="1.5" strokeLinejoin="round" />
      <line x1="8" y1="11.5" x2="16" y2="11.5" stroke="#39ff14" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function LiveIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="1.6" fill="#39ff14" />
      <path d="M8.5 15.5 a5 5 0 0 1 0 -7" fill="none" stroke="#39ff14" strokeOpacity="0.5" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M15.5 15.5 a5 5 0 0 0 0 -7" fill="none" stroke="#39ff14" strokeOpacity="0.5" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M5.5 18.5 a9 9 0 0 1 0 -13" fill="none" stroke="#39ff14" strokeOpacity="0.25" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M18.5 18.5 a9 9 0 0 0 0 -13" fill="none" stroke="#39ff14" strokeOpacity="0.25" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ExportIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <line x1="12" y1="3" x2="12" y2="14" stroke="#39ff14" strokeOpacity="0.55" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M8 10 L12 14 L16 10" fill="none" stroke="#39ff14" strokeOpacity="0.55" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 18 H20" stroke="#39ff14" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function CameraIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <rect x="3" y="7" width="18" height="12" rx="2" fill="none" stroke="#39ff14" strokeOpacity="0.45" strokeWidth="1.5" />
      <path d="M8 7 L9.5 4.5 H14.5 L16 7" fill="none" stroke="#39ff14" strokeOpacity="0.45" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx="12" cy="13" r="3.2" fill="none" stroke="#39ff14" strokeWidth="1.6" />
      <circle cx="12" cy="13" r="1" fill="#39ff14" />
    </svg>
  );
}

function DedupIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <circle cx="9.5" cy="12" r="6" fill="none" stroke="#39ff14" strokeOpacity="0.35" strokeWidth="1.5" />
      <circle cx="14.5" cy="12" r="6" fill="none" stroke="#39ff14" strokeOpacity="0.7" strokeWidth="1.5" />
    </svg>
  );
}

const ICONS = {
  dashboard: DashboardIcon,
  trajectory: TrajectoryIcon,
  alerts: AlertsIcon,
  bottleneck: BottleneckIcon,
  fuzzy: FuzzyIcon,
  blacklist: BlacklistIcon,
  live: LiveIcon,
  export: ExportIcon,
  camera: CameraIcon,
  dedup: DedupIcon,
};

function IconCircle({ type }) {
  const Icon = ICONS[type];
  return (
    <span className="feature-icon-circle">
      <Icon />
    </span>
  );
}

export default function Landing() {
  const summaryQuery = useSummary();
  const s = summaryQuery.data;

  return (
    <div className="landing-page">
      <nav className="landing-topbar">
        <div className="brand">
          <span className="brand-mark">
            <span className="brand-scan" />
          </span>
          <span className="brand-text">{APP_NAME}</span>
        </div>
        <Link to="/dashboard" className="btn-pill btn-pill-sm">
          Enter Dashboard
        </Link>
      </nav>

      <section className="landing-hero-section">
        <div className="landing-bg-texture" aria-hidden="true" />

        <div className="landing-content">
          <div className="landing-text">
            <span className="hero-pill-badge">
              <span className="capability-dot" /> Live City-Wide ANPR Monitoring
            </span>
            <h1 className="landing-title">{APP_NAME}</h1>
            <p className="landing-subheadline">{SUBHEADLINE}</p>
            <p className="landing-tagline">{TAGLINE}</p>

            <div className="hero-cta-row">
              <Link to="/dashboard" className="btn-pill">
                Enter the Dashboard →
              </Link>
              <Link to="/trajectory" className="btn-pill btn-pill-outline">
                ⌕ Search a Plate
              </Link>
              <Link to="/test" className="btn-pill btn-pill-outline">
                ▶ Test the Model
              </Link>
            </div>

            <div className="hero-capability-row">
              {HERO_CAPABILITIES.map((c, i) => (
                <span key={c.label}>
                  <Link to={c.to} className="hero-capability-link">
                    {c.label}
                  </Link>
                  {i < HERO_CAPABILITIES.length - 1 && <span className="hero-capability-dot"> · </span>}
                </span>
              ))}
            </div>
          </div>

          <div className="hero-visual">
            <div className="landing-graphic" aria-hidden="true">
              <HeroGraphic />
            </div>

            <div className="hero-float-card hero-float-card--top-right">
              <span className="float-label">Cameras Online</span>
              <span className="float-value">{s ? `${s.cameras_online}/${s.cameras_total}` : '—'}</span>
            </div>
            <div className="hero-float-card hero-float-card--center">
              <span className="float-label">Active Alerts</span>
              <span className="float-value">{s ? String(s.active_alerts).padStart(2, '0') : '—'}</span>
            </div>
            <div className="hero-float-card hero-float-card--bottom-left">
              <span className="float-label">Avg City Speed</span>
              <span className="float-value">{s?.avg_speed_kmh != null ? `${s.avg_speed_kmh} km/h` : '—'}</span>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-section bordered-top">
        <div className="landing-section-header">
          <p className="landing-eyebrow">Platform Overview</p>
          <h2 className="landing-section-heading">A Complete City-Wide Traffic Platform</h2>
          <p className="landing-section-subtext">
            From live density mapping down to a single flagged plate, every screen is powered by the same
            real-time ANPR ingestion pipeline.
          </p>
        </div>

        <div className="feature-grid">
          {FEATURE_CARDS.map((card) => (
            <Link to={card.to} key={card.label} className="glass-card interactive feature-card">
              <IconCircle type={card.icon} />
              <h3>{card.label}</h3>
              <p>{card.description}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="landing-section bordered-top">
        <div className="landing-section-header">
          <p className="landing-eyebrow">Detection Pipeline</p>
          <h2 className="landing-section-heading">One Camera Read In. One City-Wide Alert Out.</h2>
        </div>

        <div className="pipeline-row">
          {PIPELINE_STEPS.map((step, i) => (
            <Fragment key={step.label}>
              <div className="glass-card pipeline-step">
                <IconCircle type={step.icon} />
                <span>{step.label}</span>
              </div>
              {i < PIPELINE_STEPS.length - 1 && (
                <span className="pipeline-arrow" aria-hidden="true">
                  →
                </span>
              )}
            </Fragment>
          ))}
        </div>

        <p className="pipeline-caption">
          Every raw detection is deduplicated into a vehicle track using a five-second window, checked against
          the blacklist and behavioral rules (curfew violations, route circling) in real time, and pushed over
          WebSocket to every connected screen — so an alert never waits on a manual refresh.
        </p>
      </section>

      <section className="landing-section bordered-top">
        <div className="landing-cta-band">
          <h2>Search a plate. See its whole route.</h2>
          <p>Partial plates and OCR-confused reads are supported — fuzzy matching fills the gaps.</p>
          <Link to="/trajectory" className="btn-pill">
            Search Now →
          </Link>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="brand">
          <span className="brand-mark" style={{ width: 8, height: 8 }} />
          {APP_NAME}
        </div>
        <span>A FastAPI + PostgreSQL ANPR pipeline, console built with React + Vite.</span>
      </footer>
    </div>
  );
}
