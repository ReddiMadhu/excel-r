import { useState, useEffect, useMemo } from 'react';
import {
  GitMerge, Trash2, CheckCircle, TrendingUp, Sparkles, Mail, X, FileDown,
  Star, Send, Target, AlertTriangle,
} from 'lucide-react';
import { jsPDF } from 'jspdf';
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


function generateDefaultEmailDraft(rec, type, sourceKpis) {
  if (!rec) return { to: '', subject: '', body: '' };

  let to = rec.user_groups && rec.user_groups.length > 0
    ? `${rec.user_groups[0].toLowerCase().replace(/[^a-z0-9]/g, '-')}@company.com`
    : 'stakeholders@company.com';

  let subject = '';
  let body = '';

  const reasonsList = cleanReasons(rec.reasons)
    .map(r => `- ${r}`)
    .join('\n');
  const audienceList = rec.user_groups && rec.user_groups.length > 0
    ? rec.user_groups.map(g => `- ${g}`).join('\n')
    : '- General Stakeholders';
  const kpisList = sourceKpis && sourceKpis.length > 0
    ? sourceKpis.map(k => `- ${k}`).join('\n')
    : '- No registered KPIs';
  const datasourcesList = rec.tables && rec.tables.length > 0
    ? rec.tables.map(t => `- ${t}`).join('\n')
    : '- No direct database lineage references';

  if (type === 'merge') {
    subject = `[Governance Action Required] Consolidation & Merge Recommendation: ${rec.workbook_name}`;
    body = `Hello Stakeholders,

We have analyzed the BI reporting landscape and identified significant metric and layout overlap. We recommend merging the report "${rec.workbook_name}" into "${rec.merge_with_name || 'the recommended target report'}".

Recommended Action: Consolidate and merge into ${rec.merge_with_name || 'Recommended Target Report'}

Governance Rationale:
${reasonsList || '- Redundant metric definitions and database queries.'}

Affected Audience Groups:
${audienceList}

Mapped KPIs:
${kpisList}

Source Database Lineage:
${datasourcesList}

Please review these details. If you have any questions or require an extension before decommissioning, please let the BI Governance Team know.

Best regards,
BI Governance Team`;
  } else if (type === 'decommission') {
    subject = `[Governance Action Required] Decommission & Archive Notification: ${rec.workbook_name}`;
    body = `Hello Stakeholders,

This is a formal notification that the report "${rec.workbook_name}" has been flagged for decommissioning due to platform cleanliness violations and low utilization.

Recommended Action: Archive and Decommission Report

Governance Rationale & Cleanliness Violations:
${reasonsList || '- Zero active views in the past 90 days.'}

Affected Audience Groups:
${audienceList}

Mapped KPIs:
${kpisList}

Source Database Lineage:
${datasourcesList}

After decommissioning, this report metadata will be archived and database connection endpoints severed. Please save any necessary custom layouts immediately.

Best regards,
BI Governance Team`;
  } else {
    subject = `[Governance Status] Keep Status: ${rec.workbook_name}`;
    body = `Hello Stakeholders,

We have audited the report "${rec.workbook_name}" and confirmed its status as a Keep report.

Recommended Action: Keep Active

Governance Rationale:
${reasonsList || '- High uniqueness and active stakeholder utilization.'}

Affected Audience Groups:
${audienceList}

Mapped KPIs:
${kpisList}

Source Database Lineage:
${datasourcesList}

Thank you for maintaining high-quality dashboard standards.

Best regards,
BI Governance Team`;
  }

  return { to, subject, body };
}


/**
 * ClusterMemberDetailPanel — rich inline rationalization detail view
 * for a single workbook within a cluster.
 *
 * Renders inside ClusterDetailView's right panel instead of navigating to
 * /rationalization/review/:type/:id.
 */
export default function ClusterMemberDetailPanel({ clusterId, workbookId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Email Modal & Draft states
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [emailDraft, setEmailDraft] = useState({ to: '', subject: '', body: '' });
  const [emailStep, setEmailStep] = useState('input');
  const [emailMessage, setEmailMessage] = useState('');

  useEffect(() => {
    if (!clusterId || !workbookId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getClusterMemberDetail(clusterId, workbookId)
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
  }, [clusterId, workbookId]);

  // Determine column swap for merge: rec with more KPIs goes left
  const { leftRec, rightRec, leftKpis, rightKpis, leftOnlyKpis, rightOnlyKpis,
    leftUniquePct, rightUniquePct, leftDsCount, rightDsCount,
    leftDsCoverage, rightDsCoverage, leftKpiCoverage, rightKpiCoverage,
    leftReasons, rightReasons, swapColumns
  } = useMemo(() => {
    if (!data) return {};

    const rec = data.rec;
    const target = data.target_rec;
    const type = data.type;
    const cov = data.kpi_coverage;

    const sourceKpis = data.source_kpis || [];
    const targetKpis = data.target_kpis || [];
    const srcOnlyKpis = data.source_only_kpis || [];
    const tgtOnlyKpis = data.target_only_kpis || [];

    // Determine swap: for merge, if source has more KPIs → it's the consolidation target
    let swap = false;
    if (type === 'merge' && target) {
      const recKpis = sourceKpis.length;
      const tgtKpisLen = targetKpis.length;
      if (recKpis !== tgtKpisLen) {
        swap = recKpis > tgtKpisLen;
      } else {
        const recDs = rec.ds_sources_count || 0;
        const targetDs = target.ds_sources_count || 0;
        if (recDs !== targetDs) {
          swap = recDs > targetDs;
        } else {
          const recQuality = rec.scores?.extraction_quality_score || 0;
          const targetQuality = target.scores?.extraction_quality_score || 0;
          swap = recQuality !== targetQuality ? recQuality > targetQuality : rec.workbook_id < target.workbook_id;
        }
      }
    }

    const lRec = swap ? target : rec;
    const rRec = swap ? rec : target;
    const lKpis = swap ? targetKpis : sourceKpis;
    const rKpis = swap ? sourceKpis : targetKpis;
    const lOnlyKpis = swap ? tgtOnlyKpis : srcOnlyKpis;
    const rOnlyKpis = swap ? srcOnlyKpis : tgtOnlyKpis;

    const lUniquePct = swap ? cov.target_unique_pct : cov.source_unique_pct;
    const rUniquePct = swap ? cov.source_unique_pct : cov.target_unique_pct;
    const lDsCount = swap ? cov.target_ds_count : cov.source_ds_count;
    const rDsCount = swap ? cov.source_ds_count : cov.target_ds_count;
    const lDsCoverage = swap ? cov.target_ds_coverage_pct : cov.source_ds_coverage_pct;
    const rDsCoverage = swap ? cov.source_ds_coverage_pct : cov.target_ds_coverage_pct;
    const lKpiCoverage = swap ? cov.target_coverage_pct : cov.source_coverage_pct;
    const rKpiCoverage = swap ? cov.source_coverage_pct : cov.target_coverage_pct;

    const srcReasons = cleanReasons(rec?.reasons);
    const tgtReasons = target ? cleanReasons(target.reasons) : [];
    const lReasons = swap ? tgtReasons : srcReasons;
    const rReasons = swap ? srcReasons : tgtReasons;

    return {
      leftRec: lRec, rightRec: rRec, leftKpis: lKpis, rightKpis: rKpis,
      leftOnlyKpis: lOnlyKpis, rightOnlyKpis: rOnlyKpis,
      leftUniquePct: lUniquePct, rightUniquePct: rUniquePct,
      leftDsCount: lDsCount, rightDsCount: rDsCount,
      leftDsCoverage: lDsCoverage, rightDsCoverage: rDsCoverage,
      leftKpiCoverage: lKpiCoverage, rightKpiCoverage: rKpiCoverage,
      leftReasons: lReasons, rightReasons: rReasons,
      swapColumns: swap,
    };
  }, [data]);

  const graphWorkbookIds = useMemo(() => {
    if (!data) return [];
    const ids = [data.workbook_id];
    if (data.rec?.merge_with_id) ids.push(data.rec.merge_with_id);
    return ids;
  }, [data]);

  // PDF download
  const downloadRationalisationPDF = () => {
    if (!data) return;
    const rec = data.rec;
    const type = data.type;
    const sourceKpis = data.source_kpis || [];
    const reasons = cleanReasons(rec.reasons);

    const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
    const pageHeight = 297;
    const pageWidth = 210;
    const marginX = 20;
    const contentWidth = pageWidth - (marginX * 2);
    let y = 20;

    const checkPageBreak = (neededHeight) => {
      if (y + neededHeight > pageHeight - 20) {
        doc.addPage();
        y = 20;
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(8);
        doc.setTextColor(150, 150, 150);
        doc.text(`BI Governance Report: ${rec.workbook_name}`, marginX, 10);
        doc.line(marginX, 12, pageWidth - marginX, 12);
        y = 20;
      }
    };

    const addParagraph = (text, fontSize = 10, isBold = false, color = [51, 65, 85]) => {
      doc.setFont('helvetica', isBold ? 'bold' : 'normal');
      doc.setFontSize(fontSize);
      doc.setTextColor(color[0], color[1], color[2]);
      const lines = doc.splitTextToSize(text, contentWidth);
      const lineHeight = fontSize * 0.45;
      lines.forEach(line => {
        checkPageBreak(lineHeight);
        doc.text(line, marginX, y);
        y += lineHeight;
      });
      y += 2;
    };

    // Title banner
    doc.setFillColor(30, 41, 59);
    doc.rect(0, 0, pageWidth, 40, 'F');
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(18);
    doc.setTextColor(255, 255, 255);
    doc.text('BI Governance & Rationalization Report', marginX, 18);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(226, 232, 240);
    const dateStr = new Date().toLocaleDateString('en-US', {
      year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
    doc.text(`Generated on ${dateStr} | System: Antigravity Governance Engine`, marginX, 26);
    y = 52;

    // Report card
    checkPageBreak(25);
    doc.setFillColor(248, 250, 252);
    doc.setDrawColor(226, 232, 240);
    doc.rect(marginX, y, contentWidth, 24, 'FD');
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.setTextColor(30, 41, 59);
    doc.text(`Report name: ${rec.workbook_name}`, marginX + 6, y + 8);

    let actionText = '';
    let actionColor = [100, 116, 139];
    if (type === 'merge') {
      actionText = `CONSOLIDATION MERGE (Merge into: ${rec.merge_with_name || 'Target Report'})`;
      actionColor = [217, 119, 6];
    } else if (type === 'decommission') {
      actionText = 'DECOMMISSION / ARCHIVE';
      actionColor = [225, 29, 72];
    } else {
      actionText = 'KEEP';
      actionColor = [5, 150, 105];
    }
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10);
    doc.setTextColor(actionColor[0], actionColor[1], actionColor[2]);
    doc.text(`Recommended Action: ${actionText}`, marginX + 6, y + 16);
    y += 32;

    // Justification
    if (rec.llm_justification) {
      checkPageBreak(15);
      addParagraph('Executive Justification', 12, true, [15, 23, 42]);
      doc.setDrawColor(226, 232, 240);
      doc.line(marginX, y - 1, pageWidth - marginX, y - 1);
      y += 3;
      addParagraph(rec.llm_justification, 10, false, [51, 65, 85]);
      y += 4;
    }

    // Rationale
    if (reasons.length > 0) {
      checkPageBreak(15);
      const titleText = type === 'decommission' ? 'Cleanliness Violations' : 'Governance Rationale';
      addParagraph(titleText, 12, true, [15, 23, 42]);
      doc.setDrawColor(226, 232, 240);
      doc.line(marginX, y - 1, pageWidth - marginX, y - 1);
      y += 3;
      reasons.forEach(reason => {
        checkPageBreak(8);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(actionColor[0], actionColor[1], actionColor[2]);
        doc.text('•', marginX + 2, y);
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(10);
        doc.setTextColor(51, 65, 85);
        const lines = doc.splitTextToSize(reason, contentWidth - 8);
        const lineHeight = 10 * 0.45;
        lines.forEach((line, index) => {
          if (index > 0) checkPageBreak(lineHeight);
          doc.text(line, marginX + 6, y);
          if (index < lines.length - 1) y += lineHeight;
        });
        y += lineHeight + 2;
      });
      y += 2;
    }

    // Audience
    checkPageBreak(15);
    addParagraph('Affected Audience & Stakeholders', 12, true, [15, 23, 42]);
    doc.setDrawColor(226, 232, 240);
    doc.line(marginX, y - 1, pageWidth - marginX, y - 1);
    y += 3;
    const audienceGroups = rec.user_groups && rec.user_groups.length > 0
      ? rec.user_groups.join(', ')
      : 'No specific audience groups registered.';
    addParagraph(`Stakeholder Groups: ${audienceGroups}`, 10, false, [51, 65, 85]);
    y += 4;

    // KPIs
    checkPageBreak(15);
    addParagraph('Mapped Key Performance Indicators (KPIs)', 12, true, [15, 23, 42]);
    doc.setDrawColor(226, 232, 240);
    doc.line(marginX, y - 1, pageWidth - marginX, y - 1);
    y += 3;
    if (sourceKpis.length > 0) {
      addParagraph(`Total Mapped KPIs: ${sourceKpis.length}`, 10, true, [30, 41, 59]);
      addParagraph(sourceKpis.join(', '), 9, false, [71, 85, 105]);
    } else {
      addParagraph('No registered KPIs detected for this report.', 10, false, [100, 116, 139]);
    }
    y += 4;

    // DB Lineage
    checkPageBreak(15);
    addParagraph('Database Lineage & Source Schema Connections', 12, true, [15, 23, 42]);
    doc.setDrawColor(226, 232, 240);
    doc.line(marginX, y - 1, pageWidth - marginX, y - 1);
    y += 3;
    const sourceTablesList = rec.tables || [];
    if (sourceTablesList.length > 0) {
      addParagraph(`Referenced Data Tables: ${sourceTablesList.length}`, 10, true, [30, 41, 59]);
      addParagraph(sourceTablesList.join(', '), 9, false, [71, 85, 105]);
    } else {
      addParagraph('No direct database lineage references detected.', 10, false, [100, 116, 139]);
    }

    // Footer
    const pageCount = doc.internal.getNumberOfPages();
    for (let i = 1; i <= pageCount; i++) {
      doc.setPage(i);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8);
      doc.setTextColor(148, 163, 184);
      doc.text(`Page ${i} of ${pageCount}`, pageWidth - marginX - 15, pageHeight - 10);
      doc.text('CONFIDENTIAL - FOR INTERNAL BI GOVERNANCE USE ONLY', marginX, pageHeight - 10);
    }

    const cleanName = rec.workbook_name.replace(/[^a-z0-9]/gi, '_').toLowerCase();
    doc.save(`governance_report_${cleanName}.pdf`);
  };

  // Email handlers
  const handleOpenEmailModal = () => {
    if (!data) return;
    const draft = generateDefaultEmailDraft(data.rec, data.type, data.source_kpis);
    setEmailDraft(draft);
    setEmailStep('input');
    setEmailMessage('');
    setEmailModalOpen(true);
  };

  const handleSendEmail = async (e) => {
    if (e) e.preventDefault();
    if (!emailDraft.to || !emailDraft.to.includes('@')) {
      alert('Please enter a valid email address.');
      return;
    }
    setEmailStep('sending');
    try {
      const res = await api.sendEmailToTeam({
        email: emailDraft.to,
        subject: emailDraft.subject,
        body: emailDraft.body
      });
      setEmailMessage(res.message || `Governance notification successfully emailed to ${emailDraft.to}.`);
      setEmailStep('success');
    } catch (err) {
      console.error(err);
      setEmailMessage(err.message || 'Failed to dispatch governance email.');
      setEmailStep('error');
    }
  };

  // ─── Render ──────────────────────────────────────────────────

  if (loading) return <div className="page-enter" style={{ padding: 40 }}><Loader /></div>;

  if (error || !data) {
    return (
      <div className="card page-enter" style={{ padding: 40, textAlign: 'center' }}>
        <p style={{ color: 'var(--text-muted)' }}>
          {error || 'Could not load detail for this workbook.'}
        </p>
      </div>
    );
  }

  const type = data.type;
  const rec = data.rec;
  const target = data.target_rec;
  const sharedKpis = data.shared_kpis || [];
  const cov = data.kpi_coverage;
  const reasons = cleanReasons(rec.reasons);

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
      subtitle: 'This workbook is functionally redundant as it tracks identical metrics to the recommended target and relies on the same underlying SQL data sources.',
      color: 'var(--accent-rose)',
      iconClass: 'decommission',
    },
    keep: {
      icon: data.cluster_role === 'canonical_target' ? Target : CheckCircle,
      title: data.cluster_role === 'canonical_target' ? 'Recommended Target' : 'Keep Review',
      subtitle: data.cluster_role === 'canonical_target'
        ? 'This workbook is retained as the authoritative reference for this reporting group.'
        : 'Review KPIs, data sources, and governance status of this report.',
      color: 'var(--accent-emerald)',
      iconClass: 'keep',
    },
  };

  const config = typeConfig[type] || typeConfig.keep;
  const IconComponent = config.icon;

  return (
    <div className="page-enter review-detail-page" style={{ padding: 0, maxWidth: '100%' }}>
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
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={downloadRationalisationPDF}
            className="btn btn-ghost"
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: '0.85rem', padding: '6px 12px', cursor: 'pointer',
              border: '1px solid var(--glass-border)'
            }}
            title="Download PDF Report"
          >
            <FileDown size={15} />
            Download PDF Report
          </button>
          <button
            onClick={handleOpenEmailModal}
            className="btn btn-primary"
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: '0.85rem', padding: '6px 12px', cursor: 'pointer'
            }}
            title="Send notification email to stakeholders"
          >
            <Mail size={15} />
            Email Stakeholders
          </button>
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
                 data.cluster_role === 'canonical_target' ? 'Recommended Target' :
                 'Report'}
              </span>
              <h2 className="review-detail-col-name">{leftRec?.workbook_name}</h2>
            </div>

            {/* Scores — per-workbook containment */}
            <div className="review-detail-section">
              <h3 className="review-detail-section-title">
                Compared with {rightRec ? `"${rightRec.workbook_name}"` : 'Other Report'}
              </h3>
              <div className="review-detail-scores">
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">KPI Overlap</span>
                  <span className="review-detail-score-value" style={{ color:
                    type === 'merge'
                      ? (leftKpiCoverage >= 70 ? 'var(--accent-emerald)' : leftKpiCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                      : (leftKpiCoverage >= 90 ? 'var(--accent-rose)' : leftKpiCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                  }}>
                    {leftKpiCoverage}%
                  </span>
                  <span className="review-detail-score-note">{cov.shared_count} of {leftKpis?.length || 0} KPIs</span>
                </div>
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">Data Source Overlap</span>
                  <span className="review-detail-score-value" style={{ color:
                    type === 'merge'
                      ? (leftDsCoverage >= 70 ? 'var(--accent-emerald)' : leftDsCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                      : (leftDsCoverage >= 90 ? 'var(--accent-rose)' : leftDsCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                  }}>
                    {leftDsCoverage}%
                  </span>
                  <span className="review-detail-score-note">{cov.ds_shared_count} of {leftDsCount || '?'} columns</span>
                </div>
                <div className="review-detail-score-item">
                  <span className="review-detail-score-label">Unique KPIs</span>
                  <span className="review-detail-score-value" style={{ color:
                    leftUniquePct > 0
                      ? (type === 'merge' ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                      : 'var(--text-muted)'
                  }}>
                    {leftUniquePct}%
                  </span>
                  <span className="review-detail-score-note">{leftOnlyKpis?.length || 0} only in this report</span>
                </div>
              </div>
            </div>

            {/* KPIs */}
            {(sharedKpis.length > 0 || (leftOnlyKpis && leftOnlyKpis.length > 0)) && (
              <div className="review-detail-section">
                <h3 className="review-detail-section-title">
                  {type === 'merge' ? 'KPIs in Merge Candidate' : 'KPIs in This Report'}
                </h3>
                <div className="review-detail-kpi-list">
                  {sharedKpis.map((k, i) => (
                    <div key={`shared-${i}`} className="review-detail-kpi-item shared">
                      <span>{k}</span>
                      <span className="review-detail-shared-badge">SHARED</span>
                    </div>
                  ))}
                  {(leftOnlyKpis || []).map((k, i) => (
                    <div key={`source-${i}`} className="review-detail-kpi-item">
                      <span>{k}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Rationale (for non-decommission) */}
            {type !== 'decommission' && leftReasons && leftReasons.length > 0 && (
              <div className="review-detail-section">
                <h3 className="review-detail-section-title">Governance Rationale</h3>
                <div className="review-detail-rationale">
                  {leftReasons.map((r, i) => (
                    <div key={i} className="review-detail-rationale-item">
                      <span className="review-detail-rationale-icon" style={{ color: config.color, marginTop: '2px', display: 'flex', alignItems: 'center' }}>
                        {type === 'merge' ? <AlertTriangle size={13} /> : <CheckCircle size={13} />}
                      </span>
                      <span>{r}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* AI Justification (for non-decommission) */}
            {type !== 'decommission' && leftRec?.llm_justification && (
              <div className="review-detail-ai">
                <Sparkles size={14} style={{ flexShrink: 0 }} />
                <span>{leftRec.llm_justification}</span>
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
                <h2 className="review-detail-col-name">{rightRec?.workbook_name || '—'}</h2>
              </div>

              {rightRec && (
                <>
                  <div className="review-detail-section">
                    <h3 className="review-detail-section-title">
                      Compared with "{leftRec?.workbook_name}"
                    </h3>
                    <div className="review-detail-scores">
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">KPI Overlap</span>
                        <span className="review-detail-score-value" style={{ color:
                          type === 'merge'
                            ? (rightKpiCoverage >= 70 ? 'var(--accent-emerald)' : rightKpiCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                            : (rightKpiCoverage >= 90 ? 'var(--accent-rose)' : rightKpiCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                        }}>
                          {rightKpiCoverage}%
                        </span>
                        <span className="review-detail-score-note">{cov.shared_count} of {rightKpis?.length || 0} KPIs</span>
                      </div>
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">Data Source Overlap</span>
                        <span className="review-detail-score-value" style={{ color:
                          type === 'merge'
                            ? (rightDsCoverage >= 70 ? 'var(--accent-emerald)' : rightDsCoverage >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)')
                            : (rightDsCoverage >= 90 ? 'var(--accent-rose)' : rightDsCoverage >= 50 ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                        }}>
                          {rightDsCoverage}%
                        </span>
                        <span className="review-detail-score-note">{cov.ds_shared_count} of {rightDsCount || '?'} columns</span>
                      </div>
                      <div className="review-detail-score-item">
                        <span className="review-detail-score-label">Unique KPIs</span>
                        <span className="review-detail-score-value" style={{ color:
                          rightUniquePct > 0
                            ? (type === 'merge' ? 'var(--accent-amber)' : 'var(--accent-emerald)')
                            : 'var(--text-muted)'
                        }}>
                          {rightUniquePct}%
                        </span>
                        <span className="review-detail-score-note">{rightOnlyKpis?.length || 0} only in this report</span>
                      </div>
                    </div>
                  </div>

                  {(sharedKpis.length > 0 || (rightOnlyKpis && rightOnlyKpis.length > 0)) && (
                    <div className="review-detail-section">
                      <h3 className="review-detail-section-title">
                        {type === 'merge' ? 'KPIs in Consolidation Target' : 'Its KPIs'}
                      </h3>
                      <div className="review-detail-kpi-list">
                        {sharedKpis.map((k, i) => (
                          <div key={`target-shared-${i}`} className="review-detail-kpi-item shared">
                            <span>{k}</span>
                            <span className="review-detail-shared-badge">SHARED</span>
                          </div>
                        ))}
                        {(rightOnlyKpis || []).map((k, i) => (
                          <div key={`target-only-${i}`} className="review-detail-kpi-item">
                            <span>{k}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {rightReasons && rightReasons.length > 0 && (
                    <div className="review-detail-section">
                      <h3 className="review-detail-section-title">Target Rationale</h3>
                      <div className="review-detail-rationale">
                        {rightReasons.map((r, i) => (
                          <div key={i} className="review-detail-rationale-item">
                            <span className="review-detail-rationale-icon" style={{ color: 'var(--accent-emerald)', marginTop: '2px', display: 'flex', alignItems: 'center' }}>
                              <CheckCircle size={13} />
                            </span>
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

          {/* For keep/golden target with no merge target, show single-column view */}
          {type === 'keep' && !rec.merge_with_name && (
            <div className="review-detail-col">
              <div className="review-detail-col-header" style={{ borderColor: 'var(--accent-emerald)' }}>
                <span className="review-detail-col-label" style={{ color: 'var(--accent-emerald)' }}>
                  Status
                </span>
                <h2 className="review-detail-col-name">Active</h2>
              </div>
              <div className="review-detail-section">
                <h3 className="review-detail-section-title">Governance Rationale</h3>
                <div className="review-detail-rationale">
                  {reasons.length > 0 ? reasons.map((r, i) => (
                    <div key={i} className="review-detail-rationale-item">
                      <span className="review-detail-rationale-icon" style={{ color: 'var(--accent-emerald)', marginTop: '2px', display: 'flex', alignItems: 'center' }}>
                        <CheckCircle size={13} />
                      </span>
                      <span>{r}</span>
                    </div>
                  )) : (
                    <div className="review-detail-rationale-item">
                      <span className="review-detail-rationale-icon" style={{ color: 'var(--accent-emerald)', marginTop: '2px', display: 'flex', alignItems: 'center' }}>
                        <CheckCircle size={13} />
                      </span>
                      <span>High uniqueness and active stakeholder utilization.</span>
                    </div>
                  )}
                </div>
              </div>
              {rec.llm_justification && (
                <div className="review-detail-ai">
                  <Sparkles size={14} style={{ flexShrink: 0 }} />
                  <span>{rec.llm_justification}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Decommission Rationale section removed and moved to heading subtext */}

        {/* Graph Section */}
        <div className="review-detail-graph-section">
          <div className="review-detail-graph-header">
            <div className="review-detail-graph-title" style={{ color: config.color }}>
              <TrendingUp size={18} />
              <span>{type === 'merge' ? 'Visual Lineage & Common Connections' : 'Report Connections Lineage'}</span>
            </div>
          </div>

          <div className="review-detail-graph-body">
            <div className="review-detail-graph-wrapper" style={{ width: '100%' }}>
              <KPIDashboardGraph
                view={type === 'keep' || !rec.merge_with_id ? 'landscape' : 'rationalization'}
                workbookId={type === 'keep' || !rec.merge_with_id ? data.workbook_id : undefined}
                workbookIds={type === 'keep' || !rec.merge_with_id ? undefined : graphWorkbookIds}
                height="550px"
                legendExcludeGroups={['Report', 'KPI']}
                hideSharedSources={true}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Email dispatch Modal */}
      {emailModalOpen && (
        <div className="email-modal-backdrop" onClick={() => setEmailModalOpen(false)}>
          <div className="email-modal-card" style={{ maxWidth: '640px', width: '90%' }} onClick={(e) => e.stopPropagation()}>
            <button className="email-modal-close" onClick={() => setEmailModalOpen(false)}>
              <X size={18} />
            </button>

            {emailStep === 'input' && (
              <form onSubmit={handleSendEmail} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--accent-blue)', marginBottom: 2 }}>
                  <Mail size={22} />
                  <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>Review Email Draft</h3>
                </div>
                <p className="text-secondary" style={{ fontSize: '0.85rem', margin: 0 }}>
                  Review and customize the notification subject and body before sending it to stakeholders.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)' }}>RECIPIENT EMAIL</label>
                  <input
                    type="email"
                    required
                    className="email-modal-input"
                    placeholder="e.g. stakeholders@company.com"
                    value={emailDraft.to}
                    onChange={(e) => setEmailDraft({ ...emailDraft, to: e.target.value })}
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)' }}>SUBJECT</label>
                  <input
                    type="text"
                    required
                    className="email-modal-input"
                    placeholder="Email Subject"
                    value={emailDraft.subject}
                    onChange={(e) => setEmailDraft({ ...emailDraft, subject: e.target.value })}
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)' }}>EMAIL BODY</label>
                  <textarea
                    required
                    className="email-modal-input"
                    style={{ minHeight: '220px', fontFamily: 'monospace', fontSize: '0.85rem', lineHeight: '1.4', resize: 'vertical' }}
                    placeholder="Type email body here..."
                    value={emailDraft.body}
                    onChange={(e) => setEmailDraft({ ...emailDraft, body: e.target.value })}
                  />
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8 }}>
                  <button type="button" className="btn btn-ghost" onClick={() => setEmailModalOpen(false)}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    Send Notification
                  </button>
                </div>
              </form>
            )}

            {emailStep === 'sending' && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '24px 0', gap: 16 }}>
                <div className="email-modal-spinner" />
                <div style={{ textAlign: 'center' }}>
                  <h3 style={{ margin: '0 0 6px 0', fontSize: '1rem' }}>Dispatching Report</h3>
                  <p className="text-muted" style={{ fontSize: '0.8rem', margin: 0 }}>Compiling overlap models and sending to {emailDraft.to}...</p>
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
