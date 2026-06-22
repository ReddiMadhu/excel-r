const BASE_URL = 'http://localhost:8000';

async function fetchJson(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Accept': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  // Health
  getHealth: () => fetchJson('/api/health'),

  // Scans
  createScan: async (files) => {
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));
    const res = await fetch(`${BASE_URL}/api/scans`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    return res.json();
  },
  getScanProgress: (scanId) => fetchJson(`/api/scans/${scanId}`),

  // Workbooks
  getWorkbooks: () => fetchJson('/api/workbooks'),
  getWorkbook: (id) => fetchJson(`/api/workbooks/${id}`),
  deleteWorkbook: (id) => fetchJson(`/api/workbooks/${id}`, { method: 'DELETE' }),

  // Dashboards
  getDashboards: () => fetchJson('/api/dashboards'),
  getDashboard: (id) => fetchJson(`/api/dashboards/${id}`),

  // Data
  getCalculatedFields: () => fetchJson('/api/calculated-fields'),
  getDatasources: () => fetchJson('/api/datasources'),
  getKpiClusters: () => fetchJson('/api/kpi-clusters'),

  // Governance
  getRecommendations: () => fetchJson('/api/governance/recommendations'),
  getReviewQueue: () => fetchJson('/api/governance/review'),
  getRisks: () => fetchJson('/api/governance/risks'),
  getPairwiseMatrix: (workbookIds) =>
    fetchJson(`/api/governance/pairwise${workbookIds ? '?workbook_ids=' + workbookIds : ''}`),

  // Agents (decentralized pipelines)
  getAgentsStatus: () => fetchJson('/api/agents/status'),
  runIntelligence: () => fetchJson('/api/agents/intelligence/run', { method: 'POST' }),
  runRationalization: () => fetchJson('/api/agents/rationalization/run', { method: 'POST' }),

  // KPI Graph
  getKpiGraphData: (dashboards) => 
    fetchJson(`/api/kpi-graph/data${dashboards ? '?dashboards=' + encodeURIComponent(dashboards) : ''}`),
  getKpiGraphSummary: (dashboards, focusType = 'all') => 
    fetchJson(`/api/kpi-graph/summary?focus_type=${focusType}${dashboards ? '&dashboards=' + encodeURIComponent(dashboards) : ''}`),
};
