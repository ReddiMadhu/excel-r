import { NavLink, useLocation } from 'react-router-dom';
import { getAgent } from '../config/agents';
import AgentRunBanner from '../components/layout/AgentRunBanner';

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
  const showRunBanner = agentId === 'intelligence' || agentId === 'rationalization';

  return (
    <div className="agent-workspace">
      {showRunBanner && <AgentRunBanner agentId={agentId} />}
      {showTabs && (
        <div className="workspace-tabs">
          {agent.tabs.map(tab => (
            <NavLink
              key={tab.id}
              to={tab.path}
              end
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
