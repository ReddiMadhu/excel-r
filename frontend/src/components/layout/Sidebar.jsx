import { NavLink } from 'react-router-dom';
import { Upload, FileSpreadsheet } from 'lucide-react';
import AgentSection from './AgentSection';
import { useSidebarMetrics } from '../../hooks/useSidebarMetrics';
import { agents } from '../../config/agents';

export default function Sidebar() {
  const { metrics, loading } = useSidebarMetrics();

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
            />
          ))}
        </div>
      </nav>
    </aside>
  );
}
