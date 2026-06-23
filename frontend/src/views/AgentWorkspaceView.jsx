import { NavLink, useLocation } from 'react-router-dom';
import { getAgent } from '../config/agents';

export default function AgentWorkspaceView({ agentId }) {
  const agent = getAgent(agentId);
  const { pathname } = useLocation();

  if (!agent) return null;

  const activeTab =
    agent.tabs.find(tab => pathname === tab.path) ||
    agent.tabs.find(tab => pathname.startsWith(tab.path + '/')) ||
    agent.tabs[0];

  const ActiveComponent = activeTab.Component;
  const showTabs = agent.tabs.length > 1;

  return (
    <div className="agent-workspace">
      {showTabs && (
        <div className="workspace-tabs">
          {agent.tabs.map(tab => (
            <NavLink
              key={tab.id}
              to={tab.path}
              end={tab.path === agent.path}
              className={({ isActive }) => `workspace-tab ${isActive ? 'active' : ''}`}
            >
              {tab.label}
            </NavLink>
          ))}
        </div>
      )}
      <div className="workspace-content">
        <ActiveComponent />
      </div>
    </div>
  );
}
