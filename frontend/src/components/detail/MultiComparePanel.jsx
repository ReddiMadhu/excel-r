import { useState, useEffect, useMemo } from 'react';
import {
  GitCompare, X, Target, Trash2, GitMerge, AlertCircle,
  CheckCircle, AlertTriangle, TrendingUp,
} from 'lucide-react';
import { api } from '../../api/client';
import { Loader } from '../shared';
import { KPIDashboardGraph } from '../shared/KPIDashboardGraph';


function cleanReasons(reasons) {
  return (reasons || []).filter(r => {
    const lower = r.toLowerCase();
    return !lower.includes('fingerprint')
      && !lower.includes('retained workbook')
      && !lower.includes('retained over');
  });
}


/**
 * MultiComparePanel — Side-by-side comparison of multiple candidates vs the Target.
 *
 * Props:
 *   clusterId   – The cluster/group ID
 *   compareIds  – Set<number> of candidate workbook IDs to compare
 *   targetId    – The canonical target workbook ID
 *   onExit      – () => void — callback to exit comparison mode
 */
export default function MultiComparePanel({ clusterId, compareIds, targetId, onExit }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const compareIdsKey = [...compareIds].sort().join(',');

  useEffect(() => {
    if (!clusterId || compareIds.size === 0) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    api.getClusterMultiCompare(clusterId, [...compareIds])
      .then(result => {
        if (!cancelled) setData(result);
      })
      .catch(err => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [clusterId, compareIdsKey]);

  const graphWorkbookIds = useMemo(() => {
    const ids = [...compareIds];
    if (targetId && !ids.includes(targetId)) ids.push(targetId);
    return ids;
  }, [compareIdsKey, targetId]);

  if (loading) return <div className="page-enter" style={{ padding: 40 }}><Loader /></div>;

  if (error || !data) {
    return (
      <div className="card page-enter" style={{ padding: 40, textAlign: 'center' }}>
        <p style={{ color: 'var(--text-muted)' }}>
          {error || 'Could not load comparison data.'}
        </p>
      </div>
    );
  }

  const { target_rec, target_kpis, target_reasons, candidates } = data;

  const getRoleConfig = (type, role) => {
    if (type === 'decommission' || role === 'decommission') return {
      label: 'Archive', icon: Trash2, color: 'var(--accent-rose)', className: 'decommission',
    };
    if (type === 'merge' || role === 'merge_source') return {
      label: 'Merge', icon: GitMerge, color: 'var(--accent-amber)', className: 'merge',
    };
    return {
      label: 'Review', icon: AlertCircle, color: 'var(--text-muted)', className: 'review',
    };
  };

  return (
    <div className="page-enter multi-compare-panel">
      {/* Comparison Header */}
      <div className="multi-compare-header">
        <div className="multi-compare-header-left">
          <div className="multi-compare-icon">
            <GitCompare size={20} />
          </div>
          <div>
            <h1 className="multi-compare-title">
              Comparing Reports
              <span className="multi-compare-count-badge">{candidates.length}</span>
            </h1>
            <p className="multi-compare-subtitle">
              Side-by-side comparison of selected candidates against the recommended target.
            </p>
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onExit} style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontSize: '0.82rem', padding: '6px 14px',
          border: '1px solid var(--glass-border)',
        }}>
          <X size={14} /> Exit Comparison
        </button>
      </div>

      {/* Scrollable Comparison Columns */}
      <div className="multi-compare-scroll-wrapper">
        <div className="multi-compare-columns">
          {/* Candidate Columns (scrollable) */}
          {candidates.map(candidate => {
            const roleConfig = getRoleConfig(candidate.type, candidate.cluster_role);
            const cov = candidate.kpi_coverage;
            const reasons = candidate.reasons || [];

            const kpiCoverage = cov.source_coverage_pct;
            const dsCoverage = cov.source_ds_coverage_pct;
            const uniquePct = cov.source_unique_pct;

            return (
              <div key={candidate.workbook_id} className="compare-col">
                {/* Column Header */}
                <div className="compare-col-header" style={{ borderColor: roleConfig.color }}>
                  <span className="compare-col-label" style={{ color: roleConfig.color }}>
                    {roleConfig.label} Candidate
                  </span>
                  <h2 className="compare-col-name">{candidate.workbook_name}</h2>
                  <span className="compare-col-vs">
                    Compared with "{target_rec?.workbook_name || 'Target'}"
                  </span>
                </div>

                {/* Score Cards */}
                <div className="compare-score-cards">
                  <div className="compare-score-item">
                    <span className="compare-score-label">KPI Overlap</span>
                    <span className="compare-score-value" style={{ color:
                      candidate.type === 'merge'
                        ? (kpiCoverage >= 70 ? 'var(--accent-emerald)' : kpiCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                        : (kpiCoverage >= 90 ? 'var(--accent-rose)' : kpiCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                    }}>
                      {kpiCoverage}%
                    </span>
                    <span className="compare-score-note">{cov.shared_count} of {cov.source_total} KPIs</span>
                  </div>
                  <div className="compare-score-item">
                    <span className="compare-score-label">Data Source Overlap</span>
                    <span className="compare-score-value" style={{ color:
                      candidate.type === 'merge'
                        ? (dsCoverage >= 70 ? 'var(--accent-emerald)' : dsCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                        : (dsCoverage >= 90 ? 'var(--accent-rose)' : dsCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                    }}>
                      {dsCoverage}%
                    </span>
                    <span className="compare-score-note">{cov.ds_shared_count} of {cov.source_ds_count || '?'} sources</span>
                  </div>
                  <div className="compare-score-item">
                    <span className="compare-score-label">Unique KPIs</span>
                    <span className="compare-score-value" style={{ color:
                      uniquePct > 0
                        ? (candidate.type === 'merge' ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                        : 'var(--text-muted)'
                    }}>
                      {uniquePct}%
                    </span>
                    <span className="compare-score-note">{candidate.source_only_kpis?.length || 0} only in this report</span>
                  </div>
                </div>

                {/* KPI List */}
                {(candidate.shared_kpis?.length > 0 || candidate.source_only_kpis?.length > 0) && (
                  <div className="compare-section">
                    <h3 className="compare-section-title">KPIs in This Report</h3>
                    <div className="compare-kpi-list">
                      {(candidate.shared_kpis || []).map((k, i) => (
                        <div key={`s-${i}`} className="compare-kpi-item shared">
                          <span>{k}</span>
                          <span className="compare-shared-badge">SHARED</span>
                        </div>
                      ))}
                      {(candidate.source_only_kpis || []).map((k, i) => (
                        <div key={`u-${i}`} className="compare-kpi-item">
                          <span>{k}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Governance Rationale */}
                {reasons.length > 0 && (
                  <div className="compare-section">
                    <h3 className="compare-section-title">Governance Rationale</h3>
                    <div className="compare-rationale-list">
                      {reasons.map((r, i) => (
                        <div key={i} className="compare-rationale-item">
                          <span className="compare-rationale-icon" style={{ color: roleConfig.color }}>
                            {candidate.type === 'merge' ? <AlertTriangle size={12} /> : <CheckCircle size={12} />}
                          </span>
                          <span>{r}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}

          {/* Target Column (pinned right) */}
          <div className="compare-col compare-col-pinned">
            <div className="compare-col-header" style={{ borderColor: 'var(--accent-emerald)' }}>
              <span className="compare-col-label" style={{ color: 'var(--accent-emerald)' }}>
                <Target size={12} style={{ marginRight: 4 }} /> Recommended Target
              </span>
              <h2 className="compare-col-name">{target_rec?.workbook_name || '—'}</h2>
              <span className="compare-col-vs">
                {target_kpis?.length || 0} KPIs · {target_rec?.ds_sources_count || 0} Data Sources
              </span>
            </div>

            <div className="compare-score-cards">
              <div className="compare-score-item">
                <span className="compare-score-label">Total KPIs</span>
                <span className="compare-score-value" style={{ color: 'var(--accent-emerald)' }}>
                  {target_kpis?.length || 0}
                </span>
                <span className="compare-score-note">Canonical KPI count</span>
              </div>
              <div className="compare-score-item">
                <span className="compare-score-label">Data Sources</span>
                <span className="compare-score-value" style={{ color: 'var(--accent-emerald)' }}>
                  {target_rec?.ds_sources_count || 0}
                </span>
                <span className="compare-score-note">Total connected sources</span>
              </div>
              <div className="compare-score-item">
                <span className="compare-score-label">Status</span>
                <span className="compare-score-value" style={{ color: 'var(--accent-emerald)' }}>
                  Keep
                </span>
                <span className="compare-score-note">Active reference report</span>
              </div>
            </div>

            {/* Target KPI List */}
            {target_kpis && target_kpis.length > 0 && (
              <div className="compare-section">
                <h3 className="compare-section-title">Target KPIs</h3>
                <div className="compare-kpi-list">
                  {target_kpis.map((k, i) => (
                    <div key={`t-${i}`} className="compare-kpi-item target-kpi">
                      <span>{k}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Target Rationale */}
            {target_reasons && target_reasons.length > 0 && (
              <div className="compare-section">
                <h3 className="compare-section-title">Target Rationale</h3>
                <div className="compare-rationale-list">
                  {target_reasons.map((r, i) => (
                    <div key={i} className="compare-rationale-item">
                      <span className="compare-rationale-icon" style={{ color: 'var(--accent-emerald)' }}>
                        <CheckCircle size={12} />
                      </span>
                      <span>{r}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Graph Section — Combined Lineage */}
      <div className="multi-compare-graph-section">
        <div className="multi-compare-graph-header">
          <TrendingUp size={18} style={{ color: 'var(--accent-blue)' }} />
          <span>Report Connections Lineage</span>
        </div>
        <div className="multi-compare-graph-body">
          <KPIDashboardGraph
            view="rationalization"
            workbookIds={graphWorkbookIds}
            height="550px"
            legendExcludeGroups={['Report', 'KPI']}
            hideSharedSources={true}
          />
        </div>
      </div>
    </div>
  );
}
