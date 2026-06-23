import { useState, useCallback } from 'react';
import { NavLink } from 'react-router-dom';
import { Upload, FileSpreadsheet } from 'lucide-react';
import AgentSection from './AgentSection';
import { useSidebarMetrics } from '../../hooks/useSidebarMetrics';
import { useAgentStatus } from './AgentRunBanner';
import { agents } from '../../config/agents';
import { api } from '../../api/client';

export default function Sidebar() {
  const { metrics, loading, refetch: refetchMetrics } = useSidebarMetrics();
  const { agents: agentStatuses, refetch: refetchAgentStatus } = useAgentStatus(true);
  const [runningAgentId, setRunningAgentId] = useState(null);

  const handleRunAgent = useCallback(async (agentId) => {
    setRunningAgentId(agentId);
    try {
      if (agentId === 'intelligence') {
        await api.runIntelligence();
      } else if (agentId === 'rationalization') {
        await api.runRationalization();
      }
      await refetchAgentStatus();
    } finally {
      setRunningAgentId(null);
    }
  }, [refetchAgentStatus]);

  const handleAgentComplete = useCallback(() => {
    refetchMetrics();
    refetchAgentStatus();
  }, [refetchMetrics, refetchAgentStatus]);

  return (
    <aside className="app-sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo">
          <FileSpreadsheet />
        </div>
        <div className="sidebar-brand-text">
          <span className="brand-subtitle">BI Governance</span>
          <span className="brand-title">Excel Ration.</span>
        </div>
      </div>
      <nav className="sidebar-nav">
        <NavLink
          to="/upload"
          className={({ isActive }) => `nav-link nav-link-upload ${isActive ? 'active' : ''}`}
        >
          <Upload />
          Upload
        </NavLink>

        <div className="agent-sections">
          {agents.map(agent => (
            <AgentSection
              key={agent.id}
              agent={agent}
              metrics={metrics}
              loading={loading}
              agentStatus={agentStatuses?.[agent.id]}
              runningAgentId={runningAgentId}
              onRunAgent={handleRunAgent}
              onAgentComplete={handleAgentComplete}
            />
          ))}
        </div>
      </nav>
    </aside>
  );
}
