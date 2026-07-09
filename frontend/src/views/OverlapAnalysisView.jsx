import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import {
  GitMerge, Layers, AlertTriangle, Target,
  ChevronRight, Search, RefreshCw,
} from 'lucide-react';
import { Loader, EmptyState } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';
import './OverlapAnalysisView.css';

// ─── Streamlined Cluster Card ─────────────────────────────────

function StreamlinedClusterCard({ cluster, onClick }) {
  const { cluster_name, cluster_size, cohesion_score,
          canonical_target_name, cluster_validation_flag, suspect_edges } = cluster;

  const hasSuspect = cluster_validation_flag === 'llm_suspect' ||
    (Array.isArray(suspect_edges) && suspect_edges.length > 0);

  const redundantCount = cluster_size - 1;

  const cohesionRating = cohesion_score >= 0.6 ? 'Strong'
    : cohesion_score >= 0.35 ? 'Moderate'
    : 'Weak';

  const cohesionColor = cohesion_score >= 0.6 ? 'var(--accent-emerald)'
    : cohesion_score >= 0.35 ? 'var(--accent-amber)'
    : 'var(--accent-rose)';

  return (
    <div className="compact-cluster-card card card-clickable" onClick={onClick}>
      {/* Top row: Cluster Name & Flag */}
      <div className="cc-card-header">
        <div className="cc-title-group">
          <Layers size={14} style={{ color: 'var(--accent-blue)', flexShrink: 0 }} />
          <h4 className="cc-card-title" title={cluster_name}>{cluster_name}</h4>
        </div>
        {hasSuspect && (
          <span className="badge badge-amber" style={{ fontSize: '0.65rem' }}>
            <AlertTriangle size={10} /> Flagged
          </span>
        )}
      </div>

      {/* Mid row: Canonical Target Subtitle */}
      {canonical_target_name && (
        <div className="cc-canonical-target">
          <Target size={11} style={{ color: 'var(--accent-emerald)', flexShrink: 0 }} />
          <span className="cc-canonical-name" title={canonical_target_name}>
            {canonical_target_name}
          </span>
        </div>
      )}

      {/* Bottom Row: Ratio & Cohesion */}
      <div className="cc-card-footer">
        <span className="cc-ratio-text">
          Consolidates <strong>{redundantCount}</strong> report{redundantCount !== 1 ? 's' : ''}
        </span>
        <div className="cc-cohesion-pill">
          <span className="cc-cohesion-dot" style={{ background: cohesionColor }} />
          <span className="cc-cohesion-val" style={{ color: cohesionColor }}>
            {cohesionRating} ({Math.round(cluster_score_calc(cohesion_score))})
          </span>
        </div>
      </div>
    </div>
  );
}

function cluster_score_calc(score) {
  return Math.round((score || 0) * 100);
}

// ─── Main Overlap View ────────────────────────────────────────

export default function OverlapAnalysisView() {
  const [clusters, setClusters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeFilter, setActiveFilter] = useState('all');
  const [search, setSearch] = useState('');
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getClusters();
      setClusters(data || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Filters
  const filtered = useMemo(() => {
    let result = clusters;
    if (activeFilter === 'multi')   result = result.filter(c => c.cluster_size > 1);
    if (activeFilter === 'flagged') result = result.filter(c => c.cluster_validation_flag === 'llm_suspect');
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(c =>
        c.cluster_name.toLowerCase().includes(q) ||
        (c.members || []).some(m => m.workbook_name.toLowerCase().includes(q))
      );
    }
    return result;
  }, [clusters, activeFilter, search]);

  const multiClusters = filtered.filter(c => c.cluster_size > 1);
  const singletonClusters = filtered.filter(c => c.cluster_size === 1);

  if (loading) return (
    <div className="page-enter"><PageHeader title="Overlap Analysis" /><Loader /></div>
  );

  if (!clusters.length) return (
    <div className="page-enter">
      <PageHeader title="Overlap Analysis" />
      <EmptyState
        icon={Layers}
        title="No cluster data yet"
        message="Run the Rationalization agent to generate workbook clusters. For best results, run Intelligence first."
      />
    </div>
  );

  return (
    <div className="page-enter">
      <PageHeader
        title="Overlap Analysis"
        subtitle="Identify and consolidate redundant report clusters."
        actions={
          <button className="btn btn-ghost btn-sm" onClick={load}>
            <RefreshCw size={14} /> Refresh
          </button>
        }
      />

      {/* Filters & search */}
      <div className="ration-toolbar streamlined">
        <div className="ration-search">
          <Search />
          <input
            placeholder="Search reports or groups…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div className="ration-pills">
          {[
            { id: 'all',          label: 'All Groups',      dot: 'var(--text-muted)' },
            { id: 'multi',        label: 'Requires Action', dot: 'var(--accent-blue)' },
            { id: 'flagged',      label: 'Flagged',         dot: 'var(--accent-amber)' },
          ].map(({ id, label, dot }) => (
            <button
              key={id}
              className={`ration-pill ${activeFilter === id ? 'active-' + (id === 'all' ? 'all' : id === 'multi' ? 'keep' : 'review') : ''}`}
              onClick={() => setActiveFilter(id)}
            >
              <span className="pill-dot" style={{ background: dot }} />
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="agent-run-banner tone-error" style={{ marginBottom: 16 }}>
          <div className="agent-run-banner-text">
            <AlertTriangle size={16} style={{ color: 'var(--accent-rose)', flexShrink: 0 }} />
            <span>{error}</span>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={load}>Retry</button>
        </div>
      )}

      {/* Split Column Layout */}
      <div className="overlap-split-layout">
        {/* Left Column: Overlapping Groups (Primary) */}
        <div className="overlap-main-content">
          <div className="col-title-row">
            <GitMerge size={15} style={{ color: 'var(--accent-blue)' }} />
            <h3>Overlapping Workbook Groups ({multiClusters.length})</h3>
          </div>
          
          {multiClusters.length > 0 ? (
            <div className="streamlined-cluster-grid">
              {multiClusters.map(cluster => (
                <StreamlinedClusterCard
                  key={cluster.id}
                  cluster={cluster}
                  onClick={() => navigate(`/overlap-analysis/cluster/${cluster.id}`)}
                />
              ))}
            </div>
          ) : (
            !error && (
              <div className="empty-state">
                <Layers />
                <h3>No overlap groups found</h3>
                <p>Try adjusting your search query or filters.</p>
              </div>
            )
          )}
        </div>

        {/* Right Column: Unique Reports (Secondary) */}
        <div className="overlap-sidebar-content">
          <div className="col-title-row sidebar">
            <Layers size={15} style={{ color: 'var(--text-muted)' }} />
            <h3>Unique Reports ({singletonClusters.length})</h3>
          </div>
          
          {singletonClusters.length > 0 ? (
            <div className="singletons-list-card card">
              <p className="singletons-panel-desc">
                These reports have 0% overlap and require no changes.
              </p>
              <div className="singletons-list-stack">
                {singletonClusters.map(c => (
                  <div
                    key={c.id}
                    className="singleton-item-row"
                    onClick={() => navigate(`/rationalization/review/keep/${c.members?.[0]?.workbook_id}`)}
                  >
                    <span className="singleton-item-name" title={c.members?.[0]?.workbook_name || c.cluster_name}>
                      {c.members?.[0]?.workbook_name || c.cluster_name}
                    </span>
                    <ChevronRight size={13} className="singleton-item-chevron" />
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="empty-sidebar-state card">
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No unique reports found</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
