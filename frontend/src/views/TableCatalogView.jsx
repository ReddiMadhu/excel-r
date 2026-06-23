import { useState, useMemo, useEffect } from 'react';
import { Table2, FileSpreadsheet, ChevronDown, ChevronRight } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Badge, Loader, EmptyState } from '../components/shared';

export default function TableCatalogView() {
  const { data: workbooks, loading: wbLoading } = useApi(api.getWorkbooks);
  const { data: dashboards, loading: dashLoading } = useApi(api.getDashboards);
  const { data: recommendations } = useApi(api.getRecommendations);
  const { data: calcFields } = useApi(api.getCalculatedFields);
  const [selectedWbId, setSelectedWbId] = useState(null);
  const [expandedSheets, setExpandedSheets] = useState({});
  const [dashboardDetails, setDashboardDetails] = useState({});
  const [loadingDetails, setLoadingDetails] = useState({});

  const recMap = useMemo(() => {
    const map = {};
    (recommendations || []).forEach(r => { map[r.workbook_id] = r; });
    return map;
  }, [recommendations]);

  const fingerprintMap = useMemo(() => {
    const map = {};
    (calcFields || []).forEach(cf => {
      const key = `${cf.workbook_id}:${cf.table_name}:${cf.name}`;
      map[key] = cf.fingerprint;
    });
    return map;
  }, [calcFields]);

  const wbDashboards = useMemo(() => {
    if (!dashboards || !selectedWbId) return [];
    return dashboards.filter(d => d.workbook_id === selectedWbId);
  }, [dashboards, selectedWbId]);

  useEffect(() => {
    if (workbooks?.length && selectedWbId === null) {
      setSelectedWbId(workbooks[0].id);
    }
  }, [workbooks, selectedWbId]);

  const loadDashboardDetail = async (dashboardId) => {
    if (dashboardDetails[dashboardId] || loadingDetails[dashboardId]) return;
    setLoadingDetails(prev => ({ ...prev, [dashboardId]: true }));
    try {
      const detail = await api.getDashboard(dashboardId);
      setDashboardDetails(prev => ({ ...prev, [dashboardId]: detail }));
    } finally {
      setLoadingDetails(prev => ({ ...prev, [dashboardId]: false }));
    }
  };

  const toggleSheet = (dashboardId) => {
    const isExpanded = expandedSheets[dashboardId];
    setExpandedSheets(prev => ({ ...prev, [dashboardId]: !isExpanded }));
    if (!isExpanded) loadDashboardDetail(dashboardId);
  };

  if (wbLoading || dashLoading) return <Loader />;

  const selectedRec = selectedWbId ? recMap[selectedWbId] : null;
  const selectedWb = (workbooks || []).find(w => w.id === selectedWbId);

  return (
    <div className="page-enter">
      <div className="section-header" style={{ marginBottom: 16 }}>
        <div>
          <h1>Table Catalog</h1>
          <p className="text-secondary" style={{ fontSize: '0.85rem', marginTop: 4 }}>
            Tables, column definitions, formulas, and rationalization context.
          </p>
        </div>
        {workbooks?.length > 0 && (
          <select
            value={selectedWbId || ''}
            onChange={e => setSelectedWbId(Number(e.target.value))}
            style={{
              padding: '8px 12px',
              background: 'var(--bg-input)',
              border: '1px solid var(--glass-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontSize: '0.875rem',
              fontFamily: 'inherit',
              minWidth: 220,
            }}
          >
            {workbooks.map(wb => (
              <option key={wb.id} value={wb.id}>{wb.name}</option>
            ))}
          </select>
        )}
      </div>

      {(!workbooks || workbooks.length === 0) ? (
        <EmptyState
          icon={Table2}
          title="No workbooks"
          message="Upload workbooks to explore tables and column intelligence."
        />
      ) : (
        <>
          {selectedRec && selectedRec.action === 'decommission' && selectedRec.merge_with_name && (
            <div className="card" style={{
              marginBottom: 16,
              borderLeft: '3px solid var(--status-decommission)',
              background: 'var(--status-decommission-bg)',
            }}>
              <p style={{ fontSize: '0.85rem', marginBottom: 4 }}>
                <strong>Rationalization:</strong> Decommission &quot;{selectedWb?.name}&quot; → retain &quot;{selectedRec.merge_with_name}&quot;
              </p>
              {selectedRec.kpi_overlap_score > 0 && (
                <p className="text-muted" style={{ fontSize: '0.75rem' }}>
                  {Math.round(selectedRec.kpi_overlap_score * 100)}% KPI overlap
                  {selectedRec.datasource_overlap_score > 0 && (
                    <> · {Math.round(selectedRec.datasource_overlap_score * 100)}% datasource overlap</>
                  )}
                </p>
              )}
            </div>
          )}

          {selectedRec && selectedRec.action !== 'decommission' && selectedRec.action !== 'keep' && (
            <div className="card" style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Badge action={selectedRec.action} />
              {selectedRec.merge_with_name && (
                <span className="text-secondary" style={{ fontSize: '0.85rem' }}>
                  Related to &quot;{selectedRec.merge_with_name}&quot;
                </span>
              )}
            </div>
          )}

          {wbDashboards.length === 0 ? (
            <EmptyState icon={Table2} title="No sheets" message="This workbook has no sheets." />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {wbDashboards.map(dash => {
                const isExpanded = expandedSheets[dash.id];
                const detail = dashboardDetails[dash.id];
                const isLoading = loadingDetails[dash.id];

                return (
                  <div key={dash.id} className="card">
                    <button
                      type="button"
                      onClick={() => toggleSheet(dash.id)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        width: '100%',
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: 'var(--text-primary)',
                        padding: 0,
                        textAlign: 'left',
                      }}
                    >
                      {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      <FileSpreadsheet size={16} style={{ color: 'var(--accent-blue)' }} />
                      <span style={{ fontWeight: 600 }}>{dash.name}</span>
                      <span className="text-muted" style={{ fontSize: '0.75rem' }}>
                        {dash.table_count || 0} tables · {dash.formula_count || 0} formulas
                      </span>
                    </button>

                    {isExpanded && (
                      <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--glass-border)' }}>
                        {isLoading && <Loader />}
                        {!isLoading && detail && (
                          <TableList
                            detail={detail}
                            workbookId={selectedWbId}
                            fingerprintMap={fingerprintMap}
                          />
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TableList({ detail, workbookId, fingerprintMap }) {
  const worksheets = detail.worksheets || [];
  const columns = detail.columns || [];

  if (worksheets.length === 0) {
    return <p className="text-muted" style={{ fontSize: '0.85rem' }}>No tables detected on this sheet.</p>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {worksheets.map(ws => {
        const tableCols = columns.filter(c => c.table_name === ws.name);
        return (
          <div key={ws.id} style={{
            padding: 16,
            borderRadius: 8,
            border: '1px solid var(--glass-border)',
            background: 'var(--bg-base)',
          }}>
            <h4 style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <Table2 size={14} style={{ color: 'var(--accent-blue)' }} />
              {ws.name}
              <span className="text-muted" style={{ fontSize: '0.7rem', fontWeight: 400 }}>
                {ws.row_count}×{ws.column_count}
              </span>
            </h4>

            {ws.business_purpose && (
              <div style={{ marginBottom: 12 }}>
                <p className="text-muted" style={{ fontSize: '0.7rem', marginBottom: 4 }}>Table Definition</p>
                <p className="text-secondary" style={{ fontSize: '0.85rem' }}>{ws.business_purpose}</p>
              </div>
            )}

            {tableCols.length > 0 && (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Column</th>
                      <th>Type</th>
                      <th>Column Definition</th>
                      <th>Formula</th>
                      <th>Fingerprint</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableCols.map(col => {
                      const fp = col.formula_lineage?.fingerprint
                        || fingerprintMap[`${workbookId}:${ws.name}:${col.column_name}`]
                        || '—';
                      return (
                        <tr key={col.id}>
                          <td style={{ fontWeight: 500 }}>{col.column_name}</td>
                          <td>
                            <span className={`badge ${col.column_type === 'formula_based' ? 'badge-purple' : 'badge-blue'}`}>
                              {col.column_type || 'data'}
                            </span>
                          </td>
                          <td className="text-muted" style={{ fontSize: '0.8rem', maxWidth: 200 }}>
                            {col.definition || '—'}
                          </td>
                          <td>
                            {col.formula ? (
                              <code className="mono" style={{
                                fontSize: '0.7rem',
                                background: 'var(--bg-surface)',
                                padding: '2px 6px',
                                borderRadius: 4,
                                maxWidth: 200,
                                display: 'inline-block',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}>{col.formula}</code>
                            ) : '—'}
                          </td>
                          <td>
                            {fp !== '—' ? (
                              <code className="mono" style={{
                                fontSize: '0.65rem',
                                color: 'var(--accent-purple)',
                                maxWidth: 150,
                                display: 'inline-block',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}>{fp}</code>
                            ) : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
