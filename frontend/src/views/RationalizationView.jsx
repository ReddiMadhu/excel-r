import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CheckCircle, GitMerge, Trash2, AlertCircle, Search,
  ChevronRight, X, ArrowRight, TrendingUp, Sparkles, Mail,
} from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { StatCard, Loader, EmptyState } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';

export default function RationalizationView() {
  const { data: recs, loading } = useApi(api.getRecommendations);
  const { data: pairwise, loading: pwLoading } = useApi(api.getPairwiseMatrix);
  const navigate = useNavigate();

  // Email Modal states
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [emailInput, setEmailInput] = useState('governance-team@company.com');
  const [emailStep, setEmailStep] = useState('input'); // 'input' | 'sending' | 'success' | 'error'
  const [emailMessage, setEmailMessage] = useState('');

  const handleOpenEmailModal = () => {
    setEmailStep('input');
    setEmailMessage('');
    setEmailModalOpen(true);
  };

  const handleSendEmail = async (e) => {
    if (e) e.preventDefault();
    if (!emailInput || !emailInput.includes('@')) {
      alert('Please enter a valid email address.');
      return;
    }
    setEmailStep('sending');
    try {
      const res = await api.sendEmailToTeam({ email: emailInput });
      setEmailMessage(res.message || `Governance report successfully emailed to ${emailInput}.`);
      setEmailStep('success');
    } catch (err) {
      console.error(err);
      setEmailMessage(err.message || 'Failed to dispatch governance email.');
      setEmailStep('error');
    }
  };

  // Pairwise KPI breakdown lookup: "id_a-id_b" → { unique_kpis_a, unique_kpis_b, name_a, name_b }
  const pairwiseKpiMap = useMemo(() => {
    if (!pairwise?.pairs) return {};
    const map = {};
    pairwise.pairs.forEach(p => {
      const key = [p.workbook_id_a, p.workbook_id_b].sort((a, b) => a - b).join('-');
      map[key] = {
        unique_kpis_a: p.unique_kpis_a || [],
        unique_kpis_b: p.unique_kpis_b || [],
        name_a: p.workbook_name_a,
        name_b: p.workbook_name_b,
        id_a: p.workbook_id_a,
        id_b: p.workbook_id_b,
        overlap_relationship: p.overlap_relationship || 'distinct',
      };
    });
    return map;
  }, [pairwise]);

  // Compute sharing map for KPIs
  const kpiSharingMap = useMemo(() => {
    if (!recs) return {};
    const map = {};
    recs.forEach(r => {
      if (r.common_kpis) {
        r.common_kpis.forEach(k => {
          if (!map[k]) map[k] = new Set();
          if (r.workbook_name) map[k].add(r.workbook_name);
          if (r.merge_with_name) map[k].add(r.merge_with_name);
        });
      }
    });
    const result = {};
    for (const k in map) {
      result[k] = Array.from(map[k]).sort();
    }
    return result;
  }, [recs]);

  // Filter state
  const [activeTab, setActiveTab] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedWorkbook, setSelectedWorkbook] = useState('all');

  // Heatmap collapse
  const [heatmapOpen, setHeatmapOpen] = useState(false);

  // ── Derived data ──────────────────────────────────────────
  const counts = useMemo(() => {
    if (!recs) return { keep: 0, merge: 0, decommission: 0, review: 0 };
    // Count merge groups (pairs), not individual workbooks
    const mergeAll = recs.filter(r => r.action === 'merge');
    const seenPairs = new Set();
    let mergeGroups = 0;
    for (const r of mergeAll) {
      if (!r.merge_with_id) { mergeGroups++; continue; }
      const key = [r.workbook_id, r.merge_with_id].sort((a, b) => a - b).join('-');
      if (!seenPairs.has(key)) { seenPairs.add(key); mergeGroups++; }
    }
    return {
      keep: recs.filter(r => r.action === 'keep').length,
      merge: mergeGroups,
      decommission: recs.filter(r => r.action === 'decommission' || r.action === 'delete').length,
      review: recs.filter(r => r.action === 'review').length,
    };
  }, [recs]);

  const workbookNames = useMemo(() => {
    if (!recs) return [];
    const names = new Set(recs.map(r => r.workbook_name).filter(Boolean));
    return Array.from(names).sort();
  }, [recs]);

  // Navigate to review detail page
  const goToReview = (rec, type) => {
    navigate(`/rationalization/review/${type}/${rec.workbook_id || rec.id}`);
  };

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
    if (selectedWorkbook !== 'all') {
      // For merge recs, include if either side matches
      const nameMatch = rec.workbook_name === selectedWorkbook;
      const partnerMatch = rec.merge_with_name === selectedWorkbook;
      if (!nameMatch && !partnerMatch) return false;
    }
    return true;
  };

  // Raw merge recs (undeduped) — used only for counting individuals
  const mergeRecs = useMemo(
    () => (recs || []).filter(r => r.action === 'merge').filter(filterRec),
    [recs, searchTerm, selectedWorkbook]
  );

  // Deduplicated merge pairs — one card per unique A↔B pair
  const mergePairs = useMemo(() => {
    const seen = new Set();
    const pairs = [];
    for (const rec of mergeRecs) {
      if (!rec.merge_with_id) {
        pairs.push({ primary: rec, partner: null });
        continue;
      }
      const key = [rec.workbook_id, rec.merge_with_id].sort((a, b) => a - b).join('-');
      if (!seen.has(key)) {
        seen.add(key);
        const partner = mergeRecs.find(r => r.workbook_id === rec.merge_with_id) || null;
        pairs.push({ primary: rec, partner });
      }
    }
    return pairs;
  }, [mergeRecs]);

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



  if (loading) return <Loader />;

  const totalFiltered = mergePairs.length + decommissionFiltered.length + keepRecs.length + reviewRecs.length;

  return (
    <div className="page-enter">
      <PageHeader
        title="Rationalization Results"
        actions={
          <button
            onClick={handleOpenEmailModal}
            className="btn btn-primary"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: '0.85rem',
              padding: '6px 12px',
              cursor: 'pointer'
            }}
            title="Send rationalization results to governance team via email"
          >
            <Mail size={15} />
            Send Email to Team
          </button>
        }
      />



      {(!recs || recs.length === 0) ? (
        <EmptyState
          icon={GitMerge}
          title="No recommendations yet"
          message="Upload multiple reports and the rationalization engine will produce recommendations."
        />
      ) : (
        <div>
          {/* ── Filter Toolbar ──────────────────────────────── */}
          <div className="ration-toolbar">
            <div className="ration-search">
              <Search />
              <input
                type="text"
                placeholder="Search report or dashboard..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>

            <select
              className="ration-workbook-select"
              value={selectedWorkbook}
              onChange={(e) => setSelectedWorkbook(e.target.value)}
            >
              <option value="all">All Reports</option>
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
                count={mergePairs.length}
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


          {/* ── Recommendation Cards Grid ──────────────────── */}
          {activeTab === 'all' ? (
            <div className="ration-grid">
              {/* Merge Column */}
              <div className="ration-column">
                <ColumnHeader
                  label="MERGE"
                  color="var(--accent-amber)"
                  count={mergePairs.length}
                  badge="merge"
                  badgeText="Groups"
                />
                {mergePairs.length > 0 ? mergePairs.map(({ primary, partner }) => (
                  <MergeGroupCard
                    key={primary.id}
                    primary={primary}
                    partner={partner}
                    onReviewPrimary={() => goToReview(primary, 'merge')}
                    onReviewPartner={partner ? () => goToReview(partner, 'merge') : null}
                    kpiSharingMap={kpiSharingMap}
                    pairwiseKpiMap={pairwiseKpiMap}
                  />
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
                  <RecCard key={rec.id} rec={rec} type="decommission" onReview={() => goToReview(rec, 'decommission')} kpiSharingMap={kpiSharingMap} />
                )) : <div className="ration-empty">No decommission recommendations</div>}
              </div>

              {/* Keep Column */}
              <div className="ration-column">
                <ColumnHeader
                  label="KEEP"
                  color="var(--accent-emerald)"
                  count={keepRecs.length}
                  badge="keep"
                  badgeText="Active"
                />
                {keepRecs.length > 0 ? keepRecs.map(rec => (
                  <RecCard key={rec.id} rec={rec} type="keep" onReview={() => goToReview(rec, 'keep')} kpiSharingMap={kpiSharingMap} />
                )) : <div className="ration-empty">No keep recommendations</div>}
              </div>
            </div>
          ) : (
            <div className="ration-grid single-col">
              {activeTab === 'merge' && (
                <div className="ration-column">
                  <ColumnHeader label="MERGE" color="var(--accent-amber)" count={mergePairs.length} badge="merge" badgeText="Groups" />
                  {mergePairs.length > 0 ? mergePairs.map(({ primary, partner }) => (
                    <MergeGroupCard
                      key={primary.id}
                      primary={primary}
                      partner={partner}
                      onReviewPrimary={() => goToReview(primary, 'merge')}
                      onReviewPartner={partner ? () => goToReview(partner, 'merge') : null}
                      kpiSharingMap={kpiSharingMap}
                      pairwiseKpiMap={pairwiseKpiMap}
                    />
                  )) : <div className="ration-empty">No merge recommendations</div>}
                </div>
              )}
              {activeTab === 'decommission' && (
                <div className="ration-column">
                  <ColumnHeader label="DECOMMISSION" color="var(--accent-rose)" count={decommissionFiltered.length} badge="decommission" badgeText="Inactive" />
                  {decommissionFiltered.length > 0 ? decommissionFiltered.map(rec => (
                    <RecCard key={rec.id} rec={rec} type="decommission" onReview={() => goToReview(rec, 'decommission')} kpiSharingMap={kpiSharingMap} />
                  )) : <div className="ration-empty">No decommission recommendations</div>}
                </div>
              )}
              {activeTab === 'keep' && (
                <div className="ration-column">
                  <ColumnHeader label="KEEP" color="var(--accent-emerald)" count={keepRecs.length} badge="keep" badgeText="Active" />
                  {keepRecs.length > 0 ? keepRecs.map(rec => (
                    <RecCard key={rec.id} rec={rec} type="keep" onReview={() => goToReview(rec, 'keep')} kpiSharingMap={kpiSharingMap} />
                  )) : <div className="ration-empty">No keep recommendations</div>}
                </div>
              )}
              {activeTab === 'review' && (
                <div className="ration-column">
                  <ColumnHeader label="REVIEW" color="#3b82f6" count={reviewRecs.length} badge="review" badgeText="Needs Attention" />
                  {reviewRecs.length > 0 ? reviewRecs.map(rec => (
                    <RecCard key={rec.id} rec={rec} type="review" kpiSharingMap={kpiSharingMap} />
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

      {/* Email dispatch Modal */}
      {emailModalOpen && (
        <div className="email-modal-backdrop" onClick={() => setEmailModalOpen(false)}>
          <div className="email-modal-card" onClick={(e) => e.stopPropagation()}>
            <button className="email-modal-close" onClick={() => setEmailModalOpen(false)}>
              <X size={18} />
            </button>
            
            {emailStep === 'input' && (
              <form onSubmit={handleSendEmail} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--accent-blue)', marginBottom: 4 }}>
                  <Mail size={22} />
                  <h3 style={{ margin: 0, fontSize: '1.15rem' }}>Send Governance Report</h3>
                </div>
                <p className="text-secondary" style={{ fontSize: '0.85rem', margin: 0 }}>
                  Send the compiled BI rationalization and redundancy report directly to the team via email.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)' }}>TEAM EMAIL ADDRESS</label>
                  <input
                    type="email"
                    required
                    className="email-modal-input"
                    placeholder="e.g. governance-team@company.com"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    autoFocus
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8 }}>
                  <button type="button" className="btn btn-ghost" onClick={() => setEmailModalOpen(false)}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    Send Report
                  </button>
                </div>
              </form>
            )}

            {emailStep === 'sending' && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px 0', gap: 16 }}>
                <div className="email-modal-spinner" />
                <div style={{ textAlign: 'center' }}>
                  <h3 style={{ margin: '0 0 6px 0', fontSize: '1rem' }}>Dispatching Report</h3>
                  <p className="text-muted" style={{ fontSize: '0.8rem', margin: 0 }}>Compiling overlap models and sending to {emailInput}...</p>
                </div>
              </div>
            )}

            {emailStep === 'success' && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '16px 0', gap: 16 }}>
                <div className="email-modal-success-icon">✓</div>
                <div style={{ textAlign: 'center' }}>
                  <h3 style={{ margin: '0 0 6px 0', fontSize: '1.1rem', color: 'var(--accent-emerald)' }}>Report Dispatched</h3>
                  <p className="text-secondary" style={{ fontSize: '0.85rem', margin: 0 }}>{emailMessage}</p>
                </div>
                <button className="btn btn-primary" onClick={() => setEmailModalOpen(false)} style={{ marginTop: 8 }}>
                  Done
                </button>
              </div>
            )}

            {emailStep === 'error' && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '16px 0', gap: 16 }}>
                <div className="email-modal-error-icon">!</div>
                <div style={{ textAlign: 'center' }}>
                  <h3 style={{ margin: '0 0 6px 0', fontSize: '1.1rem', color: 'var(--accent-rose)' }}>Dispatch Failed</h3>
                  <p className="text-secondary" style={{ fontSize: '0.85rem', margin: 0 }}>{emailMessage}</p>
                </div>
                <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
                  <button className="btn btn-ghost" onClick={() => setEmailModalOpen(false)}>
                    Close
                  </button>
                  <button className="btn btn-primary" onClick={() => handleSendEmail()}>
                    Retry
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
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

function MergeGroupCard({ primary, partner, onReviewPrimary, onReviewPartner, kpiSharingMap, pairwiseKpiMap }) {
  const [kpiExpanded, setKpiExpanded] = useState(false);
  const reasons = cleanReasons(primary.reasons);
  const kpiPct = ((primary.kpi_overlap_score || 0) * 100).toFixed(0);
  const dsPct = ((primary.datasource_overlap_score || 0) * 100).toFixed(0);
  const commonKpis = primary.common_kpis || [];

  const partnerName = partner ? partner.workbook_name : (primary.merge_with_name || '');
  const partnerId = partner ? partner.workbook_id : primary.merge_with_id;

  // Lookup unique KPIs from pairwise data
  const pairKey = partnerId
    ? [primary.workbook_id, partnerId].sort((a, b) => a - b).join('-')
    : null;
  const pairData = pairKey ? (pairwiseKpiMap[pairKey] || null) : null;

  // Orient unique KPIs so _a = primary workbook, _b = partner
  let uniqueToPrimary = [];
  let uniqueToPartner = [];
  if (pairData) {
    if (pairData.id_a === primary.workbook_id) {
      uniqueToPrimary = pairData.unique_kpis_a;
      uniqueToPartner = pairData.unique_kpis_b;
    } else {
      uniqueToPrimary = pairData.unique_kpis_b;
      uniqueToPartner = pairData.unique_kpis_a;
    }
  }

  const totalKpis = commonKpis.length + uniqueToPrimary.length + uniqueToPartner.length;

  return (
    <div className="rec-card merge">
      {/* Header — both workbooks with merge icon */}
      <div className="rec-card-top" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', flexWrap: 'wrap' }}>
          <div className="rec-card-name" style={{ flex: 1 }}>{primary.workbook_name}</div>
          <span style={{
            display: 'flex', alignItems: 'center',
            color: 'var(--accent-amber)', fontWeight: 700, flexShrink: 0,
          }}>
            <GitMerge size={15} />
          </span>
          <div className="rec-card-name" style={{ flex: 1 }}>{partnerName}</div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span className="badge badge-amber" style={{ fontSize: '0.68rem' }}>Merge Group</span>
          {pairData?.overlap_relationship === 'both_have_extras' && (
            <span className="badge" style={{ fontSize: '0.68rem', background: 'rgba(59,130,246,0.12)', color: 'var(--accent-blue)' }}>
              Both add unique KPIs
            </span>
          )}
          {primary.llm_override && <span className="badge badge-purple" style={{ fontSize: '0.68rem' }}>AI Override</span>}
        </div>
      </div>

      {/* Overlap Scores */}
      <div className="rec-card-scores">
        <div className="rec-score-item">
          <span className="rec-score-label">KPI Overlap:</span>
          <span className="rec-score-value" style={{ color: scoreColor(+kpiPct, false) }}>{kpiPct}%</span>
        </div>
        <div className="rec-score-item">
          <span className="rec-score-label">DS Overlap:</span>
          <span className="rec-score-value" style={{ color: scoreColor(+dsPct, false) }}>{dsPct}%</span>
        </div>
      </div>

      {/* Rationale */}
      {reasons.length > 0 && (
        <div className="rec-card-rationale">
          <div className="rec-card-rationale-title">Governance Rationale</div>
          <ul>
            {reasons.map((reason, i) => (
              <li key={i}>
                <span className="rationale-icon" style={{ color: 'var(--accent-amber)' }}>!</span>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* AI Justification */}
      {primary.llm_justification && (
        <div className="rec-card-ai">
          <Sparkles size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
          {primary.llm_justification}
        </div>
      )}

      {/* KPI Breakdown — shared + unique per workbook */}
      {totalKpis > 0 && (
        <div className="rec-card-kpis">
          <button
            className="rec-card-kpis-label"
            onClick={() => setKpiExpanded(e => !e)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              display: 'flex', alignItems: 'center', gap: 6,
              color: 'inherit', font: 'inherit', fontWeight: 600,
            }}
          >
            <ChevronRight size={13} style={{ transform: kpiExpanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }} />
            KPI Breakdown
            <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: '0.75rem' }}>
              {commonKpis.length} shared · {uniqueToPrimary.length + uniqueToPartner.length} unique
            </span>
          </button>

          {kpiExpanded && (
            <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 10 }}>
              {/* Shared KPIs */}
              {commonKpis.length > 0 && (
                <div>
                  <div style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    Shared ({commonKpis.length} — {kpiPct}% overlap)
                  </div>
                  <div className="rec-card-kpis-tags">
                    {commonKpis.map((k, i) => (
                      <span key={i} className="rec-kpi-tag" style={{ background: 'rgba(245,158,11,0.12)', color: 'var(--accent-amber)' }} title="Shared between both workbooks">
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Unique to primary */}
              {uniqueToPrimary.length > 0 && (
                <div>
                  <div style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    Only in {primary.workbook_name} ({uniqueToPrimary.length})
                  </div>
                  <div className="rec-card-kpis-tags">
                    {uniqueToPrimary.map((k, i) => (
                      <span key={i} className="rec-kpi-tag" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)' }} title={`Unique to ${primary.workbook_name}`}>
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Unique to partner */}
              {uniqueToPartner.length > 0 && (
                <div>
                  <div style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    Only in {partnerName} ({uniqueToPartner.length})
                  </div>
                  <div className="rec-card-kpis-tags">
                    {uniqueToPartner.map((k, i) => (
                      <span key={i} className="rec-kpi-tag" style={{ background: 'rgba(139,92,246,0.1)', color: 'var(--accent-purple)' }} title={`Unique to ${partnerName}`}>
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Footer — review buttons for each workbook */}
      <div className="rec-card-footer" style={{ gap: 6, flexWrap: 'wrap' }}>
        <div style={{ flex: 1 }} />
        <button className="btn-review merge" onClick={onReviewPrimary} style={{ fontSize: '0.72rem' }}>
          {primary.workbook_name} <ArrowRight size={11} />
        </button>
        {onReviewPartner && (
          <button className="btn-review merge" onClick={onReviewPartner} style={{ fontSize: '0.72rem' }}>
            {partner?.workbook_name} <ArrowRight size={11} />
          </button>
        )}
      </div>
    </div>
  );
}

function RecCard({ rec, type, onReview, kpiSharingMap }) {
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
          {type === 'decommission' && reasons.some(r => /already present|identical kpi/i.test(r)) && (
            <span className="badge" style={{ marginTop: 4, display: 'inline-block', fontSize: '0.68rem', background: 'rgba(244,63,94,0.12)', color: 'var(--accent-rose)' }}>
              Subset of retain target
            </span>
          )}
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
            {rec.common_kpis.map((k, i) => {
              const sharingReports = (kpiSharingMap[k] || []).filter(name => name !== rec.workbook_name);
              const tooltipText = sharingReports.length > 0
                ? `Shared with: ${sharingReports.join(', ')}`
                : 'Shared KPI';
              return (
                <span key={i} className="rec-kpi-tag" title={tooltipText}>
                  {k}
                  {sharingReports.length > 0 && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 4 }}>
                      ({sharingReports.length})
                    </span>
                  )}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Footer with Review Button */}
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
          View Details <ArrowRight size={13} />
        </button>
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
