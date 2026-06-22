import { useNavigate } from 'react-router-dom';
import { FileSpreadsheet, BarChart3, Database, Tags, GitCompare } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { StatCard, Badge, ComplexityBar, Loader, EmptyState } from '../components/shared';

export default function PortfolioView() {
  const navigate = useNavigate();
  const { data: workbooks, loading: wbLoading } = useApi(api.getWorkbooks);
  const { data: recommendations } = useApi(api.getRecommendations);
  const { data: kpiClusters } = useApi(api.getKpiClusters);
  const { data: calcFields } = useApi(api.getCalculatedFields);

  if (wbLoading) return <Loader />;

  const recMap = {};
  (recommendations || []).forEach(r => { recMap[r.workbook_id] = r; });

  const totalSheets = (workbooks || []).reduce((s, w) => s + (w.sheet_count || 0), 0);
  const totalCalcFields = (calcFields || []).length;
  const multiWbClusters = (kpiClusters || []).filter(c => c.workbook_count > 1).length;

  return (
    <div className="page-enter">
      <div className="section-header">
        <h1>Portfolio Overview</h1>
        <button className="btn btn-primary" onClick={() => navigate('/upload')}>
          <FileSpreadsheet size={16} /> Upload Files
        </button>
      </div>

      <div className="stat-grid">
        <StatCard icon={FileSpreadsheet} value={(workbooks || []).length} label="Workbooks" color="blue" />
        <StatCard icon={BarChart3} value={totalSheets} label="Sheets" color="purple" />
        <StatCard icon={Database} value={totalCalcFields} label="Calculated Fields" color="emerald" />
        <StatCard icon={Tags} value={multiWbClusters} label="Shared KPI Clusters" color="amber" />
      </div>

      {(!workbooks || workbooks.length === 0) ? (
        <EmptyState
          icon={FileSpreadsheet}
          title="No workbooks yet"
          message="Upload Excel files to get started with rationalization."
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {workbooks.map(wb => {
            const rec = recMap[wb.id];
            return (
              <div
                key={wb.id}
                className="card card-clickable"
                onClick={() => navigate(`/workbooks/${wb.id}`)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                      <h3>{wb.name}</h3>
                      {rec && <Badge action={rec.action} />}
                    </div>
                    <p className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: 8 }}>
                      {wb.sheet_count} sheets &middot; {wb.calculated_field_count || 0} calc fields
                      &middot; {wb.datasource_count || 0} datasources
                      {wb.comparison_mode && (
                        <> &middot; <span className="badge badge-blue" style={{ fontSize: '0.65rem' }}>{wb.comparison_mode}</span></>
                      )}
                      {wb.extraction_quality_score != null && (
                        <> &middot; {Math.round(wb.extraction_quality_score * 100)}% quality</>
                      )}
                      {wb.has_vba_macros && <> &middot; <span style={{ color: 'var(--accent-rose)' }}>VBA</span></>}
                    </p>
                    {wb.purpose && (
                      <p className="text-muted" style={{ fontSize: '0.8rem' }}>{wb.purpose}</p>
                    )}
                    {rec && rec.action !== 'keep' && rec.merge_with_name && (
                      <p style={{ fontSize: '0.8rem', color: 'var(--accent-amber)', marginTop: 6 }}>
                        <GitCompare size={13} style={{ verticalAlign: -2 }} />{' '}
                        {rec.action === 'merge' ? 'Merge' : 'Overlap'} with "{rec.merge_with_name}"
                        {rec.kpi_overlap_score > 0 && ` (${Math.round(rec.kpi_overlap_score * 100)}% KPI overlap)`}
                      </p>
                    )}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8, minWidth: 140 }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Complexity</div>
                    <ComplexityBar value={wb.extraction_complexity} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

