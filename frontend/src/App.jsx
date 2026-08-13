import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import Sidebar from './components/layout/Sidebar';
import UploadView from './views/UploadView';
import WorkbookDetailView from './views/WorkbookDetailView';
import AgentWorkspaceView from './views/AgentWorkspaceView';
import RationalizationDetailView from './views/RationalizationDetailView';
import OverlapAnalysisView from './views/OverlapAnalysisView';
import ClusterDetailView from './views/ClusterDetailView';

export default function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    return localStorage.getItem('sidebar-collapsed') === 'true';
  });

  const toggleSidebar = () => {
    setSidebarCollapsed(prev => {
      const next = !prev;
      localStorage.setItem('sidebar-collapsed', String(next));
      return next;
    });
  };

  return (
    <ThemeProvider>
      <BrowserRouter>
        <div className={`app-layout ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
          <Sidebar collapsed={sidebarCollapsed} onToggle={toggleSidebar} />
          <main className="app-main">
            <div className="app-content">
              <Routes>
                <Route path="/" element={<Navigate to="/discovery" replace />} />
                <Route path="/upload" element={<UploadView />} />
                <Route path="/discovery" element={<AgentWorkspaceView agentId="discovery" />} />
                <Route path="/intelligence" element={<AgentWorkspaceView agentId="intelligence" />} />
                <Route path="/intelligence/landscape" element={<AgentWorkspaceView agentId="intelligence" />} />
                <Route path="/intelligence/metrics" element={<Navigate to="/intelligence" replace />} />
                <Route path="/intelligence/tables" element={<Navigate to="/intelligence" replace />} />
                <Route path="/rationalization" element={<AgentWorkspaceView agentId="rationalization" />} />
                <Route path="/rationalization/review/:type/:id" element={<RationalizationDetailView />} />
                <Route path="/excel-review" element={<AgentWorkspaceView agentId="discovery" />} />
                <Route path="/overlap-analysis" element={<OverlapAnalysisView />} />
                <Route path="/overlap-analysis/cluster/:clusterId" element={<ClusterDetailView />} />
                <Route path="/workbooks/:id" element={<WorkbookDetailView />} />
                <Route path="/kpi-clusters" element={<Navigate to="/intelligence" replace />} />
                <Route path="/intelligence/kpi" element={<Navigate to="/intelligence" replace />} />
                <Route path="/landscape" element={<Navigate to="/intelligence/landscape" replace />} />
              </Routes>
            </div>
          </main>
        </div>
      </BrowserRouter>
    </ThemeProvider>
  );
}

