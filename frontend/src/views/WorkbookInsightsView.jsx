import { useState, useEffect, useMemo } from 'react';
import {
  FileSpreadsheet, Sparkles, Filter, LayoutGrid, Link2, Table2, ChevronDown, ChevronRight,
} from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Badge, Loader, EmptyState } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';
import {
  sheetTypeLabel,
  columnTypeLabel,
  describeActiveFilters,
  parsePivotLayouts,
  describePivotLayout,
  describeRelationships,
  workbookSummaryText,
  sheetSummaryText,
} from '../utils/businessContext';

export default function WorkbookInsightsView() {
  const { data: workbooks, loading: wbLoading } = useApi(api.getWorkbooks);
  const { data: dashboards, loading: dashLoading } = useApi(api.getDashboards);
  const { data: catalog } = useApi(api.getBusinessCatalog);
  const { data: recommendations } = useApi(api.getRecommendations);
  const [selectedWbId, setSelectedWbId] = useState(null);
  const [expandedSheets, setExpandedSheets] = useState({});
  const [dashboardDetails, setDashboardDetails] = useState({});
  const [loadingDetails, setLoadingDetails] = useState({});

  const recMap = useMemo(() => {
    const map = {};
    (recommendations || []).forEach(r => { map[r.workbook_id] = r; });
    return map;
  }, [recommendations]);

  const wbDashboards = useMemo(() => {
    if (!dashboards || !selectedWbId) return [];
    return dashboards.filter(d => d.workbook_id === selectedWbId);
  }, [dashboards, selectedWbId]);

  const selectedWb = useMemo(
    () => (workbooks || []).find(w => w.id === selectedWbId),
    [workbooks, selectedWbId],
  );

  const selectedRec = selectedWbId ? recMap[selectedWbId] : null;

  const summaryDashboard = useMemo(
    () => wbDashboards.find(d => d.sheet_type === 'summary_report') || wbDashboards[0],
    [wbDashboards],
  );

  const catalogEntry = useMemo(
    () => (catalog?.workbooks || []).find(w => w.id === selectedWbId),
    [catalog, selectedWbId],
  );

  const businessContext = useMemo(() => ({
    lineOfBusiness: catalogEntry?.line_of_business || summaryDashboard?.line_of_business,
    businessGroup:
      catalogEntry?.primary_business_group
      || catalogEntry?.user_groups?.[0]
      || summaryDashboard?.user_groups?.[0],
    suggested: catalogEntry?.metadata_suggested,
  }), [catalogEntry, summaryDashboard]);

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

  const overview = workbookSummaryText(selectedWb, summaryDashboard);

  return (
    <div className="page-enter">
      <PageHeader
        title="Workbook Guide"
        subtitle="Business summaries, sheet context, filters, and plain-language column definitions."
        actions={workbooks?.length > 0 ? (
          <select
            value={selectedWbId || ''}
            onChange={e => {
              setSelectedWbId(Number(e.target.value));
              setExpandedSheets({});
            }}
            className="input-select"
          >
            {workbooks.map(wb => (
              <option key={wb.id} value={wb.id}>{wb.name}</option>
            ))}
          </select>
        ) : null}
      />

      {(!workbooks || workbooks.length === 0) ? (
        <EmptyState
          icon={FileSpreadsheet}
          title="No workbooks yet"
          message="Upload workbooks to see business summaries and sheet context."
        />
      ) : (
        <>
          <div className="card insight-overview-card">
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
              <div className="insight-icon-wrap">
                <Sparkles size={18} />
              </div>
              <div style={{ flex: 1 }}>
                <h3 style={{ marginBottom: 8, fontSize: '1rem' }}>{selectedWb?.name}</h3>
                {overview ? (
                  <p className="insight-body-text">{overview}</p>
                ) : (
                  <p className="text-muted" style={{ fontSize: '0.9rem' }}>
                    Run <strong>BI Intelligence</strong> from the sidebar to generate a business summary for this workbook.
                  </p>
                )}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
                  {businessContext.lineOfBusiness && (
                    <span className={`badge badge-blue ${businessContext.suggested ? 'badge-suggested' : ''}`}>
                      {businessContext.lineOfBusiness}
                    </span>
                  )}
                  {businessContext.businessGroup && (
                    <span className={`badge badge-amber ${businessContext.suggested ? 'badge-suggested' : ''}`}>
                      {businessContext.businessGroup}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {selectedRec && selectedRec.action === 'decommission' && selectedRec.merge_with_name && (
            <div className="card" style={{
              marginBottom: 16,
              borderLeft: '3px solid var(--status-decommission)',
              background: 'var(--status-decommission-bg)',
            }}>
              <p style={{ fontSize: '0.85rem', margin: 0 }}>
                <strong>Rationalization:</strong> Decommission &quot;{selectedWb?.name}&quot; → retain &quot;{selectedRec.merge_with_name}&quot;
              </p>
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
            <EmptyState icon={Table2} title="No sheets" message="This workbook has no sheets to summarize." />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <h3 className="section-title">Sheets in this workbook</h3>
              {wbDashboards.map(dash => (
                <SheetInsightCard
                  key={dash.id}
                  dash={dash}
                  detail={dashboardDetails[dash.id]}
                  isLoading={loadingDetails[dash.id]}
                  isExpanded={!!expandedSheets[dash.id]}
                  onToggle={() => toggleSheet(dash.id)}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SheetInsightCard({ dash, detail, isLoading, isExpanded, onToggle }) {
  const summary = detail ? sheetSummaryText(dash, detail.worksheets) : sheetSummaryText(dash, []);
  const filters = detail ? describeActiveFilters(detail.filters) : null;

  const pivots = useMemo(() => {
    if (!detail) return [];
    const fromMeta = parsePivotLayouts(detail.raw_metadata?.pivot_tables);
    const fromTables = (detail.worksheets || []).flatMap(ws => parsePivotLayouts(ws.pivot_configuration));
    return fromMeta.length ? fromMeta : fromTables;
  }, [detail]);

  const relationships = useMemo(() => {
    if (!detail?.worksheets) return [];
    return detail.worksheets.flatMap(ws => describeRelationships(ws.inter_table_relationships));
  }, [detail]);

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <button type="button" className="insight-sheet-header" onClick={onToggle}>
        {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <FileSpreadsheet size={16} style={{ color: 'var(--accent-blue)', flexShrink: 0 }} />
        <span style={{ fontWeight: 650, flex: 1, textAlign: 'left' }}>{dash.name}</span>
        <span className="badge badge-blue" style={{ fontSize: '0.65rem' }}>
          {sheetTypeLabel(dash.sheet_type)}
        </span>
      </button>

      {!isExpanded && dash.ai_summary && (
        <p className="insight-body-text" style={{ padding: '0 18px 14px', fontSize: '0.85rem', margin: 0 }}>
          {dash.ai_summary}
        </p>
      )}

      {isExpanded && (
        <div style={{ padding: '0 18px 18px', borderTop: '1px solid var(--glass-border)' }}>
          {isLoading && <div style={{ paddingTop: 16 }}><Loader /></div>}

          {!isLoading && detail && (
            <div style={{ paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 18 }}>
              {summary && (
                <InsightBlock icon={Sparkles} title="What this sheet does">
                  <p className="insight-body-text">{summary}</p>
                </InsightBlock>
              )}

              {filters && filters.length > 0 && (
                <InsightBlock icon={Filter} title="Active filters on this report">
                  <ul className="insight-list">
                    {filters.map((f, i) => (
                      <li key={i}>{f.text}</li>
                    ))}
                  </ul>
                </InsightBlock>
              )}

              {pivots.length > 0 && (
                <InsightBlock icon={LayoutGrid} title="How the report is organized">
                  {pivots.map((pivot, i) => (
                    <div key={i} className="insight-subcard">
                      <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: 6 }}>{pivot.name}</div>
                      <p className="insight-body-text">{describePivotLayout(pivot)}</p>
                    </div>
                  ))}
                </InsightBlock>
              )}

              {(detail.worksheets || []).length > 0 && (
                <InsightBlock icon={Table2} title="Tables on this sheet">
                  <ColumnGuide detail={detail} />
                </InsightBlock>
              )}

              {relationships.length > 0 && (
                <InsightBlock icon={Link2} title="How tables connect">
                  <ul className="insight-list">
                    {relationships.map((rel, i) => (
                      <li key={i}>{rel}</li>
                    ))}
                  </ul>
                </InsightBlock>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ColumnGuide({ detail }) {
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
          <div key={ws.id} className="insight-subcard">
            <h4 style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <Table2 size={14} style={{ color: 'var(--accent-blue)' }} />
              {ws.name}
            </h4>

            {ws.business_purpose && (
              <p className="insight-body-text" style={{ marginBottom: 8 }}>{ws.business_purpose}</p>
            )}

            {ws.measures?.length > 0 && (
              <p className="insight-meta-line" style={{ marginBottom: 4 }}>
                <strong>Measures shown:</strong> {ws.measures.join(', ')}
              </p>
            )}
            {ws.dimensions?.length > 0 && (
              <p className="insight-meta-line" style={{ marginBottom: 12 }}>
                <strong>Grouped by:</strong> {ws.dimensions.join(', ')}
              </p>
            )}

            {tableCols.length > 0 ? (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Column</th>
                      <th>Kind</th>
                      <th>What it means</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableCols.map(col => (
                      <tr key={col.id}>
                        <td style={{ fontWeight: 500 }}>{col.column_name}</td>
                        <td>
                          <span className={`badge ${col.column_type === 'formula_based' ? 'badge-purple' : 'badge-blue'}`}>
                            {columnTypeLabel(col.column_type)}
                          </span>
                        </td>
                        <td className="text-secondary" style={{ fontSize: '0.85rem', maxWidth: 420 }}>
                          {col.definition || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-muted" style={{ fontSize: '0.85rem' }}>No column definitions available.</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function InsightBlock({ icon: Icon, title, children }) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Icon size={15} style={{ color: 'var(--accent-blue)' }} />
        <span className="section-title" style={{ margin: 0 }}>{title}</span>
      </div>
      {children}
    </div>
  );
}
