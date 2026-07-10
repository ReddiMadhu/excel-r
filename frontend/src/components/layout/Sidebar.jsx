import { useState, useCallback } from 'react';
import { NavLink } from 'react-router-dom';
import { Upload, FileSpreadsheet, ChevronLeft, ChevronRight } from 'lucide-react';
import AgentSection from './AgentSection';
import { useSidebarMetrics } from '../../hooks/useSidebarMetrics';
import { useAgentStatus } from './AgentRunBanner';
import { agents } from '../../config/agents';
import { api } from '../../api/client';

export default function Sidebar({ collapsed, onToggle }) {
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
    // Notify all useApi hooks (KpiExplorerView, LandscapeView, etc.) to refetch
    window.dispatchEvent(new Event('portfolio-updated'));
  }, [refetchMetrics, refetchAgentStatus]);

  return (
    <aside className={`app-sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-brand">
        <div className="sidebar-logo">
          <FileSpreadsheet />
        </div>
        {!collapsed && (
          <div className="sidebar-brand-text">
            <span className="brand-subtitle">BI Governance</span>
            <span className="brand-title">Excel Ration<span className="brand-dot">.</span></span>
          </div>
        )}
        <button
          className="sidebar-collapse-btn"
          onClick={onToggle}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>
      <nav className="sidebar-nav">
        <NavLink
          to="/upload"
          className={({ isActive }) => `nav-link nav-link-upload ${isActive ? 'active' : ''}`}
          title={collapsed ? "Upload" : undefined}
        >
          <Upload />
          {!collapsed && <span>Upload</span>}
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
              collapsed={collapsed}
            />
          ))}
        </div>
      </nav>
    </aside>
  );
}
