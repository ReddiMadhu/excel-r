import { useState, useMemo } from 'react';
import {
  CheckCircle, GitMerge, Trash2, AlertCircle, Search,
  ChevronRight, X, ArrowRight, TrendingUp, Sparkles,
} from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { StatCard, Loader, EmptyState } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';
import { KPIDashboardGraph } from '../components/shared/KPIDashboardGraph';

export default function RationalizationView() {
  const { data: recs, loading } = useApi(api.getRecommendations);
  const { data: pairwise, loading: pwLoading } = useApi(api.getPairwiseMatrix);

  // Filter state
  const [activeTab, setActiveTab] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedWorkbook, setSelectedWorkbook] = useState('all');

  // Modal state
  const [mergeModalItem, setMergeModalItem] = useState(null);
  const [decommissionModalItem, setDecommissionModalItem] = useState(null);

  // Heatmap collapse
  const [heatmapOpen, setHeatmapOpen] = useState(false);

  // ── Derived data ──────────────────────────────────────────
  const counts = useMemo(() => {
    if (!recs) return { keep: 0, merge: 0, decommission: 0, review: 0 };
    return {
      keep: recs.filter(r => r.action === 'keep').length,
      merge: recs.filter(r => r.action === 'merge').length,
      decommission: recs.filter(r => r.action === 'decommission' || r.action === 'delete').length,
      review: recs.filter(r => r.action === 'review').length,
    };
  }, [recs]);

  const workbookNames = useMemo(() => {
    if (!recs) return [];
    const names = new Set(recs.map(r => r.workbook_name).filter(Boolean));
    return Array.from(names).sort();
  }, [recs]);

  const workbookIds = useMemo(
    () => (pairwise?.workbooks || []).map(w => w.id),
    [pairwise]
  );

  // Decommission pairs logic
  const decommissionRecs = useMemo(
    () => (recs || []).filter(r => r.action === 'decommission' || r.action === 'delete'),
    [recs]
  );

  const retainTargetIds = useMemo(
    () => new Set(decommissionRecs.map(r => r.merge_with_id).filter(Boolean)),
    [decommissionRecs]
  );

  // ── Filtering logic ───────────────────────────────────────
  const filterRec = (rec) => {
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      const nameMatch = (rec.workbook_name || '').toLowerCase().includes(q);
      const mergeMatch = (rec.merge_with_name || '').toLowerCase().includes(q);
      if (!nameMatch && !mergeMatch) return false;
    }
    if (selectedWorkbook !== 'all' && rec.workbook_name !== selectedWorkbook) return false;
    return true;
  };

  const mergeRecs = useMemo(
    () => (recs || []).filter(r => r.action === 'merge').filter(filterRec),
    [recs, searchTerm, selectedWorkbook]
  );

  const decommissionFiltered = useMemo(() => {
    const pairs = [];
    const retainTargets = new Set(decommissionRecs.map(r => r.merge_with_id).filter(Boolean));
    const filtered = decommissionRecs.filter(rec => {
      if (!filterRec(rec)) return false;
      if (!rec.merge_with_id) return true;
      if (retainTargets.has(rec.workbook_id)) return false;
      return true;
    });
    const pairMap = new Map();
    for (const rec of filtered) {
      if (rec.merge_with_id) {
        const key = [rec.workbook_id, rec.merge_with_id].sort((a, b) => a - b).join('-');
        if (!pairMap.has(key)) pairMap.set(key, rec);
      } else {
        pairs.push(rec);
      }
    }
    return [...pairMap.values(), ...pairs];
  }, [decommissionRecs, searchTerm, selectedWorkbook]);

  const keepRecs = useMemo(
    () => (recs || []).filter(r => {
      if (r.action !== 'keep') return false;
      return filterRec(r);
    }),
    [recs, searchTerm, selectedWorkbook]
  );

  const reviewRecs = useMemo(
    () => (recs || []).filter(r => r.action === 'review').filter(filterRec),
    [recs, searchTerm, selectedWorkbook]
  );

  // Find matching merge target for modal
  const mergeTarget = useMemo(() => {
    if (!mergeModalItem || !recs) return null;
    return recs.find(r => r.workbook_name === mergeModalItem.merge_with_name)
      || recs.find(r => r.workbook_id === mergeModalItem.merge_with_id);
  }, [mergeModalItem, recs]);

  if (loading) return <Loader />;

  const totalFiltered = mergeRecs.length + decommissionFiltered.length + keepRecs.length + reviewRecs.length;

  return (
    <div className="page-enter">
      <PageHeader title="Rationalization Results" />



      {(!recs || recs.length === 0) ? (
        <EmptyState
          icon={GitMerge}
          title="No recommendations yet"
          message="Upload multiple workbooks and the rationalization engine will produce recommendations."
        />
      ) : (
        <div>
          {/* ── Filter Toolbar ──────────────────────────────── */}
          <div className="ration-toolbar">
            <div className="ration-search">
              <Search />
              <input
                type="text"
                placeholder="Search workbook or dashboard..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>

            <select
              className="ration-workbook-select"
              value={selectedWorkbook}
              onChange={(e) => setSelectedWorkbook(e.target.value)}
            >
              <option value="all">All Workbooks</option>
              {workbookNames.map((wb, i) => (
                <option key={i} value={wb}>{wb}</option>
              ))}
            </select>

            <div className="ration-pills">
              <PillButton
                label="All"
                count={totalFiltered}
                active={activeTab === 'all'}
                activeClass="active-all"
                onClick={() => setActiveTab('all')}
              />
              <PillButton
                label="Merge"
                count={mergeRecs.length}
                color="var(--accent-amber)"
                active={activeTab === 'merge'}
                activeClass="active-merge"
                onClick={() => setActiveTab('merge')}
              />
              <PillButton
                label="Decommission"
                count={decommissionFiltered.length}
                color="var(--accent-rose)"
                active={activeTab === 'decommission'}
                activeClass="active-decommission"
                onClick={() => setActiveTab('decommission')}
              />
              <PillButton
                label="Keep"
                count={keepRecs.length}
                color="var(--accent-emerald)"
                active={activeTab === 'keep'}
                activeClass="active-keep"
                onClick={() => setActiveTab('keep')}
              />
              {counts.review > 0 && (
                <PillButton
                  label="Review"
                  count={reviewRecs.length}
                  color="#3b82f6"
                  active={activeTab === 'review'}
                  activeClass="active-review"
                  onClick={() => setActiveTab('review')}
                />
              )}
            </div>
          </div>

          {/* ── Relationship Graph ──────────────────────────── */}
          {workbookIds.length > 1 && (
            <div className="card compact-card" style={{ marginBottom: 12 }}>
              <KPIDashboardGraph
                view="rationalization"
                workbookIds={workbookIds}
                height="520px"
                filterAction={activeTab !== 'all' ? activeTab : null}
                title="Workbook Relationship Map"
              />
            </div>
          )}

          {/* ── Recommendation Cards Grid ──────────────────── */}
          {activeTab === 'all' ? (
            <div className="ration-grid">
              {/* Merge Column */}
              <div className="ration-column">
                <ColumnHeader
                  label="CONSOLIDATE & MERGE"
                  color="var(--accent-amber)"
                  count={mergeRecs.length}
                  badge="merge"
                  badgeText="Redundant"
                />
                {mergeRecs.length > 0 ? mergeRecs.map(rec => (
                  <RecCard key={rec.id} rec={rec} type="merge" onReview={() => setMergeModalItem(rec)} />
                )) : <div className="ration-empty">No merge recommendations</div>}
              </div>

              {/* Decommission Column */}
              <div className="ration-column">
                <ColumnHeader
                  label="DECOMMISSION"
                  color="var(--accent-rose)"
                  count={decommissionFiltered.length}
                  badge="decommission"
                  badgeText="Inactive"
                />
                {decommissionFiltered.length > 0 ? decommissionFiltered.map(rec => (
                  <RecCard key={rec.id} rec={rec} type="decommission" onReview={() => setDecommissionModalItem(rec)} />
                )) : <div className="ration-empty">No decommission recommendations</div>}
              </div>

              {/* Keep Column */}
              <div className="ration-column">
                <ColumnHeader
                  label="KEEP & CERTIFY"
                  color="var(--accent-emerald)"
                  count={keepRecs.length}
                  badge="keep"
                  badgeText="Active"
                />
                {keepRecs.length > 0 ? keepRecs.map(rec => (
                  <RecCard key={rec.id} rec={rec} type="keep" />
                )) : <div className="ration-empty">No keep recommendations</div>}
              </div>
            </div>
          ) : (
            <div className="ration-grid single-col">
              {activeTab === 'merge' && (
                <div className="ration-column">
                  <ColumnHeader label="CONSOLIDATE & MERGE" color="var(--accent-amber)" count={mergeRecs.length} badge="merge" badgeText="Redundant" />
                  {mergeRecs.length > 0 ? mergeRecs.map(rec => (
                    <RecCard key={rec.id} rec={rec} type="merge" onReview={() => setMergeModalItem(rec)} />
                  )) : <div className="ration-empty">No merge recommendations</div>}
                </div>
              )}
              {activeTab === 'decommission' && (
                <div className="ration-column">
                  <ColumnHeader label="DECOMMISSION" color="var(--accent-rose)" count={decommissionFiltered.length} badge="decommission" badgeText="Inactive" />
                  {decommissionFiltered.length > 0 ? decommissionFiltered.map(rec => (
                    <RecCard key={rec.id} rec={rec} type="decommission" onReview={() => setDecommissionModalItem(rec)} />
                  )) : <div className="ration-empty">No decommission recommendations</div>}
                </div>
              )}
              {activeTab === 'keep' && (
                <div className="ration-column">
                  <ColumnHeader label="KEEP & CERTIFY" color="var(--accent-emerald)" count={keepRecs.length} badge="keep" badgeText="Active" />
                  {keepRecs.length > 0 ? keepRecs.map(rec => (
                    <RecCard key={rec.id} rec={rec} type="keep" />
                  )) : <div className="ration-empty">No keep recommendations</div>}
                </div>
              )}
              {activeTab === 'review' && (
                <div className="ration-column">
                  <ColumnHeader label="REVIEW" color="#3b82f6" count={reviewRecs.length} badge="review" badgeText="Needs Attention" />
                  {reviewRecs.length > 0 ? reviewRecs.map(rec => (
                    <RecCard key={rec.id} rec={rec} type="review" />
                  )) : <div className="ration-empty">No review recommendations</div>}
                </div>
              )}
            </div>
          )}

          {/* ── Collapsible Advanced Analytics (Heatmap) ──── */}
          {pairwise && pairwise.workbooks?.length > 1 && (
            <div style={{ marginBottom: 24 }}>
              <button
                className="advanced-analytics-toggle"
                onClick={() => setHeatmapOpen(!heatmapOpen)}
              >
                <ChevronRight className={`toggle-chevron ${heatmapOpen ? 'open' : ''}`} />
                Advanced Analytics
                <span className="toggle-badge">KPI Overlap Matrix</span>
              </button>
              <div className={`advanced-analytics-content ${heatmapOpen ? 'open' : ''}`}>
                <div className="advanced-analytics-inner">
                  <div className="card">
                    <h3 style={{ marginBottom: 16 }}>KPI Overlap Matrix</h3>
                    {pwLoading ? <Loader /> : (
                      <OverlapHeatmap
                        workbooks={pairwise.workbooks}
                        pairs={pairwise.pairs}
                      />
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Merge Review Modal ──────────────────────────────── */}
      {mergeModalItem && (
        <MergeReviewModal
          rec={mergeModalItem}
          target={mergeTarget}
          onClose={() => setMergeModalItem(null)}
        />
      )}

      {/* ── Decommission Review Modal ──────────────────────── */}
      {decommissionModalItem && (
        <DecommissionReviewModal
          rec={decommissionModalItem}
          onClose={() => setDecommissionModalItem(null)}
        />
      )}
    </div>
  );
}

/* ═════════════════════════════════════════════════════════════
   Sub-Components
   ═════════════════════════════════════════════════════════════ */

function PillButton({ label, count, color, active, activeClass, onClick }) {
  return (
    <button
      className={`ration-pill ${active ? activeClass : ''}`}
      onClick={onClick}
    >
      {color && <span className="pill-dot" style={{ background: color }} />}
      {label}
      <span className="pill-count">{count}</span>
    </button>
  );
}

function ColumnHeader({ label, color, count, badge, badgeText }) {
  return (
    <div className="ration-col-header">
      <div className="ration-col-title" style={{ color }}>
        <span className="col-dot" style={{ background: color }} />
        {label}
      </div>
      <span className={`ration-col-badge ${badge}`}>
        {count} {badgeText}
      </span>
    </div>
  );
}

function cleanReasons(reasons) {
  return (reasons || []).filter(r => {
    const lower = r.toLowerCase();
    return !lower.includes('fingerprint')
      && !lower.includes('retained workbook')
      && !lower.includes('retained over');
  });
}

function scoreColor(pct, inverse) {
  if (inverse) {
    return pct >= 60 ? 'var(--accent-emerald)' : pct >= 30 ? 'var(--accent-amber)' : 'var(--accent-rose)';
  }
  return pct >= 70 ? 'var(--accent-rose)' : pct >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)';
}

function RecCard({ rec, type, onReview }) {
  const reasons = cleanReasons(rec.reasons);
  const kpiPct = ((rec.kpi_overlap_score || 0) * 100).toFixed(0);
  const dsPct = ((rec.datasource_overlap_score || 0) * 100).toFixed(0);
  const uniqPct = ((rec.uniqueness_score || 0) * 100).toFixed(0);

  const rationaleIcons = {
    merge: { icon: '!', color: 'var(--accent-amber)' },
    decommission: { icon: '▲', color: 'var(--accent-rose)' },
    keep: { icon: '✓', color: 'var(--accent-emerald)' },
    review: { icon: '?', color: '#3b82f6' },
  };
  const ri = rationaleIcons[type] || rationaleIcons.keep;

  return (
    <div className={`rec-card ${type}`}>
      {/* Header */}
      <div className="rec-card-top">
        <div>
          <div className="rec-card-name">{rec.workbook_name}</div>
          {rec.llm_override && <span className="badge badge-purple" style={{ marginTop: 4, display: 'inline-block' }}>AI Override</span>}
        </div>
        <span className={`rec-card-uniqueness ${type}`}>
          {uniqPct}% Unique
        </span>
      </div>

      {/* Scores */}
      <div className="rec-card-scores">
        <div className="rec-score-item">
          <span className="rec-score-label">KPI Overlap:</span>
          <span className="rec-score-value" style={{ color: scoreColor(+kpiPct, false) }}>{kpiPct}%</span>
        </div>
        <div className="rec-score-item">
          <span className="rec-score-label">DS Overlap:</span>
          <span className="rec-score-value" style={{ color: scoreColor(+dsPct, false) }}>{dsPct}%</span>
        </div>
        <div className="rec-score-item">
          <span className="rec-score-label">Uniqueness:</span>
          <span className="rec-score-value" style={{ color: scoreColor(+uniqPct, true) }}>{uniqPct}%</span>
        </div>
      </div>

      {/* Rationale */}
      {reasons.length > 0 && (
        <div className="rec-card-rationale">
          <div className="rec-card-rationale-title">Governance Rationale</div>
          <ul>
            {reasons.map((reason, i) => (
              <li key={i}>
                <span className="rationale-icon" style={{ color: ri.color }}>{ri.icon}</span>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* AI Justification */}
      {rec.llm_justification && (
        <div className="rec-card-ai">
          <Sparkles size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
          {rec.llm_justification}
        </div>
      )}

      {/* Common KPIs */}
      {rec.common_kpis && rec.common_kpis.length > 0 && (
        <div className="rec-card-kpis">
          <div className="rec-card-kpis-label">Common KPIs</div>
          <div className="rec-card-kpis-tags">
            {rec.common_kpis.map((k, i) => (
              <span key={i} className="rec-kpi-tag">{k}</span>
            ))}
          </div>
        </div>
      )}

      {/* Footer with Review Button */}
      {(type === 'merge' || type === 'decommission') && (
        <div className="rec-card-footer">
          <div className="rec-card-merge-target">
            {type === 'merge' && rec.merge_with_name && (
              <>
                <GitMerge size={13} />
                <span title={`Merge into '${rec.merge_with_name}'`}>
                  Merge into &lsquo;{rec.merge_with_name}&rsquo;
                </span>
              </>
            )}
            {type === 'decommission' && rec.merge_with_name && (
              <>
                <ArrowRight size={13} />
                <span title={`Retain '${rec.merge_with_name}'`}>
                  Retain &lsquo;{rec.merge_with_name}&rsquo;
                </span>
              </>
            )}
          </div>
          <button className={`btn-review ${type}`} onClick={onReview}>
            Review Details <ArrowRight size={13} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ── Merge Review Modal ──────────────────────────────────── */
function MergeReviewModal({ rec, target, onClose }) {
  const reasons = cleanReasons(rec.reasons);
  const commonKpis = new Set(rec.common_kpis || []);

  return (
    <div className="review-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="review-modal">
        {/* Header */}
        <div className="review-modal-header">
          <div className="review-modal-header-left">
            <div className="review-modal-icon merge">
              <GitMerge size={22} />
            </div>
            <div>
              <div className="review-modal-title">Consolidation Merger Review</div>
              <div className="review-modal-subtitle">
                Compare metrics, data sources, and KPIs side-by-side to review consolidating these workbooks.
              </div>
            </div>
          </div>
          <button className="review-modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="review-modal-body">
          {/* Side-by-side comparison */}
          <div className="review-comparison">
            {/* Source Column */}
            <div className="review-col">
              <div>
                <div className="review-col-label source">Source — Merge Candidate</div>
                <div className="review-col-name">{rec.workbook_name}</div>
              </div>

              {/* Scores */}
              <div>
                <div className="review-section-title">Overlap Scores</div>
                <div className="rec-card-scores">
                  <div className="rec-score-item">
                    <span className="rec-score-label">KPI:</span>
                    <span className="rec-score-value" style={{ color: 'var(--accent-amber)' }}>
                      {((rec.kpi_overlap_score || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="rec-score-item">
                    <span className="rec-score-label">DS:</span>
                    <span className="rec-score-value" style={{ color: 'var(--accent-amber)' }}>
                      {((rec.datasource_overlap_score || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="rec-score-item">
                    <span className="rec-score-label">Unique:</span>
                    <span className="rec-score-value">
                      {((rec.uniqueness_score || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              </div>

              {/* Common KPIs */}
              {rec.common_kpis && rec.common_kpis.length > 0 && (
                <div>
                  <div className="review-section-title">Shared KPIs</div>
                  <div className="review-kpi-list">
                    {rec.common_kpis.map((k, i) => (
                      <div key={i} className="review-kpi-item shared">
                        <span>{k}</span>
                        <span className="shared-badge" style={{
                          fontSize: '0.6rem', fontWeight: 700, padding: '1px 6px',
                          borderRadius: 100, background: 'rgba(245, 158, 11, 0.12)',
                          color: 'var(--accent-amber)'
                        }}>SHARED</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Rationale */}
              {reasons.length > 0 && (
                <div>
                  <div className="review-section-title">Governance Rationale</div>
                  <div className="review-rationale-box">
                    <ul>
                      {reasons.map((r, i) => (
                        <li key={i}>
                          <span style={{ color: 'var(--accent-amber)', fontWeight: 700 }}>!</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>

            {/* Target Column */}
            <div className="review-col">
              <div>
                <div className="review-col-label target">Target — Consolidation Destination</div>
                <div className="review-col-name">{rec.merge_with_name || '—'}</div>
              </div>

              {target && (
                <>
                  <div>
                    <div className="review-section-title">Overlap Scores</div>
                    <div className="rec-card-scores">
                      <div className="rec-score-item">
                        <span className="rec-score-label">KPI:</span>
                        <span className="rec-score-value" style={{ color: 'var(--accent-emerald)' }}>
                          {((target.kpi_overlap_score || 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="rec-score-item">
                        <span className="rec-score-label">DS:</span>
                        <span className="rec-score-value" style={{ color: 'var(--accent-emerald)' }}>
                          {((target.datasource_overlap_score || 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="rec-score-item">
                        <span className="rec-score-label">Unique:</span>
                        <span className="rec-score-value">
                          {((target.uniqueness_score || 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  </div>

                  {target.common_kpis && target.common_kpis.length > 0 && (
                    <div>
                      <div className="review-section-title">Its KPIs</div>
                      <div className="review-kpi-list">
                        {target.common_kpis.map((k, i) => {
                          const isShared = commonKpis.has(k);
                          return (
                            <div key={i} className={`review-kpi-item ${isShared ? 'shared' : ''}`}>
                              <span>{k}</span>
                              {isShared && (
                                <span className="shared-badge" style={{
                                  fontSize: '0.6rem', fontWeight: 700, padding: '1px 6px',
                                  borderRadius: 100, background: 'rgba(245, 158, 11, 0.12)',
                                  color: 'var(--accent-amber)'
                                }}>SHARED</span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {cleanReasons(target.reasons).length > 0 && (
                    <div>
                      <div className="review-section-title">Target Rationale</div>
                      <div className="review-rationale-box">
                        <ul>
                          {cleanReasons(target.reasons).map((r, i) => (
                            <li key={i}>
                              <span style={{ color: 'var(--accent-emerald)', fontWeight: 700 }}>✓</span>
                              <span>{r}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}
                </>
              )}

              {!target && (
                <div className="ration-empty" style={{ marginTop: 12 }}>
                  Target workbook details not available in current recommendations.
                </div>
              )}
            </div>
          </div>

          {/* Lineage graph */}
          {rec.workbook_id && rec.merge_with_id && (
            <div className="review-graph-section">
              <div className="review-graph-section-header">
                <div className="review-graph-section-title" style={{ color: 'var(--accent-amber)' }}>
                  <TrendingUp size={16} />
                  Visual Lineage & Common Connections
                </div>
              </div>
              <div className="review-graph-wrapper">
                <KPIDashboardGraph
                  view="rationalization"
                  workbookIds={[rec.workbook_id, rec.merge_with_id]}
                  height="340px"
                />
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="review-modal-footer">
          <div className="review-footer-info" style={{ color: 'var(--accent-amber)' }}>
            <TrendingUp size={14} />
            Consolidating reduces redundant workbook maintenance
          </div>
          <div className="review-footer-actions">
            <button className="btn-cancel" onClick={onClose}>Cancel</button>
            <button className="btn-apply merge">Apply Merger</button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Decommission Review Modal ───────────────────────────── */
function DecommissionReviewModal({ rec, onClose }) {
  const reasons = cleanReasons(rec.reasons);

  return (
    <div className="review-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="review-modal">
        {/* Header */}
        <div className="review-modal-header">
          <div className="review-modal-header-left">
            <div className="review-modal-icon decommission">
              <Trash2 size={22} />
            </div>
            <div>
              <div className="review-modal-title">Decommission Governance Review</div>
              <div className="review-modal-subtitle">
                Review KPIs, governance rationale, and lineage connections before decommissioning.
              </div>
            </div>
          </div>
          <button className="review-modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="review-modal-body">
          <div className="review-comparison">
            {/* Workbook Details */}
            <div className="review-col">
              <div>
                <div className="review-col-label decommission">Decommission Candidate</div>
                <div className="review-col-name">{rec.workbook_name}</div>
              </div>

              <div>
                <div className="review-section-title">Overlap Scores</div>
                <div className="rec-card-scores">
                  <div className="rec-score-item">
                    <span className="rec-score-label">KPI Overlap:</span>
                    <span className="rec-score-value" style={{ color: 'var(--accent-rose)' }}>
                      {((rec.kpi_overlap_score || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="rec-score-item">
                    <span className="rec-score-label">DS Overlap:</span>
                    <span className="rec-score-value" style={{ color: 'var(--accent-rose)' }}>
                      {((rec.datasource_overlap_score || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="rec-score-item">
                    <span className="rec-score-label">Uniqueness:</span>
                    <span className="rec-score-value">
                      {((rec.uniqueness_score || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              </div>

              {rec.common_kpis && rec.common_kpis.length > 0 && (
                <div>
                  <div className="review-section-title">KPIs in This Workbook</div>
                  <div className="review-kpi-list">
                    {rec.common_kpis.map((k, i) => (
                      <div key={i} className="review-kpi-item">
                        <span>{k}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {rec.merge_with_name && (
                <div style={{
                  padding: 12, borderRadius: 8,
                  background: 'var(--status-keep-bg)',
                  border: '1px solid var(--accent-emerald)',
                }}>
                  <div className="review-section-title" style={{ color: 'var(--accent-emerald)' }}>
                    Retain Target
                  </div>
                  <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                    {rec.merge_with_name}
                  </div>
                </div>
              )}
            </div>

            {/* Rationale Column */}
            <div className="review-col">
              <div>
                <div className="review-col-label rationale">Governance Rationale</div>
                <div className="review-col-name" style={{ fontSize: '0.95rem' }}>Why Decommission?</div>
              </div>

              {rec.llm_justification && (
                <div className="rec-card-ai">
                  <Sparkles size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
                  {rec.llm_justification}
                </div>
              )}

              {reasons.length > 0 && (
                <div>
                  <div className="review-section-title">Platform Cleanliness Violations</div>
                  <div className="review-rationale-box">
                    <ul>
                      {reasons.map((r, i) => (
                        <li key={i}>
                          <span style={{ color: 'var(--accent-rose)', fontWeight: 700 }}>▲</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              <div className="review-impact-alert decommission">
                <strong>Governance Impact Alert:</strong> This action will archive the workbook metadata,
                disconnect datasource references, and flag it in the repository index for cleanup.
              </div>
            </div>
          </div>

          {/* Lineage graph */}
          {rec.workbook_id && (
            <div className="review-graph-section">
              <div className="review-graph-section-header">
                <div className="review-graph-section-title" style={{ color: 'var(--accent-rose)' }}>
                  <TrendingUp size={16} />
                  Workbook Connections Lineage
                </div>
              </div>
              <div className="review-graph-wrapper">
                <KPIDashboardGraph
                  view="rationalization"
                  workbookIds={rec.merge_with_id
                    ? [rec.workbook_id, rec.merge_with_id]
                    : [rec.workbook_id]
                  }
                  height="340px"
                />
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="review-modal-footer">
          <div className="review-footer-info" style={{ color: 'var(--accent-rose)' }}>
            Archiving this workbook frees up resources and reduces portfolio clutter
          </div>
          <div className="review-footer-actions">
            <button className="btn-cancel" onClick={onClose}>Cancel</button>
            <button className="btn-apply decommission">Apply Decommission</button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Heatmap Component ───────────────────────────────────── */
function OverlapHeatmap({ workbooks, pairs }) {
  const wbNames = workbooks.map(wb =>
    wb.name.length > 20 ? wb.name.slice(0, 18) + '...' : wb.name
  );
  const n = workbooks.length;

  const overlapMap = {};
  (pairs || []).forEach(p => {
    const key = `${p.workbook_id_a}-${p.workbook_id_b}`;
    const keyR = `${p.workbook_id_b}-${p.workbook_id_a}`;
    overlapMap[key] = p.kpi_overlap;
    overlapMap[keyR] = p.kpi_overlap;
  });

  const getColor = (val) => {
    if (val >= 0.7) return 'rgba(244, 63, 94, 0.75)';
    if (val >= 0.4) return 'rgba(245, 158, 11, 0.65)';
    if (val > 0) return 'rgba(59, 130, 246, 0.4)';
    return 'var(--bg-elevated)';
  };

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: `120px repeat(${n}, 1fr)`,
      gap: 2,
      maxWidth: 600,
    }}>
      <div />
      {wbNames.map((name, i) => (
        <div key={i} className="heatmap-label" style={{
          fontSize: '0.65rem',
          textAlign: 'center',
          transform: 'rotate(-30deg)',
          transformOrigin: 'bottom left',
          height: 60,
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'center',
        }}>{name}</div>
      ))}

      {workbooks.map((wbRow, i) => (
        <div key={`row-${i}`} style={{ display: 'contents' }}>
          <div className="heatmap-label" style={{ display: 'flex', alignItems: 'center' }}>
            {wbNames[i]}
          </div>
          {workbooks.map((wbCol, j) => {
            if (i === j) {
              return <div key={`${i}-${j}`} className="heatmap-cell" style={{ background: 'var(--bg-base)' }}>—</div>;
            }
            const val = overlapMap[`${wbRow.id}-${wbCol.id}`] || 0;
            return (
              <div
                key={`${i}-${j}`}
                className="heatmap-cell"
                style={{ background: getColor(val), color: val > 0.4 ? 'white' : 'var(--text-muted)' }}
                title={`${wbRow.name} vs ${wbCol.name}: ${(val * 100).toFixed(0)}%`}
              >
                {val > 0 ? `${(val * 100).toFixed(0)}` : ''}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
