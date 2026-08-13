import { useMemo, useState } from 'react';
import ReactDOM from 'react-dom';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, GitMerge, Trash2, CheckCircle, TrendingUp, Sparkles, Mail, X, FileDown, Target, AlertTriangle,
} from 'lucide-react';
import { jsPDF } from 'jspdf';
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

export default function RationalizationDetailView() {
  const { type, id } = useParams();
  const navigate = useNavigate();
  const workbookId = parseInt(id, 10);

  // Email Modal & Draft states
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [emailDraft, setEmailDraft] = useState({ to: '', subject: '', body: '' });
  const [emailStep, setEmailStep] = useState('input'); // 'input' | 'sending' | 'success' | 'error'
  const [emailMessage, setEmailMessage] = useState('');

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

  // Intelligence to determine consolidation destination (Target) vs merge candidate (Source)
  const isRecConsolidationTarget = useMemo(() => {
    if (!target) return true;
    const recKpis = sourceKpis.length;
    const targetKpisLen = targetKpis.length;
    if (recKpis !== targetKpisLen) {
      return recKpis > targetKpisLen;
    }
    // 2. Compare Data Source counts
    const recDs = rec.ds_sources_count || 0;
    const targetDs = target.ds_sources_count || 0;
    if (recDs !== targetDs) {
      return recDs > targetDs;
    }
    // 3. Compare Quality Score
    const recQuality = rec.scores?.extraction_quality_score || 0;
    const targetQuality = target.scores?.extraction_quality_score || 0;
    if (recQuality !== targetQuality) {
      return recQuality > targetQuality;
    }
    return rec.workbook_id < target.workbook_id;
  }, [rec, target, sourceKpis, targetKpis]);

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

  const downloadRationalisationPDF = () => {
    const doc = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4'
    });

    const pageHeight = 297;
    const pageWidth = 210;
    const marginX = 18;
    const contentWidth = pageWidth - (marginX * 2);
    let y = 20;

    const checkPageBreak = (neededHeight) => {
      if (y + neededHeight > pageHeight - 22) {
        doc.addPage();
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(7);
        doc.setTextColor(160, 170, 180);
        doc.text(`${rec.workbook_name} - ${config.title}`, marginX, 10);
        doc.setDrawColor(226, 232, 240);
        doc.line(marginX, 12, pageWidth - marginX, 12);
        y = 18;
      }
    };

    const addParagraph = (text, fontSize = 9.5, isBold = false, color = [51, 65, 85]) => {
      doc.setFont('helvetica', isBold ? 'bold' : 'normal');
      doc.setFontSize(fontSize);
      doc.setTextColor(color[0], color[1], color[2]);
      const lines = doc.splitTextToSize(text, contentWidth);
      const lineHeight = fontSize * 0.42;
      lines.forEach(line => {
        checkPageBreak(lineHeight + 1);
        doc.text(line, marginX, y);
        y += lineHeight;
      });
      y += 1.5;
    };

    const addSectionTitle = (title) => {
      checkPageBreak(14);
      y += 3;
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(11);
      doc.setTextColor(15, 23, 42);
      doc.text(title, marginX, y);
      y += 1.5;
      doc.setDrawColor(200, 210, 220);
      doc.line(marginX, y, pageWidth - marginX, y);
      y += 4;
    };

    const addBullet = (text, bulletColor = [100, 116, 139]) => {
      checkPageBreak(7);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(9.5);
      doc.setTextColor(bulletColor[0], bulletColor[1], bulletColor[2]);
      doc.text('-', marginX + 2, y);
      doc.setTextColor(51, 65, 85);
      const lines = doc.splitTextToSize(text, contentWidth - 8);
      const lh = 9.5 * 0.42;
      lines.forEach((line, idx) => {
        if (idx > 0) checkPageBreak(lh + 1);
        doc.text(line, marginX + 7, y);
        if (idx < lines.length - 1) y += lh;
      });
      y += lh + 1.5;
    };

    // ── Determine action label & color ──
    let actionText = '';
    let actionColor = [100, 116, 139];
    if (type === 'merge') {
      actionText = `Consolidation Merge -> ${rec.merge_with_name || 'Target Report'}`;
      actionColor = [217, 119, 6];
    } else if (type === 'decommission') {
      actionText = 'Decommission / Archive';
      actionColor = [225, 29, 72];
    } else {
      actionText = 'Keep';
      actionColor = [5, 150, 105];
    }

    // ═══════════════════════════════════════════
    // PAGE 1: Header Banner
    // ═══════════════════════════════════════════
    doc.setFillColor(30, 41, 59);
    doc.rect(0, 0, pageWidth, 36, 'F');
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(16);
    doc.setTextColor(255, 255, 255);
    doc.text(config.title, marginX, 16);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8.5);
    doc.setTextColor(200, 210, 225);
    const dateStr = new Date().toLocaleDateString('en-US', {
      year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
    doc.text(`Generated: ${dateStr}`, marginX, 24);
    doc.text(config.subtitle.length > 100 ? config.subtitle.substring(0, 100) + '...' : config.subtitle, marginX, 30);
    y = 44;

    // ── Report Identification Card ──
    checkPageBreak(28);
    doc.setFillColor(245, 247, 250);
    doc.setDrawColor(210, 218, 228);
    doc.roundedRect(marginX, y, contentWidth, 22, 2, 2, 'FD');
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10.5);
    doc.setTextColor(30, 41, 59);
    doc.text(`Report: ${rec.workbook_name}`, marginX + 5, y + 8);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(9.5);
    doc.setTextColor(actionColor[0], actionColor[1], actionColor[2]);
    doc.text(`Recommended Action: ${actionText}`, marginX + 5, y + 16);
    y += 28;

    // ── Overlap Scores Summary Table ──
    if (type === 'merge' || type === 'decommission') {
      addSectionTitle('Overlap Analysis Summary');
      const colW = contentWidth / 3;
      const scoreData = [
        { label: 'KPI Overlap', val: `${leftKpiCoverage}%`, note: `${sharedCount} of ${leftTotalKpis} KPIs` },
        { label: 'Data Source Overlap', val: `${leftDsCoverage}%`, note: `${sharedDsCount} of ${leftDsCount || '?'} sources` },
        { label: 'Unique KPIs', val: `${leftUniquePct}%`, note: `${leftOnlyKpis.length} unique` },
      ];
      const boxY = y;
      scoreData.forEach((s, idx) => {
        const bx = marginX + idx * colW;
        doc.setFillColor(248, 250, 252);
        doc.setDrawColor(220, 225, 235);
        doc.roundedRect(bx, boxY, colW - 3, 22, 1.5, 1.5, 'FD');
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(7.5);
        doc.setTextColor(100, 116, 139);
        doc.text(s.label, bx + 4, boxY + 6);
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(14);
        doc.setTextColor(30, 41, 59);
        doc.text(s.val, bx + 4, boxY + 15);
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(7);
        doc.setTextColor(120, 130, 145);
        doc.text(s.note, bx + 4, boxY + 20);
      });
      y = boxY + 28;
    }

    // ── Executive Justification ──
    if (rec.llm_justification) {
      addSectionTitle('Executive Justification');
      addParagraph(rec.llm_justification, 9.5, false, [51, 65, 85]);
      y += 2;
    }

    // ── Source Report Column ──
    addSectionTitle(type === 'merge' ? `Source - Merge Candidate: ${leftRec.workbook_name}` : type === 'decommission' ? `Decommission Candidate: ${leftRec.workbook_name}` : `Report: ${leftRec.workbook_name}`);

    if (type === 'merge' || type === 'decommission') {
      addParagraph(`Compared with: ${rightRec ? rightRec.workbook_name : 'N/A'}`, 9, true, [71, 85, 105]);
      addParagraph(`KPI Overlap: ${leftKpiCoverage}% (${sharedCount} of ${leftTotalKpis} KPIs)   |   DS Overlap: ${leftDsCoverage}%   |   Unique KPIs: ${leftUniquePct}% (${leftOnlyKpis.length})`, 8.5, false, [71, 85, 105]);
      y += 2;
    }

    // Source Governance Rationale
    if (leftReasons && leftReasons.length > 0) {
      checkPageBreak(10);
      addParagraph(type === 'decommission' ? 'Cleanliness Violations:' : 'Governance Rationale:', 9.5, true, [30, 41, 59]);
      leftReasons.forEach(r => addBullet(r, actionColor));
      y += 1;
    }

    // Source AI Justification
    if (type !== 'decommission' && leftRec.llm_justification) {
      checkPageBreak(10);
      addParagraph('AI Justification:', 9, true, [100, 80, 200]);
      addParagraph(leftRec.llm_justification, 9, false, [80, 90, 110]);
      y += 1;
    }

    // Source KPIs
    if (sharedKpis.length > 0 || leftOnlyKpis.length > 0) {
      checkPageBreak(10);
      addParagraph(`KPIs (${leftKpis.length} total):`, 9.5, true, [30, 41, 59]);
      sharedKpis.forEach(k => addBullet(`${k}  [SHARED]`, [5, 150, 105]));
      leftOnlyKpis.forEach(k => addBullet(k, [100, 116, 139]));
      y += 2;
    }

    // ── Target Report Column (for merge/decommission) ──
    if ((type === 'merge' || (type === 'decommission' && rec.merge_with_name)) && rightRec) {
      addSectionTitle(type === 'merge' ? `Target - Consolidation Destination: ${rightRec.workbook_name}` : `Retain Target: ${rightRec.workbook_name}`);

      addParagraph(`Compared with: ${leftRec.workbook_name}`, 9, true, [71, 85, 105]);
      addParagraph(`KPI Overlap: ${rightKpiCoverage}% (${sharedCount} of ${rightTotalKpis} KPIs)   |   DS Overlap: ${rightDsCoverage}%   |   Unique KPIs: ${rightUniquePct}% (${rightOnlyKpis.length})`, 8.5, false, [71, 85, 105]);
      y += 2;

      // Target Rationale
      if (rightReasons && rightReasons.length > 0) {
        addParagraph('Target Rationale:', 9.5, true, [30, 41, 59]);
        rightReasons.forEach(r => addBullet(r, [5, 150, 105]));
        y += 1;
      }

      // Target KPIs
      if (sharedKpis.length > 0 || rightOnlyKpis.length > 0) {
        addParagraph(`KPIs (${rightKpis.length} total):`, 9.5, true, [30, 41, 59]);
        sharedKpis.forEach(k => addBullet(`${k}  [SHARED]`, [5, 150, 105]));
        rightOnlyKpis.forEach(k => addBullet(k, [100, 116, 139]));
        y += 2;
      }
    }

    // ── Affected Audience & Stakeholders ──
    addSectionTitle('Affected Audience & Stakeholders');
    const audienceGroups = rec.user_groups && rec.user_groups.length > 0
      ? rec.user_groups.join(', ')
      : 'No specific audience groups registered.';
    addParagraph(audienceGroups, 9.5, false, [51, 65, 85]);
    y += 2;

    // ── KPIs Full Catalog ──
    addSectionTitle('Mapped Key Performance Indicators (KPIs)');
    if (sourceKpis.length > 0) {
      addParagraph(`Total Mapped KPIs: ${sourceKpis.length}`, 9.5, true, [30, 41, 59]);
      addParagraph(sourceKpis.join(', '), 8.5, false, [71, 85, 105]);
    } else {
      addParagraph('No registered KPIs detected for this report.', 9.5, false, [120, 130, 145]);
    }
    y += 2;

    // ── Database Lineage ──
    addSectionTitle('Database Lineage & Source Tables');
    const sourceTablesList = rec.tables || [];
    if (sourceTablesList.length > 0) {
      addParagraph(`Referenced Data Tables: ${sourceTablesList.length}`, 9.5, true, [30, 41, 59]);
      addParagraph(sourceTablesList.join(', '), 8.5, false, [71, 85, 105]);
    } else {
      addParagraph('No direct database lineage references detected.', 9.5, false, [120, 130, 145]);
    }
    y += 2;

    // ── Common Data Sources (for merge/decommission) ──
    if ((type === 'merge' || type === 'decommission') && rec.common_datasources && rec.common_datasources.length > 0) {
      addSectionTitle('Common Data Sources');
      addParagraph(`${rec.common_datasources.length} shared data sources between reports:`, 9.5, true, [30, 41, 59]);
      addParagraph(rec.common_datasources.join(', '), 8.5, false, [71, 85, 105]);
      y += 2;
    }

    // ── Common KPIs (for merge/decommission) ──
    if ((type === 'merge' || type === 'decommission') && rec.common_kpis && rec.common_kpis.length > 0) {
      addSectionTitle('Common KPIs Between Reports');
      addParagraph(`${rec.common_kpis.length} shared KPIs:`, 9.5, true, [30, 41, 59]);
      addParagraph(rec.common_kpis.join(', '), 8.5, false, [71, 85, 105]);
      y += 2;
    }

    // ── Sheet Names ──
    if (rec.sheet_names && rec.sheet_names.length > 0) {
      addSectionTitle('Sheet Names');
      addParagraph(rec.sheet_names.join(', '), 9, false, [71, 85, 105]);
      y += 2;
    }

    // ── Quality Scores ──
    if (rec.scores) {
      addSectionTitle('Quality & Extraction Scores');
      const s = rec.scores;
      const scoreLines = [];
      if (s.extraction_quality_score != null) scoreLines.push(`Extraction Quality: ${(s.extraction_quality_score * 100).toFixed(0)}%`);
      if (s.extraction_complexity != null) scoreLines.push(`Extraction Complexity: ${s.extraction_complexity}`);
      if (s.structural_risk != null) scoreLines.push(`Structural Risk: ${s.structural_risk}`);
      if (s.computation_depth != null) scoreLines.push(`Computation Depth: ${s.computation_depth}`);
      if (s.comparison_mode) scoreLines.push(`Comparison Mode: ${s.comparison_mode}`);
      if (rec.kpi_overlap_score != null) scoreLines.push(`KPI Overlap Score: ${(rec.kpi_overlap_score * 100).toFixed(1)}%`);
      if (rec.datasource_overlap_score != null) scoreLines.push(`Datasource Overlap Score: ${(rec.datasource_overlap_score * 100).toFixed(1)}%`);
      if (rec.uniqueness_score != null) scoreLines.push(`Uniqueness Score: ${(rec.uniqueness_score * 100).toFixed(1)}%`);
      if (scoreLines.length > 0) {
        addParagraph(scoreLines.join('   |   '), 8.5, false, [71, 85, 105]);
      }
      y += 2;
    }

    // ── Page Numbers ──
    const pageCount = doc.internal.getNumberOfPages();
    for (let i = 1; i <= pageCount; i++) {
      doc.setPage(i);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(7.5);
      doc.setTextColor(160, 170, 185);
      doc.text(`Page ${i} of ${pageCount}`, pageWidth - marginX - 18, pageHeight - 8);
    }

    const cleanName = rec.workbook_name.replace(/[^a-z0-9]/gi, '_').toLowerCase();
    doc.save(`governance_report_${cleanName}.pdf`);
  };

  const handleOpenEmailModal = () => {
    const draft = generateDefaultEmailDraft(rec, type, sourceKpis);
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



  const swapColumns = type === 'merge' && !!target && isRecConsolidationTarget;

  const leftRec = swapColumns ? target : rec;
  const rightRec = swapColumns ? rec : target;

  const leftKpis = swapColumns ? targetKpis : sourceKpis;
  const rightKpis = swapColumns ? sourceKpis : targetKpis;

  const leftTotalKpis = leftKpis.length;
  const rightTotalKpis = rightKpis.length;

  const leftOnlyKpis = swapColumns ? targetOnlyKpis : sourceOnlyKpis;
  const rightOnlyKpis = swapColumns ? sourceOnlyKpis : targetOnlyKpis;

  const leftUniquePct = swapColumns ? targetUniquePct : sourceUniquePct;
  const rightUniquePct = swapColumns ? sourceUniquePct : targetUniquePct;

  const leftDsCount = swapColumns ? targetDsCount : sourceDsCount;
  const rightDsCount = swapColumns ? sourceDsCount : targetDsCount;

  const leftDsCoverage = swapColumns ? targetDsCoverage : sourceDsCoverage;
  const rightDsCoverage = swapColumns ? sourceDsCoverage : targetDsCoverage;

  const leftKpiCoverage = swapColumns ? targetKpiCoverage : sourceKpiCoverage;
  const rightKpiCoverage = swapColumns ? sourceKpiCoverage : targetKpiCoverage;

  const leftReasons = swapColumns ? (rightRec ? cleanReasons(rightRec.reasons) : []) : reasons;
  const rightReasons = swapColumns ? reasons : (rightRec ? cleanReasons(rightRec.reasons) : []);



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
      icon: CheckCircle,
      title: 'Keep Review',
      subtitle: 'Review KPIs, data sources, and governance status of this report.',
      color: 'var(--accent-emerald)',
      iconClass: 'keep',
    },
    review: {
      icon: AlertTriangle,
      title: 'Governance Review',
      subtitle: 'Ambiguous portfolio overlap or low extraction quality — not cell-level Excel Review. Inspect reasons, scores, and fingerprints before deciding.',
      color: '#3b82f6',
      iconClass: 'review',
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
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={downloadRationalisationPDF}
            className="btn btn-ghost"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: '0.85rem',
              padding: '6px 12px',
              cursor: 'pointer',
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
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: '0.85rem',
              padding: '6px 12px',
              cursor: 'pointer'
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
                 'Report'}
              </span>
              <h2 className="review-detail-col-name">{leftRec.workbook_name}</h2>
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
                  <span className="review-detail-score-note">{sharedCount} of {leftTotalKpis} KPIs</span>
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
                  <span className="review-detail-score-note">{sharedDsCount} of {leftDsCount || '?'} columns</span>
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
                  <span className="review-detail-score-note">{leftOnlyKpis.length} only in this report</span>
                </div>
              </div>
            </div>

            {/* KPIs */}
            {(sharedKpis.length > 0 || leftOnlyKpis.length > 0) && (
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
                  {leftOnlyKpis.map((k, i) => (
                    <div key={`source-${i}`} className="review-detail-kpi-item">
                      <span>{k}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Rationale (for non-decommission actions) */}
            {type !== 'decommission' && leftReasons.length > 0 && (
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

            {/* AI Justification (for non-decommission actions) */}
            {type !== 'decommission' && leftRec.llm_justification && (
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
                      Compared with "{leftRec.workbook_name}"
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
                        <span className="review-detail-score-note">{sharedCount} of {rightTotalKpis} KPIs</span>
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
                        <span className="review-detail-score-note">{sharedDsCount} of {rightDsCount || '?'} columns</span>
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
                        <span className="review-detail-score-note">{rightOnlyKpis.length} only in this report</span>
                      </div>
                    </div>
                  </div>

                  {(sharedKpis.length > 0 || rightOnlyKpis.length > 0) && (
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
                        {rightOnlyKpis.map((k, i) => (
                          <div key={`target-only-${i}`} className="review-detail-kpi-item">
                            <span>{k}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {rightReasons.length > 0 && (
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
        </div>

        {/* Decommission Rationale section removed and moved to heading subtext */}

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

      {/* Email dispatch Modal — rendered via Portal to escape CSS transform containing block */}
      {emailModalOpen && ReactDOM.createPortal(
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
                
                {/* To Recipient */}
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

                {/* Subject */}
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

                {/* Body */}
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
        </div>,
        document.body
      )}
    </div>
  );
}
