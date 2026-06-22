import { useState } from 'react';
import { Tags, Search, FileSpreadsheet, Network } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Loader, EmptyState, KPIDashboardGraph } from '../components/shared';

export default function KpiExplorerView() {
  const { data: clusters, loading } = useApi(api.getKpiClusters);
  const [search, setSearch] = useState('');
  const [showGraph, setShowGraph] = useState(false);

  if (loading) return <Loader />;

  const filtered = (clusters || []).filter(c =>
    !search || c.canonical_name.toLowerCase().includes(search.toLowerCase()) ||
    (c.original_names || []).some(n => n.toLowerCase().includes(search.toLowerCase()))
  );

  const multiWb = filtered.filter(c => c.workbook_count > 1);
  const singleWb = filtered.filter(c => c.workbook_count <= 1);

  return (
    <div className="page-enter">
      <div className="section-header" style={{ marginBottom: 16 }}>
        <div>
          <h1>KPI Explorer</h1>
          <p className="text-secondary" style={{ fontSize: '0.85rem', marginTop: 4 }}>
            Explore extracted calculated fields and their canonical groupings.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            onClick={() => setShowGraph(!showGraph)}
            className={`btn ${showGraph ? 'btn-primary' : 'btn-ghost'}`}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', fontSize: '0.85rem' }}
          >
            <Network size={14} />
            {showGraph ? 'Hide Visual Graph' : 'Show Visual Graph'}
          </button>
          <div style={{ position: 'relative' }}>
            <Search size={16} style={{
              position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
              color: 'var(--text-muted)',
            }} />
            <input
              type="text"
              placeholder="Search KPIs..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                padding: '8px 12px 8px 36px',
                background: 'var(--bg-input)',
                border: '1px solid var(--glass-border)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontSize: '0.875rem',
                width: 200,
                fontFamily: 'inherit',
              }}
            />
          </div>
        </div>
      </div>

      {showGraph && (
        <div className="card animate-slide-up" style={{ height: '480px', marginBottom: '24px', padding: '16px' }}>
          <KPIDashboardGraph dashboards="" height="100%" />
        </div>
      )}

      {filtered.length === 0 ? (
        <EmptyState
          icon={Tags}
          title="No KPI clusters"
          message="Upload workbooks to generate KPI clusters."
        />
      ) : (
        <>
          {/* Multi-workbook clusters — the interesting ones */}
          {multiWb.length > 0 && (
            <div style={{ marginBottom: 32 }}>
              <h3 className="section-title" style={{ marginBottom: 12 }}>
                Cross-Workbook Clusters ({multiWb.length})
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {multiWb.map((c, i) => <ClusterCard key={i} cluster={c} highlight />)}
              </div>
            </div>
          )}

          {/* Single-workbook clusters */}
          {singleWb.length > 0 && (
            <div>
              <h3 className="section-title" style={{ marginBottom: 12 }}>
                Single-Workbook Clusters ({singleWb.length})
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Tags size={16} style={{ color: 'var(--accent-purple)' }} />
          <h3 style={{ fontSize: '0.95rem' }}>{cluster.canonical_name}</h3>
          <span className="badge badge-purple">
            {(cluster.original_names || []).length} members
          </span>
          {cluster.workbook_count > 1 && (
            <span className="badge badge-blue">
              <FileSpreadsheet size={11} /> {cluster.workbook_count} workbooks
            </span>
          )}
        </div>
        <span className="text-muted" style={{ fontSize: '0.75rem' }}>
          {cluster.cluster_method || 'lexical'}
        </span>
      </div>

      {expanded && (cluster.original_names || []).length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--glass-border)' }}>
          <span className="text-muted" style={{ fontSize: '0.75rem' }}>Original names: </span>
          <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {cluster.original_names.map((name, i) => (
              <code key={i} style={{
                fontSize: '0.75rem',
                background: 'var(--bg-base)',
                padding: '2px 8px',
                borderRadius: 4,
                color: 'var(--text-secondary)',
              }}>{name}</code>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

