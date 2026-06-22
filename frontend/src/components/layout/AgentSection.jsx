import { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';

function isRouteActive(pathname, routes) {
  return routes.some(route => {
    if (route === '/discovery') {
      return pathname === '/discovery' || pathname.startsWith('/workbooks');
    }
    return pathname === route || pathname.startsWith(route + '/');
  });
}

function formatMetric(value, loading) {
  if (loading || value === null) return '—';
  return value;
}

export default function AgentSection({ agent, metrics, loading }) {
  const { pathname } = useLocation();
  const storageKey = `sidebar-agent-${agent.id}`;
  const routeActive = isRouteActive(pathname, agent.routes);

  const [expanded, setExpanded] = useState(() => {
    if (routeActive) return true;
    const stored = localStorage.getItem(storageKey);
    return stored === 'true';
  });

  useEffect(() => {
    if (routeActive) setExpanded(true);
  }, [routeActive]);

  useEffect(() => {
    localStorage.setItem(storageKey, String(expanded));
  }, [expanded, storageKey]);

  const Icon = agent.icon;
  const metricItems = agent.metrics(metrics);

  return (
    <div className="agent-section">
      <div className={`agent-header ${routeActive ? 'active' : ''}`}>
        <NavLink to={agent.path} className="agent-header-link">
          <Icon className="agent-header-icon" />
          <span className="agent-header-label">{agent.label}</span>
        </NavLink>
        <button
          type="button"
          className="agent-chevron-btn"
          onClick={() => setExpanded(prev => !prev)}
          aria-expanded={expanded}
          aria-label={expanded ? 'Collapse metrics' : 'Expand metrics'}
        >
          <ChevronDown className={`agent-chevron ${expanded ? 'expanded' : ''}`} />
        </button>
      </div>

      <div className={`agent-panel ${expanded ? 'expanded' : ''}`}>
        <p className="agent-description" title={agent.description}>
          {agent.description}
        </p>

        <div className="agent-metrics">
          {metricItems.map(({ label, value }) => (
            <div key={label} className="agent-metric">
              <span className="metric-label">{label}</span>
              <span className={`metric-value ${value > 0 ? 'has-value' : ''}`}>
                {formatMetric(value, loading)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
