import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { APP_NAME, APP_TAGLINE } from '../constants';

const TABS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/trajectory', label: 'Trajectory' },
  { to: '/alerts', label: 'Alerts' },
  { to: '/test', label: 'Test Model' },
];

export default function NavBar({ live, alertPulseKey }) {
  const [pulsing, setPulsing] = useState(false);

  useEffect(() => {
    if (alertPulseKey == null) return undefined;
    setPulsing(true);
    const timer = setTimeout(() => setPulsing(false), 900);
    return () => clearTimeout(timer);
  }, [alertPulseKey]);

  return (
    <nav className="top-nav">
      <div className="brand">
        <span className="brand-mark">
          <span className="brand-scan" />
        </span>
        <span className="brand-text">
          {APP_NAME} <span>// {APP_TAGLINE}</span>
        </span>
      </div>

      <div className="nav-tabs">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
          >
            {tab.label}
          </NavLink>
        ))}
      </div>

      <div className={`live-status${pulsing ? ' pulsing' : ''}`}>
        <span className={`live-dot${live ? '' : ' dim'}`} />
        {live ? 'LIVE' : 'OFFLINE'}
      </div>
    </nav>
  );
}
