import { useMemo } from 'react';
import { ShieldAlert, AlertTriangle, Info, AlertCircle } from 'lucide-react';
import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { StatCard, Loader, EmptyState } from '../components/shared';

const COLORS = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#f43f5e', '#06b6d4'];

export default function RiskDashboardView() {
  const { data: risks, loading: rLoading } = useApi(api.getRisks);
  const { data: workbooks, loading: wLoading } = useApi(api.getWorkbooks);

  const severityCounts = useMemo(() => {
    if (!risks) return { critical: 0, warning: 0, info: 0 };
    return {
      critical: risks.filter(r => r.severity === 'critical').length,
      warning: risks.filter(r => r.severity === 'warning').length,
      info: risks.filter(r => r.severity === 'info').length,
    };
  }, [risks]);

  // Build radar data from workbook complexity scores
  const radarData = useMemo(() => {
    if (!workbooks) return [];
    return [
      { axis: 'Extraction', ...Object.fromEntries(workbooks.map(w => [w.name, w.extraction_complexity || 0])) },
      { axis: 'Structural', ...Object.fromEntries(workbooks.map(w => [w.name, w.structural_risk || 0])) },
      { axis: 'Computation', ...Object.fromEntries(workbooks.map(w => [w.name, w.computation_depth || 0])) },
    ];
  }, [workbooks]);

  if (rLoading || wLoading) return <Loader />;

  return (
    <div className="page-enter">
      <h1 style={{ marginBottom: 24 }}>Risk Dashboard</h1>

      <div className="stat-grid">
        <StatCard icon={AlertCircle} value={severityCounts.critical} label="Critical Risks" color="rose" />
        <StatCard icon={AlertTriangle} value={severityCounts.warning} label="Warnings" color="amber" />
        <StatCard icon={Info} value={severityCounts.info} label="Info" color="blue" />
      </div>

      {/* Complexity Radar */}
      {workbooks && workbooks.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <h3 style={{ marginBottom: 16 }}>Workbook Complexity Comparison</h3>
          <ResponsiveContainer width="100%" height={350}>
            <RadarChart data={radarData}>
              <PolarGrid stroke="var(--glass-border)" />
              <PolarAngleAxis dataKey="axis" tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} />
              <PolarRadiusAxis angle={30} domain={[0, 5]} tick={{ fill: 'var(--text-muted)', fontSize: 10 }} />
              {(workbooks || []).map((wb, i) => (
                <Radar
                  key={wb.id}
                  name={wb.name.length > 25 ? wb.name.slice(0, 23) + '...' : wb.name}
                  dataKey={wb.name}
                  stroke={COLORS[i % COLORS.length]}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={0.15}
                  strokeWidth={2}
                />
              ))}
              <Legend
                wrapperStyle={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}
              />
              <Tooltip
                contentStyle={{
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--glass-border)',
                  borderRadius: 8,
                  fontSize: '0.8rem',
                }}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Risk Table */}
      {risks && risks.length > 0 ? (
        <div className="card">
          <h3 style={{ marginBottom: 16 }}>Detected Risks</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Workbook</th>
                <th>Sheet</th>
                <th>Category</th>
                <th>Severity</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {risks.map(risk => (
                <tr key={risk.id}>
                  <td style={{ fontWeight: 500 }}>{risk.workbook_name}</td>
                  <td className="text-muted">{risk.dashboard_name || '—'}</td>
                  <td>
                    <span className="badge badge-blue">{risk.risk_category}</span>
                  </td>
                  <td>
                    <span className={`badge ${
                      risk.severity === 'critical' ? 'badge-decommission'
                      : risk.severity === 'warning' ? 'badge-merge'
                      : 'badge-blue'
                    }`}>{risk.severity}</span>
                  </td>
                  <td className="text-secondary" style={{ fontSize: '0.85rem' }}>{risk.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="card">
          <EmptyState
            icon={ShieldAlert}
            title="No risks detected"
            message="The analyzed workbooks don't have any structural risks."
          />
        </div>
      )}
    </div>
  );
}

