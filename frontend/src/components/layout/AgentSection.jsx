import { useState, useEffect, useRef } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { ChevronDown, Play, Loader2, CheckCircle2 } from 'lucide-react';

function isRouteActive(pathname, routes) {
  return routes.some(route => {
    if (route === '/discovery') {
      return pathname === '/discovery'
        || pathname.startsWith('/discovery/')
        || pathname.startsWith('/workbooks');
    }
    return pathname === route || pathname.startsWith(route + '/');
  });
}

function formatMetric(value, loading) {
  if (loading || value === null) return '—';
  return value;
}

function shouldShowMetrics(agentId, metrics, loading, agentStatus) {
  if (loading) return false;

  const status = agentStatus?.status || metrics.agentStatus?.[agentId]?.status;

  if (agentId === 'discovery') {
    return (metrics.workbookCount || 0) > 0;
  }

  if (agentId === 'intelligence') {
    const hasRun = status === 'completed' || status === 'stale' || status === 'running';
    const hasData = (metrics.kpiClusterCount || 0) > 0;
    return hasRun || hasData;
  }

  if (agentId === 'rationalization') {
    const hasRun = status === 'completed' || status === 'stale' || status === 'running';
    const hasData =
      (metrics.keepCount || 0) > 0
      || (metrics.mergeCount || 0) > 0
      || (metrics.decommissionCount || 0) > 0
      || (metrics.reviewCount || 0) > 0;
    return hasRun || hasData;
  }

  return false;
}

function canRunAgent(agentId) {
  return agentId === 'intelligence' || agentId === 'rationalization';
}

export default function AgentSection({
  agent,
  metrics,
  loading,
  agentStatus,
  runningAgentId,
  onRunAgent,
  onAgentComplete,
}) {
  const { pathname } = useLocation();
  const storageKey = `sidebar-agent-${agent.id}`;
  const routeActive = isRouteActive(pathname, agent.routes);
  const status = agentStatus?.status || 'idle';
  const isRunning = status === 'running' || runningAgentId === agent.id;
  const showMetrics = shouldShowMetrics(agent.id, metrics, loading, agentStatus);
  const runnable = canRunAgent(agent.id);

  const [expanded, setExpanded] = useState(() => {
    if (!showMetrics) return false;
    if (routeActive) return true;
    return localStorage.getItem(storageKey) === 'true';
  });
  const prevStatus = useRef(status);

  useEffect(() => {
    if (routeActive && showMetrics) setExpanded(true);
  }, [routeActive, showMetrics]);

  useEffect(() => {
    if (prevStatus.current !== 'completed' && status === 'completed' && showMetrics) {
      setExpanded(true);
      onAgentComplete?.();
    }
    prevStatus.current = status;
  }, [status, showMetrics, onAgentComplete]);

  useEffect(() => {
    if (showMetrics) {
      localStorage.setItem(storageKey, String(expanded));
    }
  }, [expanded, storageKey, showMetrics]);

  const handleRun = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (isRunning || !runnable) return;
    await onRunAgent(agent.id);
  };

  const Icon = agent.icon;
  const metricItems = agent.metrics(metrics);

  return (
    <div className="agent-section">
      <div className={`agent-header ${routeActive ? 'active' : ''}`}>
        <NavLink to={agent.path} className="agent-header-link">
          <Icon className="agent-header-icon" />
          <span className="agent-header-label">{agent.label}</span>
        </NavLink>

        {runnable && (
          <button
            type="button"
            className={`agent-run-btn ${isRunning ? 'running' : ''} ${status === 'completed' ? 'completed' : ''}`}
            onClick={handleRun}
            disabled={isRunning}
            title={
              isRunning
                ? 'Running…'
                : status === 'completed'
                  ? 'Re-run agent'
                  : 'Run agent'
            }
            aria-label={`Run ${agent.label}`}
          >
            {isRunning ? (
              <Loader2 size={14} className="spin" />
            ) : status === 'completed' ? (
              <CheckCircle2 size={14} />
            ) : (
              <Play size={14} />
            )}
          </button>
        )}

        {showMetrics && (
          <button
            type="button"
            className="agent-chevron-btn"
            onClick={() => setExpanded(prev => !prev)}
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse metrics' : 'Expand metrics'}
          >
            <ChevronDown className={`agent-chevron ${expanded ? 'expanded' : ''}`} />
          </button>
        )}
      </div>

      {showMetrics && (
        <div className={`agent-panel ${expanded ? 'expanded' : ''}`}>
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
      )}
    </div>
  );
}
