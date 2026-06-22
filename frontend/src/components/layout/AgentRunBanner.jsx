import { useState, useEffect, useCallback } from 'react';
import { Play, Loader2, CheckCircle, AlertCircle, RefreshCw } from 'lucide-react';
import { api } from '../../api/client';

const STATUS_COPY = {
  idle: { tone: 'muted', text: 'Not run yet' },
  pending: { tone: 'warn', text: 'Ready to run' },
  stale: { tone: 'warn', text: 'Portfolio changed — re-run recommended' },
  running: { tone: 'active', text: 'Running…' },
  completed: { tone: 'ok', text: 'Up to date' },
  failed: { tone: 'error', text: 'Failed' },
};

export function useAgentStatus(pollWhileRunning = true) {
  const [agents, setAgents] = useState(null);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    try {
      const data = await api.getAgentsStatus();
      setAgents(data);
    } catch {
      setAgents(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
    if (!pollWhileRunning) return;
    const interval = setInterval(() => {
      refetch();
    }, 3000);
    return () => clearInterval(interval);
  }, [refetch, pollWhileRunning]);

  const anyRunning =
    agents?.intelligence?.status === 'running' ||
    agents?.rationalization?.status === 'running' ||
    agents?.discovery?.status === 'extracting';

  return { agents, loading, refetch, anyRunning };
}

export default function AgentRunBanner({ agentId, onComplete }) {
  const { agents, loading, refetch } = useAgentStatus(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);

  const agent = agents?.[agentId];
  const status = agent?.status || 'idle';
  const copy = STATUS_COPY[status] || STATUS_COPY.idle;
  const isRunning = status === 'running' || starting;
  const needsRun = ['idle', 'pending', 'stale', 'failed'].includes(status);

  useEffect(() => {
    if (status === 'completed' && onComplete) onComplete();
  }, [status, onComplete]);

  const handleRun = async () => {
    setStarting(true);
    setError(null);
    try {
      if (agentId === 'intelligence') {
        await api.runIntelligence();
      } else if (agentId === 'rationalization') {
        await api.runRationalization();
      }
      await refetch();
    } catch (e) {
      setError(e.message);
    } finally {
      setStarting(false);
    }
  };

  if (agentId === 'discovery' || loading || !agent) return null;

  return (
    <div className={`agent-run-banner tone-${copy.tone}`}>
      <div className="agent-run-banner-text">
        {isRunning ? (
          <Loader2 size={16} className="spin" />
        ) : status === 'completed' ? (
          <CheckCircle size={16} />
        ) : status === 'failed' ? (
          <AlertCircle size={16} />
        ) : (
          <RefreshCw size={16} />
        )}
        <div>
          <strong>{agent.label}</strong>
          <span>{copy.text}</span>
          {agentId === 'intelligence' && agent.kpi_cluster_count != null && status === 'completed' && (
            <span className="agent-run-detail"> · {agent.kpi_cluster_count} KPI clusters</span>
          )}
          {agentId === 'rationalization' && agent.recommendation_count != null && status === 'completed' && (
            <span className="agent-run-detail"> · {agent.recommendation_count} recommendations</span>
          )}
          {error && <span className="agent-run-error">{error}</span>}
        </div>
      </div>
      {needsRun && !isRunning && (
        <button type="button" className="btn btn-primary btn-sm" onClick={handleRun}>
          <Play size={14} />
          Run {agentId === 'intelligence' ? 'Intelligence' : 'Rationalization'}
        </button>
      )}
    </div>
  );
}
