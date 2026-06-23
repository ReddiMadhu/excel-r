import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import Sidebar from './components/layout/Sidebar';
import UploadView from './views/UploadView';
import WorkbookDetailView from './views/WorkbookDetailView';
import AgentWorkspaceView from './views/AgentWorkspaceView';

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <div className="app-layout">
          <Sidebar />
          <main className="app-main">
            <div className="app-content">
              <Routes>
                <Route path="/" element={<Navigate to="/discovery" replace />} />
                <Route path="/upload" element={<UploadView />} />
                <Route path="/discovery" element={<AgentWorkspaceView agentId="discovery" />} />
                <Route path="/intelligence" element={<AgentWorkspaceView agentId="intelligence" />} />
                <Route path="/intelligence/metrics" element={<AgentWorkspaceView agentId="intelligence" />} />
                <Route path="/intelligence/tables" element={<Navigate to="/intelligence" replace />} />
                <Route path="/rationalization" element={<AgentWorkspaceView agentId="rationalization" />} />
                <Route path="/workbooks/:id" element={<WorkbookDetailView />} />
                <Route path="/kpi-clusters" element={<Navigate to="/intelligence/metrics" replace />} />
                <Route path="/intelligence/kpi" element={<Navigate to="/intelligence/metrics" replace />} />
                <Route path="/landscape" element={<Navigate to="/intelligence" replace />} />
                <Route path="/intelligence/landscape" element={<Navigate to="/intelligence" replace />} />
              </Routes>
            </div>
          </main>
        </div>
      </BrowserRouter>
    </ThemeProvider>
  );
}
