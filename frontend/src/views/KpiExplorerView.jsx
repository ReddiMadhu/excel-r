import { useState, useMemo } from 'react';
import { Tags, Search, FileSpreadsheet } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Loader, EmptyState } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';

export default function KpiExplorerView() {
  const { data: clusters, loading } = useApi(api.getKpiClusters);
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => (clusters || []).filter(c =>
    !search || c.canonical_name.toLowerCase().includes(search.toLowerCase()) ||
    (c.original_names || []).some(n => n.toLowerCase().includes(search.toLowerCase()))
  ), [clusters, search]);

  const multiWb = useMemo(() => filtered.filter(c => c.workbook_count > 1), [filtered]);
  const singleWb = useMemo(() => filtered.filter(c => c.workbook_count <= 1), [filtered]);

  if (loading) return <Loader />;

  return (
    <div className="page-enter">
      <PageHeader
        title="Shared Metrics"
        subtitle="Business metrics that appear across reports — useful for spotting overlap and duplicate reports."
        actions={(
          <div style={{ position: 'relative' }}>
            <Search size={16} style={{
              position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
              color: 'var(--text-muted)',
            }} />
            <input
              type="text"
              placeholder="Search metrics..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                padding: '8px 12px 8px 36px',
                background: 'var(--bg-input)',
                border: '1px solid var(--glass-border)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
                width: 220,
                fontFamily: 'inherit',
              }}
            />
          </div>
        )}
      />

      {filtered.length === 0 ? (
        <EmptyState
          icon={Tags}
          title="No metrics grouped yet"
          message="Run BI Intelligence after uploading reports to group similar metrics together."
        />
      ) : (
        <>
          {multiWb.length > 0 && (
            <div style={{ marginBottom: 32 }}>
              <h3 className="section-title" style={{ marginBottom: 12 }}>
                Used in multiple reports ({multiWb.length})
              </h3>
              <p className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: 12 }}>
                These metrics appear in more than one file — they may indicate duplicate or overlapping reports.
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {multiWb.map((c, i) => <ClusterCard key={i} cluster={c} highlight />)}
              </div>
            </div>
          )}

          {singleWb.length > 0 && (
            <div>
              <h3 className="section-title" style={{ marginBottom: 12 }}>
                Used in one report only ({singleWb.length})
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {singleWb.map((c, i) => <ClusterCard key={i} cluster={c} />)}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ClusterCard({ cluster, highlight }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="card card-clickable"
      onClick={() => setExpanded(!expanded)}
      style={highlight ? { borderLeft: '3px solid var(--accent-purple)' } : {}}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Tags size={16} style={{ color: 'var(--accent-purple)' }} />
          <h3 style={{ fontSize: '0.95rem' }}>{cluster.canonical_name}</h3>
          {cluster.workbook_count > 1 && (
            <span className="badge badge-blue">
              <FileSpreadsheet size={11} /> {cluster.workbook_count} reports
            </span>
          )}
        </div>
      </div>

      {expanded && (cluster.original_names || []).length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--glass-border)' }}>
          <span className="text-muted" style={{ fontSize: '0.75rem' }}>Also appears as: </span>
          <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {cluster.original_names.map((name, i) => (
              <span key={i} className="badge badge-purple" style={{ fontWeight: 500 }}>
                {name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
