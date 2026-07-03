import { useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, GitMerge, Trash2, CheckCircle, TrendingUp, Sparkles,
} from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Loader } from '../components/shared';
import { KPIDashboardGraph } from '../components/shared/KPIDashboardGraph';



function cleanReasons(reasons) {
  return (reasons || []).filter(r => {
    const lower = r.toLowerCase();
    return !lower.includes('fingerprint')
      && !lower.includes('retained workbook')
      && !lower.includes('retained over');
  });
}

function getWorkbookKpis(wId, fields, clusters) {
  if (!fields || !clusters) return [];
  
  // Build a case-insensitive canonical name lookup map
  const canonMap = {};
  clusters.forEach(c => {
    if (c.original_names) {
      c.original_names.forEach(orig => {
        canonMap[orig.toLowerCase()] = c.canonical_name;
      });
    }
  });

  const wbFields = fields.filter(
    cf => cf.workbook_id === wId &&
    (cf.column_type === 'formula_based' || cf.column_type === 'pivot_value' || cf.column_type === 'total')
  );

  // Use a Map keyed by lowercase canonical name to deduplicate case-insensitively
  const kpiMap = new Map();
  wbFields.forEach(cf => {
    const origLower = cf.name.toLowerCase();
    const canonName = canonMap[origLower] || cf.name;
    const dedupeKey = canonName.toLowerCase();
    if (!kpiMap.has(dedupeKey)) {
      kpiMap.set(dedupeKey, canonName);
    }
  });

  return Array.from(kpiMap.values());
}

export default function RationalizationDetailView() {
  const { type, id } = useParams();
  const navigate = useNavigate();
  const workbookId = parseInt(id, 10);

  const { data: recs, loading: recsLoading } = useApi(api.getRecommendations);
  const { data: allCalculatedFields, loading: fieldsLoading } = useApi(api.getCalculatedFields);
  const { data: allClusters, loading: clustersLoading } = useApi(api.getKpiClusters);

  const loading = recsLoading || fieldsLoading || clustersLoading;

  const rec = useMemo(() => {
    if (!recs) return null;
    return recs.find(r => (r.workbook_id || r.id) === workbookId);
  }, [recs, workbookId]);

  const target = useMemo(() => {
    if (!rec || !recs) return null;
    return recs.find(r => r.workbook_name === rec.merge_with_name)
      || recs.find(r => r.workbook_id === rec.merge_with_id);
  }, [rec, recs]);

  const graphWorkbookIds = useMemo(() => {
    const ids = [workbookId];
    if (rec && rec.merge_with_id) ids.push(rec.merge_with_id);
    return ids;
  }, [workbookId, rec]);

  const sourceKpis = useMemo(() => {
    return getWorkbookKpis(workbookId, allCalculatedFields, allClusters);
  }, [workbookId, allCalculatedFields, allClusters]);

  const targetKpis = useMemo(() => {
    if (!rec || !rec.merge_with_id) return [];
    return getWorkbookKpis(rec.merge_with_id, allCalculatedFields, allClusters);
  }, [rec, allCalculatedFields, allClusters]);

  const { sharedKpis, sourceOnlyKpis, targetOnlyKpis } = useMemo(() => {
    const sourceKpiSet = new Set(sourceKpis);
    const targetKpiSet = new Set(targetKpis);

    const shared = sourceKpis.filter(k => targetKpiSet.has(k));
    shared.sort((a, b) => a.localeCompare(b));

    const sourceOnly = sourceKpis.filter(k => !targetKpiSet.has(k));
    sourceOnly.sort((a, b) => a.localeCompare(b));

    const targetOnly = targetKpis.filter(k => !sourceKpiSet.has(k));
    targetOnly.sort((a, b) => a.localeCompare(b));

    return {
      sharedKpis: shared,
      sourceOnlyKpis: sourceOnly,
      targetOnlyKpis: targetOnly,
    };
  }, [sourceKpis, targetKpis]);

  if (loading) return <Loader />;

  if (!rec) {
    return (
      <div className="page-enter review-detail-page">
        <button className="review-detail-back" onClick={() => navigate('/rationalization')}>
          <ArrowLeft size={16} /> Back to Rationalization
        </button>
        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
          <p style={{ color: 'var(--text-muted)' }}>Report recommendation not found.</p>
        </div>
      </div>
    );
  }

  const reasons = cleanReasons(rec.reasons);

  // Per-workbook containment scores: what % of THIS workbook's KPIs exist in the other
  const sourceTotalKpis = sourceKpis.length;
  const targetTotalKpis = targetKpis.length;
  const sharedCount = sharedKpis.length;

  // Source coverage: what % of source's KPIs are covered by target
  const sourceKpiCoverage = sourceTotalKpis > 0
    ? Math.round((sharedCount / sourceTotalKpis) * 100) : 0;
  // Target coverage: what % of target's KPIs are covered by source
  const targetKpiCoverage = targetTotalKpis > 0
    ? Math.round((sharedCount / targetTotalKpis) * 100) : 0;
  // Source uniqueness: what % of source's KPIs are unique to it
  const sourceUniquePct = sourceTotalKpis > 0
    ? Math.round((sourceOnlyKpis.length / sourceTotalKpis) * 100) : 0;
  // Target uniqueness: what % of target's KPIs are unique to it
  const targetUniquePct = targetTotalKpis > 0
    ? Math.round((targetOnlyKpis.length / targetTotalKpis) * 100) : 0;

  // DS containment calculations:
  const sourceDsCount = rec.ds_sources_count || 0;
  const targetDsCount = target ? (target.ds_sources_count || 0) : 0;
  const sharedDsCount = rec.ds_shared_count || (rec.common_datasources ? rec.common_datasources.length : 0);

  const sourceDsCoverage = sourceDsCount > 0
    ? Math.round((sharedDsCount / sourceDsCount) * 100)
    : Math.round((rec.datasource_overlap_score || 0) * 100);

  const targetDsCoverage = targetDsCount > 0
    ? Math.round((sharedDsCount / targetDsCount) * 100)
    : Math.round((target?.datasource_overlap_score || rec.datasource_overlap_score || 0) * 100);



  const typeConfig = {
    merge: {
      icon: GitMerge,
      title: 'Merge Review',
      subtitle: 'Compare metrics, data sources, and KPIs side-by-side to review merging these reports.',
      color: 'var(--accent-amber)',
      iconClass: 'merge',
    },
    decommission: {
      icon: Trash2,
      title: 'Decommission Governance Review',
      subtitle: 'Review KPIs, governance rationale, and lineage connections before decommissioning.',
      color: 'var(--accent-rose)',
      iconClass: 'decommission',
    },
    keep: {
      icon: CheckCircle,
      title: 'Keep Review',
      subtitle: 'Review KPIs, data sources, and governance status of this certified report.',
      color: 'var(--accent-emerald)',
      iconClass: 'keep',
    },
  };

  const config = typeConfig[type] || typeConfig.keep;
  const IconComponent = config.icon;

  return (
    <div className="page-enter review-detail-page">
      {/* Back Button */}
      <button className="review-detail-back" onClick={() => navigate('/rationalization')}>
        <ArrowLeft size={16} /> Back to Rationalization
      </button>

      {/* Header */}
      <div className="review-detail-header">
        <div className="review-detail-header-left">
          <div className={`review-detail-icon ${config.iconClass}`}>
            <IconComponent size={24} />
          </div>
          <div>
            <h1 className="review-detail-title">{config.title}</h1>
            <p className="review-detail-subtitle">{config.subtitle}</p>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="review-detail-content">
        {/* Comparison Section */}
        <div className="review-detail-comparison">
          {/* Source Column */}
          <div className="review-detail-col">
            <div className="review-detail-col-header" style={{ borderColor: config.color }}>
              <span className="review-detail-col-label" style={{ color: config.color }}>
                {type === 'merge' ? 'Source — Merge Candidate' :
                 type === 'decommission' ? 'Decommission Candidate' :
                 'Certified Report'}
              </span>
              <h2 className="review-detail-col-name">{rec.workbook_name}</h2>
            </div>

            {/* Scores — per-workbook containment */}
            <div className="review-detail-section">
              <h3 className="review-detail-section-title">
                Compared with {rec.merge_with_name ? `"${rec.merge_with_name}"` : 'Other Report'}
              </h3>
              <div className="review-detail-scores">
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">KPIs Covered</span>
                  <span className="review-detail-score-value" style={{ color:
                    type === 'merge'
                      ? (sourceKpiCoverage >= 70 ? 'var(--accent-emerald)' : sourceKpiCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                      : (sourceKpiCoverage >= 90 ? 'var(--accent-rose)' : sourceKpiCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                  }}>
                    {sourceKpiCoverage}%
                  </span>
                  <span className="review-detail-score-note">{sharedCount} of {sourceTotalKpis} KPIs</span>
                </div>
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">DS Columns Covered</span>
                  <span className="review-detail-score-value" style={{ color:
                    type === 'merge'
                      ? (sourceDsCoverage >= 70 ? 'var(--accent-emerald)' : sourceDsCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                      : (sourceDsCoverage >= 90 ? 'var(--accent-rose)' : sourceDsCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                  }}>
                    {sourceDsCoverage}%
                  </span>
                  <span className="review-detail-score-note">{sharedDsCount} of {sourceDsCount || '?'} columns</span>
                </div>
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">Unique KPIs</span>
                  <span className="review-detail-score-value" style={{ color:
                    sourceUniquePct > 0
                      ? (type === 'merge' ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                      : 'var(--text-muted)'
                  }}>
                    {sourceUniquePct}%
                  </span>
                  <span className="review-detail-score-note">{sourceOnlyKpis.length} only in this report</span>
                </div>
              </div>
            </div>

            {/* KPIs */}
            {(sharedKpis.length > 0 || sourceOnlyKpis.length > 0) && (
              <div className="review-detail-section">
                <h3 className="review-detail-section-title">
                  {type === 'merge' ? 'Shared KPIs' : 'KPIs in This Report'}
                </h3>
                <div className="review-detail-kpi-list">
                  {sharedKpis.map((k, i) => (
                    <div key={`shared-${i}`} className="review-detail-kpi-item shared">
                      <span>{k}</span>
                      <span className="review-detail-shared-badge">SHARED</span>
                    </div>
                  ))}
                  {sourceOnlyKpis.map((k, i) => (
                    <div key={`source-${i}`} className="review-detail-kpi-item">
                      <span>{k}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Rationale (for non-decommission actions) */}
            {type !== 'decommission' && reasons.length > 0 && (
              <div className="review-detail-section">
                <h3 className="review-detail-section-title">Governance Rationale</h3>
                <div className="review-detail-rationale">
                  {reasons.map((r, i) => (
                    <div key={i} className="review-detail-rationale-item">
                      <span className="review-detail-rationale-icon" style={{ color: config.color }}>
                        {type === 'merge' ? '!' : '✓'}
                      </span>
                      <span>{r}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* AI Justification (for non-decommission actions) */}
            {type !== 'decommission' && rec.llm_justification && (
              <div className="review-detail-ai">
                <Sparkles size={14} style={{ flexShrink: 0 }} />
                <span>{rec.llm_justification}</span>
              </div>
            )}
          </div>

          {/* Target Column (for merge OR decommission with a retain target) */}
          {(type === 'merge' || (type === 'decommission' && rec.merge_with_name)) && (
            <div className="review-detail-col">
              <div className="review-detail-col-header" style={{ borderColor: 'var(--accent-emerald)' }}>
                <span className="review-detail-col-label" style={{ color: 'var(--accent-emerald)' }}>
                  {type === 'merge' ? 'Target — Consolidation Destination' : 'Retain Target — Destination'}
                </span>
                <h2 className="review-detail-col-name">{rec.merge_with_name || '—'}</h2>
              </div>

              {target && (
                <>
                  <div className="review-detail-section">
                    <h3 className="review-detail-section-title">
                      Compared with "{rec.workbook_name}"
                    </h3>
                    <div className="review-detail-scores">
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">KPIs Covered</span>
                        <span className="review-detail-score-value" style={{ color:
                          type === 'merge'
                            ? (targetKpiCoverage >= 70 ? 'var(--accent-emerald)' : targetKpiCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                            : (targetKpiCoverage >= 90 ? 'var(--accent-rose)' : targetKpiCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                        }}>
                          {targetKpiCoverage}%
                        </span>
                        <span className="review-detail-score-note">{sharedCount} of {targetTotalKpis} KPIs</span>
                      </div>
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">DS Columns Covered</span>
                        <span className="review-detail-score-value" style={{ color:
                          type === 'merge'
                            ? (targetDsCoverage >= 70 ? 'var(--accent-emerald)' : targetDsCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                            : (targetDsCoverage >= 90 ? 'var(--accent-rose)' : targetDsCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                        }}>
                          {targetDsCoverage}%
                        </span>
                        <span className="review-detail-score-note">{sharedDsCount} of {targetDsCount || '?'} columns</span>
                      </div>
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">Unique KPIs</span>
                        <span className="review-detail-score-value" style={{ color:
                          targetUniquePct > 0
                            ? (type === 'merge' ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                            : 'var(--text-muted)'
                        }}>
                          {targetUniquePct}%
                        </span>
                        <span className="review-detail-score-note">{targetOnlyKpis.length} only in this report</span>
                      </div>
                    </div>
                  </div>

                  {(sharedKpis.length > 0 || targetOnlyKpis.length > 0) && (
                    <div className="review-detail-section">
                      <h3 className="review-detail-section-title">Its KPIs</h3>
                      <div className="review-detail-kpi-list">
                        {sharedKpis.map((k, i) => (
                          <div key={`target-shared-${i}`} className="review-detail-kpi-item shared">
                            <span>{k}</span>
                            <span className="review-detail-shared-badge">SHARED</span>
                          </div>
                        ))}
                        {targetOnlyKpis.map((k, i) => (
                          <div key={`target-only-${i}`} className="review-detail-kpi-item">
                            <span>{k}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {cleanReasons(target.reasons).length > 0 && (
                    <div className="review-detail-section">
                      <h3 className="review-detail-section-title">Target Rationale</h3>
                      <div className="review-detail-rationale">
                        {cleanReasons(target.reasons).map((r, i) => (
                          <div key={i} className="review-detail-rationale-item">
                            <span className="review-detail-rationale-icon" style={{ color: 'var(--accent-emerald)' }}>✓</span>
                            <span>{r}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {!target && (
                <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                  Target report details not available in current recommendations.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Decommission Rationale at the bottom/end */}
        {type === 'decommission' && (
          <div className="review-detail-decommission-footer-section" style={{ marginTop: 24, padding: 20, background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)', borderLeft: '4px solid var(--accent-rose)' }}>
            <h3 style={{ margin: '0 0 12px 0', display: 'flex', alignItems: 'center', gap: 8, color: 'var(--accent-rose)' }}>
              <Trash2 size={18} />
              Decommission Governance & Cleanliness Rationale
            </h3>
            
            {rec.llm_justification && (
              <div className="review-detail-ai" style={{ marginBottom: 16 }}>
                <Sparkles size={14} style={{ flexShrink: 0 }} />
                <span>{rec.llm_justification}</span>
              </div>
            )}

            {reasons.length > 0 && (
              <div className="review-detail-section" style={{ marginBottom: 16 }}>
                <h4 className="review-detail-section-title" style={{ fontSize: '0.85rem', color: 'var(--text-primary)', marginBottom: 8 }}>Platform Cleanliness Violations</h4>
                <div className="review-detail-rationale">
                  {reasons.map((r, i) => (
                    <div key={i} className="review-detail-rationale-item">
                      <span className="review-detail-rationale-icon" style={{ color: 'var(--accent-rose)' }}>▲</span>
                      <span>{r}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="review-detail-impact" style={{ margin: 0, padding: 12, background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: 'var(--radius-sm)', fontSize: '0.85rem', color: 'var(--accent-rose)' }}>
              <strong>Governance Impact Alert:</strong> This action will archive the report metadata,
              disconnect datasource references, and flag it in the repository index for cleanup.
            </div>
          </div>
        )}

        {/* Graph Section with Legend */}
        <div className="review-detail-graph-section">
          <div className="review-detail-graph-header">
            <div className="review-detail-graph-title" style={{ color: config.color }}>
              <TrendingUp size={18} />
              <span>{type === 'merge' ? 'Visual Lineage & Common Connections' : 'Report Connections Lineage'}</span>
            </div>
          </div>

          <div className="review-detail-graph-body">
            {/* Graph */}
            <div className="review-detail-graph-wrapper" style={{ width: '100%' }}>
              <KPIDashboardGraph
                view={type === 'keep' || !rec.merge_with_id ? 'landscape' : 'rationalization'}
                workbookId={type === 'keep' || !rec.merge_with_id ? workbookId : undefined}
                workbookIds={type === 'keep' || !rec.merge_with_id ? undefined : graphWorkbookIds}
                height="550px"
                legendExcludeGroups={['Report', 'KPI']}
                hideSharedSources={true}
              />
            </div>
          </div>
        </div>

        {/* Action Footer removed */}
      </div>
    </div>
  );
}
