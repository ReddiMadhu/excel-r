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

export default function RationalizationDetailView() {
  const { type, id } = useParams();
  const navigate = useNavigate();
  const workbookId = parseInt(id, 10);

  const { data: recs, loading } = useApi(api.getRecommendations);

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
  const commonKpis = new Set(rec.common_kpis || []);
  const kpiPct = ((rec.kpi_overlap_score || 0) * 100).toFixed(0);
  const dsPct = ((rec.datasource_overlap_score || 0) * 100).toFixed(0);
  const uniqPct = ((rec.uniqueness_score || 0) * 100).toFixed(0);

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

            {/* Scores */}
            <div className="review-detail-section">
              <h3 className="review-detail-section-title">Overlap Scores</h3>
              <div className="review-detail-scores">
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">KPI Overlap</span>
                  <span className="review-detail-score-value" style={{ color: config.color }}>{kpiPct}%</span>
                </div>
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">DS Overlap</span>
                  <span className="review-detail-score-value" style={{ color: config.color }}>{dsPct}%</span>
                </div>
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">Uniqueness</span>
                  <span className="review-detail-score-value">{uniqPct}%</span>
                </div>
              </div>
            </div>

            {/* KPIs */}
            {rec.common_kpis && rec.common_kpis.length > 0 && (
              <div className="review-detail-section">
                <h3 className="review-detail-section-title">
                  {type === 'merge' ? 'Shared KPIs' : 'KPIs in This Report'}
                </h3>
                <div className="review-detail-kpi-list">
                  {rec.common_kpis.map((k, i) => (
                    <div key={i} className="review-detail-kpi-item shared">
                      <span>{k}</span>
                      {type === 'merge' && (
                        <span className="review-detail-shared-badge">SHARED</span>
                      )}
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
                    <h3 className="review-detail-section-title">Overlap Scores</h3>
                    <div className="review-detail-scores">
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">KPI</span>
                        <span className="review-detail-score-value" style={{ color: 'var(--accent-emerald)' }}>
                          {((target.kpi_overlap_score || 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">DS</span>
                        <span className="review-detail-score-value" style={{ color: 'var(--accent-emerald)' }}>
                          {((target.datasource_overlap_score || 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">Unique</span>
                        <span className="review-detail-score-value">
                          {((target.uniqueness_score || 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  </div>

                  {type !== 'decommission' && target.common_kpis && target.common_kpis.length > 0 && (
                    <div className="review-detail-section">
                      <h3 className="review-detail-section-title">Its KPIs</h3>
                      <div className="review-detail-kpi-list">
                        {target.common_kpis.map((k, i) => {
                          const isShared = commonKpis.has(k);
                          return (
                            <div key={i} className={`review-detail-kpi-item ${isShared ? 'shared' : ''}`}>
                              <span>{k}</span>
                              {isShared && (
                                <span className="review-detail-shared-badge">SHARED</span>
                              )}
                            </div>
                          );
                        })}
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
              />
            </div>
          </div>
        </div>

        {/* Action Footer */}
        <div className="review-detail-footer">
          <div className="review-detail-footer-info" style={{ color: config.color }}>
            <TrendingUp size={14} />
            {type === 'merge' && 'Merging reduces redundant report maintenance'}
            {type === 'keep' && 'This report is certified and actively maintained'}
          </div>
          <div className="review-detail-footer-actions">
            <button className="btn-cancel" onClick={() => navigate('/rationalization')}>
              Back
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
