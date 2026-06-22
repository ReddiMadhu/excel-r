import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Sun, Moon } from 'lucide-react';
import Sidebar from './components/layout/Sidebar';
import UploadView from './views/UploadView';
import WorkbookDetailView from './views/WorkbookDetailView';
import AgentWorkspaceView from './views/AgentWorkspaceView';
import { api } from './api/client';

function ServerStatus() {
  const [status, setStatus] = useState({ ok: false, label: 'Checking...' });

  useEffect(() => {
    let cancelled = false;
    api.getHealth()
      .then(() => {
        if (!cancelled) setStatus({ ok: true, label: 'Server Connected' });
      })
      .catch(() => {
        if (!cancelled) setStatus({ ok: false, label: 'Server Offline' });
      });
    return () => { cancelled = true; };
  }, []);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        width: 8, height: 8, borderRadius: '50%',
        background: status.ok ? 'var(--accent-emerald)' : 'var(--accent-rose)',
        boxShadow: status.ok ? '0 0 8px var(--accent-emerald)' : '0 0 8px var(--accent-rose)',
      }} />
      <span className="text-muted" style={{ fontSize: '0.8rem' }}>{status.label}</span>
    </div>
  );
}

export default function App() {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('theme') || 'light';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'light' ? 'dark' : 'light');
  };

  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar />
        <main className="app-main">
          <header className="app-header">
            <ServerStatus />
            <button
              onClick={toggleTheme}
              className="btn btn-ghost"
              style={{
                padding: 0,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 36,
                height: 36,
                border: '1px solid var(--glass-border)',
                background: 'var(--bg-surface)',
                cursor: 'pointer',
                color: 'var(--text-primary)'
              }}
              title={`Switch to ${theme === 'light' ? 'Dark' : 'Light'} Mode`}
            >
              {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
            </button>
          </header>
          <div className="app-content">
            <Routes>
              <Route path="/" element={<Navigate to="/discovery" replace />} />
              <Route path="/upload" element={<UploadView />} />
              <Route path="/discovery" element={<AgentWorkspaceView agentId="discovery" />} />
              <Route path="/intelligence" element={<Navigate to="/intelligence/kpi" replace />} />
              <Route path="/intelligence/kpi" element={<AgentWorkspaceView agentId="intelligence" />} />
              <Route path="/intelligence/landscape" element={<AgentWorkspaceView agentId="intelligence" />} />
              <Route path="/rationalization" element={<AgentWorkspaceView agentId="rationalization" />} />
              <Route path="/rationalization/risks" element={<AgentWorkspaceView agentId="rationalization" />} />
              <Route path="/workbooks/:id" element={<WorkbookDetailView />} />
              {/* Legacy route redirects */}
              <Route path="/kpi-clusters" element={<Navigate to="/intelligence/kpi" replace />} />
              <Route path="/landscape" element={<Navigate to="/intelligence/landscape" replace />} />
              <Route path="/risks" element={<Navigate to="/rationalization/risks" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </BrowserRouter>
  );
}
