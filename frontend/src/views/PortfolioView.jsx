import { useNavigate } from 'react-router-dom';
import { FileSpreadsheet, BarChart3, Database, Tags, GitCompare } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { StatCard, Badge, Loader, EmptyState } from '../components/shared';

function effectiveRecAction(wbId, rec, allRecs) {
  if (!rec) return null;
  const retainedBy = (allRecs || []).find(
    r => (r.action === 'decommission' || r.action === 'delete') && r.merge_with_id === wbId
  );
  if (retainedBy && retainedBy.workbook_id !== wbId) return 'keep';
  if (rec.action === 'decommission' || rec.action === 'delete') {
    const opposing = (allRecs || []).find(
      r => (r.action === 'decommission' || r.action === 'delete')
        && r.workbook_id === rec.merge_with_id && r.merge_with_id === wbId
    );
    if (opposing && (rec.uniqueness_score || 0) > (opposing.uniqueness_score || 0)) return 'keep';
  }
  return rec.action;
}

function shouldShowRecHint(wbId, rec, allRecs) {
  const action = effectiveRecAction(wbId, rec, allRecs);
  if (!rec || action === 'keep' || !rec.merge_with_name) return false;
  return true;
}

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
        <StatCard icon={Tags} value={multiWbClusters} label="Shared KPIs" color="amber" />
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
            const displayAction = effectiveRecAction(wb.id, rec, recommendations);
            return (
              <div
                key={wb.id}
                className="card card-clickable"
                onClick={() => navigate(`/workbooks/${wb.id}`)}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                    <h3>{wb.name}</h3>
                    {displayAction && <Badge action={displayAction} />}
                  </div>
                  <p className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: 8 }}>
                    {wb.sheet_count} sheets &middot; {wb.calculated_field_count || 0} calc fields
                    &middot; {wb.datasource_count || 0} datasources
                    {wb.has_vba_macros && <> &middot; <span style={{ color: 'var(--accent-rose)' }}>VBA</span></>}
                  </p>
                  {wb.purpose && (
                    <p className="text-muted" style={{ fontSize: '0.8rem' }}>{wb.purpose}</p>
                  )}
                  {rec && shouldShowRecHint(wb.id, rec, recommendations) && (
                    <p style={{ fontSize: '0.8rem', color: 'var(--accent-amber)', marginTop: 6 }}>
                      <GitCompare size={13} style={{ verticalAlign: -2 }} />{' '}
                      {displayAction === 'decommission'
                        ? `Decommission → retain "${rec.merge_with_name}"`
                        : displayAction === 'merge'
                          ? `Merge with "${rec.merge_with_name}"`
                          : `Related to "${rec.merge_with_name}"`}
                      {rec.kpi_overlap_score > 0 && ` (${Math.round(rec.kpi_overlap_score * 100)}% KPI overlap)`}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

