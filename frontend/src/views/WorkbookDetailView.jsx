import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Table2, Code2, ExternalLink, EyeOff, Filter, LayoutGrid, Link2 } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Loader } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';
import { useState, Fragment, useMemo } from 'react';
import LineageGraph from '../components/detail/LineageGraph';
import {
  describeActiveFilters,
  parsePivotLayouts,
  describePivotLayout,
  describeRelationships,
} from '../utils/businessContext';

export default function WorkbookDetailView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: wb, loading } = useApi(() => api.getWorkbook(id), [id]);
  const [activeSheet, setActiveSheet] = useState(null);

  if (loading || !wb) return <Loader />;

  const dashboards = wb.dashboards || [];
  const selectedSheet = activeSheet !== null ? dashboards[activeSheet]
    : dashboards.length > 0 ? dashboards[0] : null;

  return (
    <div className="page-enter">
      <PageHeader
        title={wb.name}
        subtitle={wb.purpose || undefined}
        leading={(
          <button className="btn btn-ghost" onClick={() => navigate('/discovery')} style={{ marginTop: 4, padding: '8px 10px' }}>
            <ArrowLeft size={16} />
          </button>
        )}
      />

      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 20 }}>
          <MetaItem label="Sheets" value={wb.sheet_count} />
          <MetaItem label="Calculated Fields" value={wb.calculated_field_count} />
          <MetaItem label="Datasources" value={wb.datasource_count} />
          <MetaItem label="VBA Macros" value={wb.has_vba_macros ? 'Yes' : 'No'} highlight={wb.has_vba_macros} />
        </div>
      </div>

      {wb.external_links && wb.external_links.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <h3 style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
            <ExternalLink size={16} /> External Links
          </h3>
          {wb.external_links.map((link, i) => (
            <div key={i} className="text-secondary" style={{ fontSize: '0.85rem', padding: '4px 0' }}>
              {link}
            </div>
          ))}
        </div>
      )}

      {dashboards.length > 0 && (
        <>
          <div className="tabs">
            {dashboards.map((d, i) => (
              <button
                key={d.id}
                className={`tab ${(activeSheet === i || (activeSheet === null && i === 0)) ? 'active' : ''}`}
                onClick={() => setActiveSheet(i)}
              >
                {d.name}
                {d.sheet_type && <span className="text-muted" style={{ fontSize: '0.7rem', marginLeft: 6 }}>
                  {d.sheet_type}
                </span>}
              </button>
            ))}
          </div>

          {selectedSheet && <SheetDetail sheet={selectedSheet} />}
        </>
      )}
    </div>
  );
}

function MetaItem({ label, value, highlight }) {
  return (
    <div>
      <div className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 2 }}>{label}</div>
      <div style={{ fontWeight: 600, color: highlight ? 'var(--accent-rose)' : 'var(--text-primary)' }}>
        {value ?? '—'}
      </div>
    </div>
  );
}

function SheetDetail({ sheet }) {
  const { data: detail, loading } = useApi(() => api.getDashboard(sheet.id), [sheet.id]);
  const [selectedCol, setSelectedCol] = useState(null);
  const [selectedTableId, setSelectedTableId] = useState(null);
  const [expandedSummaryRow, setExpandedSummaryRow] = useState(null);

  const filters = describeActiveFilters(detail?.filters);
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

  if (loading) return <Loader />;
  if (!detail) return null;

  const cols = detail.columns || [];
  const worksheets = detail.worksheets || [];
  const activeTableId = selectedTableId !== null ? selectedTableId : (worksheets[0]?.id || null);
  const selectedTable = worksheets.find(ws => ws.id === activeTableId) || null;
  const displayCols = selectedTable
    ? cols.filter(col => col.table_name === selectedTable.name)
    : [];

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3>{detail.name}</h3>
        <div className="text-muted" style={{ fontSize: '0.8rem' }}>
          {detail.row_count} rows × {detail.column_count} cols
          &middot; {detail.formula_count || 0} formulas
          {detail.pivot_table_count > 0 && ` · ${detail.pivot_table_count} pivots`}
        </div>
      </div>

      {detail.ai_summary && (
        <p className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: 16, fontStyle: 'italic' }}>
          {detail.ai_summary}
        </p>
      )}

      {(detail.hidden_row_count > 0 || detail.hidden_column_count > 0) && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          {detail.hidden_row_count > 0 && (
            <span className="badge badge-decommission">
              <EyeOff size={12} /> {detail.hidden_row_count} hidden rows
            </span>
          )}
          {detail.hidden_column_count > 0 && (
            <span className="badge badge-decommission">
              <EyeOff size={12} /> {detail.hidden_column_count} hidden cols
            </span>
          )}
        </div>
      )}

      {filters && filters.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
            <Filter size={13} style={{ color: 'var(--accent-blue)' }} /> Active Filters
          </p>
          <ul style={{ margin: 0, paddingLeft: 20, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            {filters.map((f, i) => (
              <li key={i} style={{ marginBottom: 4 }}>{f.text}</li>
            ))}
          </ul>
        </div>
      )}

      {pivots.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
            <LayoutGrid size={13} style={{ color: 'var(--accent-blue)' }} /> Report Organization (Pivots)
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {pivots.map((pivot, i) => (
              <div key={i} style={{ background: 'var(--bg-surface)', padding: 10, borderRadius: 6, border: '1px solid var(--glass-border)' }}>
                <div style={{ fontWeight: 600, fontSize: '0.8rem', marginBottom: 4 }}>{pivot.name}</div>
                <p className="text-secondary" style={{ fontSize: '0.8rem', margin: 0 }}>{describePivotLayout(pivot)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {relationships.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
            <Link2 size={13} style={{ color: 'var(--accent-blue)' }} /> Table Connections
          </p>
          <ul style={{ margin: 0, paddingLeft: 20, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            {relationships.map((rel, i) => (
              <li key={i} style={{ marginBottom: 4 }}>{rel}</li>
            ))}
          </ul>
        </div>
      )}

      {worksheets.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <h4 className="section-title" style={{ marginBottom: 8 }}>Tables</h4>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {worksheets.map(ws => {
              const isActive = activeTableId === ws.id;
              return (
                <button
                  key={ws.id}
                  type="button"
                  className={`badge badge-blue ${isActive ? 'active' : ''}`}
                  onClick={() => {
                    setSelectedTableId(ws.id);
                    setExpandedSummaryRow(null);
                    setSelectedCol(null);
                  }}
                  style={{
                    cursor: 'pointer',
                    border: isActive ? '2px solid var(--accent-blue)' : undefined,
                    background: isActive ? 'rgba(236, 63, 6, 0.1)' : undefined,
                  }}
                >
                  <Table2 size={12} /> {ws.name} ({ws.row_count}×{ws.column_count})
                </button>
              );
            })}
          </div>
        </div>
      )}

      {selectedTable && (
        <div className="card animate-slide-up" style={{ marginBottom: 24, border: '1px solid var(--glass-border)', background: 'var(--bg-base)' }}>
          <h4 style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Table2 size={16} style={{ color: 'var(--accent-blue)' }} /> {selectedTable.name}
          </h4>

          {selectedTable.table_range && (
            <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 8 }}>
              Range: {selectedTable.table_range}
            </p>
          )}

          {selectedTable.business_purpose && (
            <div style={{ marginBottom: 16 }}>
              <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>Table Definition</p>
              <p className="text-secondary" style={{ fontSize: '0.85rem' }}>{selectedTable.business_purpose}</p>
            </div>
          )}

          {selectedTable.summary_rows && selectedTable.summary_rows.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 8 }}>Summary Rows</p>
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Label</th>
                      <th>Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedTable.summary_rows.map((row, idx) => {
                      const rowKey = `${row.row_number}-${row.row_type}`;
                      const isExpanded = expandedSummaryRow === rowKey;
                      return (
                        <Fragment key={rowKey}>
                          <tr
                            onClick={() => setExpandedSummaryRow(isExpanded ? null : rowKey)}
                            style={{ cursor: 'pointer' }}
                            className={isExpanded ? 'active' : ''}
                          >
                            <td style={{ fontWeight: 500 }}>{row.label}</td>
                            <td>
                              <span className="badge badge-purple">{row.row_type}</span>
                            </td>
                          </tr>
                          {isExpanded && row.cells && (
                            <tr>
                              <td colSpan={2} style={{ padding: 0 }}>
                                <div style={{ padding: 12, background: 'var(--bg-surface)' }}>
                                  <table className="data-table" style={{ fontSize: '0.8rem' }}>
                                    <thead>
                                      <tr>
                                        <th>Column</th>
                                        <th>Value</th>
                                        <th>Formula</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {row.cells.map((cell, ci) => (
                                        <tr key={ci}>
                                          <td>{cell.column_name}</td>
                                          <td className="text-muted">{cell.value != null ? String(cell.value) : '—'}</td>
                                          <td>
                                            {cell.formula ? (
                                              <code className="mono" style={{ fontSize: '0.7rem' }}>{cell.formula}</code>
                                            ) : cell.formula_pattern ? (
                                              <code className="mono" style={{ fontSize: '0.7rem' }}>{cell.formula_pattern}</code>
                                            ) : '—'}
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {displayCols.length > 0 && (
            <div>
              <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 8 }}>Table Columns</p>
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Column</th>
                      <th>Type</th>
                      <th>Definition</th>
                      <th>Formula</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayCols.map(col => (
                      <tr
                        key={col.id}
                        onClick={() => setSelectedCol(selectedCol?.id === col.id ? null : col)}
                        style={{ cursor: col.formula ? 'pointer' : undefined }}
                        className={selectedCol?.id === col.id ? 'active' : ''}
                      >
                        <td style={{ fontWeight: 500 }}>{col.column_name}</td>
                        <td>
                          <span className={`badge ${col.column_type === 'formula_based' ? 'badge-purple' : 'badge-blue'}`}>
                            {['raw', 'label'].includes(col.column_type)
                              ? (col.data_type || col.column_type)
                              : (col.column_type || 'data')}
                          </span>
                        </td>
                        <td className="text-muted" style={{ fontSize: '0.8rem', maxWidth: 200 }}>{col.definition || '—'}</td>
                        <td>
                          {col.formula ? (
                            <code className="mono" style={{
                              fontSize: '0.75rem',
                              background: 'var(--bg-base)',
                              padding: '2px 6px',
                              borderRadius: 4,
                              maxWidth: 250,
                              display: 'inline-block',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}>{col.formula}</code>
                          ) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {selectedCol && (
        <div className="card animate-slide-up" style={{ marginBottom: 24, border: '1px solid var(--glass-border)', background: 'var(--bg-base)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div>
              <h3 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '1.1rem' }}>
                <Code2 size={18} style={{ color: 'var(--accent-blue)' }} /> Lineage Graph: {selectedCol.column_name}
              </h3>
              <p className="text-secondary" style={{ fontSize: '0.8rem', marginTop: 4 }}>
                Traces formula dependency flow from source tables into calculation cells
              </p>
            </div>
            <button
              className="btn btn-ghost"
              onClick={() => setSelectedCol(null)}
              style={{ padding: '6px 12px', fontSize: '0.8rem', background: 'var(--bg-surface)' }}
            >
              Close Graph
            </button>
          </div>

          <div style={{ marginBottom: 16 }}>
            <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>Formula Expression</p>
            <code className="mono" style={{ display: 'block', background: 'var(--bg-surface)', padding: 12, borderRadius: 6, fontSize: '0.8rem', border: '1px solid var(--glass-border)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', color: 'var(--text-primary)' }}>
              {selectedCol.formula || 'No formula (Raw Column)'}
            </code>
          </div>

          {selectedCol.formula_lineage?.fingerprint && (
            <div style={{ marginBottom: 16 }}>
              <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 4 }}>Logic Fingerprint</p>
              <code className="mono" style={{ display: 'block', background: 'var(--bg-surface)', padding: '6px 10px', borderRadius: 6, fontSize: '0.75rem', border: '1px solid var(--glass-border)', color: 'var(--accent-purple)' }}>
                {selectedCol.formula_lineage.fingerprint}
              </code>
            </div>
          )}

          <LineageGraph
            columnName={selectedCol.column_name}
            tableName={selectedCol.table_name || detail.name}
            formula={selectedCol.formula}
            lineage={selectedCol.formula_lineage}
          />
        </div>
      )}

    </div>
  );
}
