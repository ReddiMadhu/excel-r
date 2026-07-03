import { useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, GitMerge, Trash2, CheckCircle, TrendingUp, Sparkles, Mail, X, FileDown,
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

We have analyzed the BI reporting landscape and identified significant metric and layout overlap. We recommend merging the report "${rec.workbook_name}" into "${rec.merge_with_name || 'the target certified report'}".

Recommended Action: Consolidate and merge into ${rec.merge_with_name || 'Target Certified Report'}

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
    subject = `[Governance Certification] Certification Keep Status: ${rec.workbook_name}`;
    body = `Hello Stakeholders,

We have audited the report "${rec.workbook_name}" and confirmed its status as a Certified Keep report.

Recommended Action: Certify and Keep Active

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
    const marginX = 20;
    const contentWidth = pageWidth - (marginX * 2); // 170 mm
    let y = 20;

    // Helper to check page bounds and auto-add new page
    const checkPageBreak = (neededHeight) => {
      if (y + neededHeight > pageHeight - 20) {
        doc.addPage();
        y = 20;
        // Draw minimal header on subsequent pages
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(8);
        doc.setTextColor(150, 150, 150);
        doc.text(`BI Governance Report: ${rec.workbook_name}`, marginX, 10);
        doc.line(marginX, 12, pageWidth - marginX, 12);
        y = 20;
      }
    };

    // Helper to add wrapped paragraph text
    const addParagraph = (text, fontSize = 10, isBold = false, color = [51, 65, 85]) => {
      doc.setFont('helvetica', isBold ? 'bold' : 'normal');
      doc.setFontSize(fontSize);
      doc.setTextColor(color[0], color[1], color[2]);
      
      const lines = doc.splitTextToSize(text, contentWidth);
      const lineHeight = fontSize * 0.45; // mm per line approx
      
      lines.forEach(line => {
        checkPageBreak(lineHeight);
        doc.text(line, marginX, y);
        y += lineHeight;
      });
      y += 2; // small space after paragraph
    };

    // 1. Draw Title Banner on first page
    doc.setFillColor(30, 41, 59); // Slate-800
    doc.rect(0, 0, pageWidth, 40, 'F');

    // Title Text
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(18);
    doc.setTextColor(255, 255, 255);
    doc.text('BI Governance & Rationalization Report', marginX, 18);

    // Subtitle
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.setTextColor(226, 232, 240); // Slate-200
    const dateStr = new Date().toLocaleDateString('en-US', {
      year: 'numeric', month: 'long', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
    doc.text(`Generated on ${dateStr} | System: Antigravity Governance Engine`, marginX, 26);

    // Reset colors and starting Y position
    y = 52;

    // Report Identification Card
    checkPageBreak(25);
    doc.setFillColor(248, 250, 252); // Slate-50 background for card
    doc.setDrawColor(226, 232, 240); // Slate-200 border
    doc.rect(marginX, y, contentWidth, 24, 'FD');
    
    // Card Text
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.setTextColor(30, 41, 59);
    doc.text(`Report name: ${rec.workbook_name}`, marginX + 6, y + 8);
    
    // Status action color
    let actionText = '';
    let actionColor = [100, 116, 139]; // Default grey
    if (type === 'merge') {
      actionText = `CONSOLIDATION MERGE (Merge into: ${rec.merge_with_name || 'Target Report'})`;
      actionColor = [217, 119, 6]; // Amber-600
    } else if (type === 'decommission') {
      actionText = 'DECOMMISSION / ARCHIVE';
      actionColor = [225, 29, 72]; // Rose-600
    } else {
      actionText = 'CERTIFIED KEEP';
      actionColor = [5, 150, 105]; // Emerald-600
    }
    
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10);
    doc.setTextColor(actionColor[0], actionColor[1], actionColor[2]);
    doc.text(`Recommended Action: ${actionText}`, marginX + 6, y + 16);

    y += 32;

    // 2. Section: Executive Justification
    if (rec.llm_justification) {
      checkPageBreak(15);
      addParagraph('Executive Justification', 12, true, [15, 23, 42]);
      doc.setDrawColor(226, 232, 240);
      doc.line(marginX, y - 1, pageWidth - marginX, y - 1);
      y += 3;
      addParagraph(rec.llm_justification, 10, false, [51, 65, 85]);
      y += 4;
    }

    // 3. Section: Governance Rationale & Cleanliness Violations
    const cleanReasonsList = cleanReasons(rec.reasons);
    if (cleanReasonsList.length > 0) {
      checkPageBreak(15);
      const titleText = type === 'decommission' ? 'Cleanliness Violations' : 'Governance Rationale';
      addParagraph(titleText, 12, true, [15, 23, 42]);
      doc.setDrawColor(226, 232, 240);
      doc.line(marginX, y - 1, pageWidth - marginX, y - 1);
      y += 3;

      cleanReasonsList.forEach(reason => {
        // Draw bullet
        checkPageBreak(8);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(actionColor[0], actionColor[1], actionColor[2]);
        doc.text('•', marginX + 2, y);
        
        doc.setFont('helvetica', 'normal');
        doc.setFontSize(10);
        doc.setTextColor(51, 65, 85);
        // Offset text slightly to not overlap bullet
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

    // 4. Section: Affected Audience Groups
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

    // 5. Section: KPI Catalog overlap
    checkPageBreak(15);
    addParagraph('Mapped Key Performance Indicators (KPIs)', 12, true, [15, 23, 42]);
    doc.setDrawColor(226, 232, 240);
    doc.line(marginX, y - 1, pageWidth - marginX, y - 1);
    y += 3;

    if (sourceKpis.length > 0) {
      const kpiText = sourceKpis.join(', ');
      addParagraph(`Total Mapped KPIs: ${sourceKpis.length}`, 10, true, [30, 41, 59]);
      addParagraph(kpiText, 9, false, [71, 85, 105]);
    } else {
      addParagraph('No registered KPIs detected for this report.', 10, false, [100, 116, 139]);
    }
    y += 4;

    // 6. Section: Database Lineage & Schema Connections
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

    // Footer on final page (and page numbers on all)
    const pageCount = doc.internal.getNumberOfPages();
    for (let i = 1; i <= pageCount; i++) {
      doc.setPage(i);
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(8);
      doc.setTextColor(148, 163, 184); // slate-400
      doc.text(`Page ${i} of ${pageCount}`, pageWidth - marginX - 15, pageHeight - 10);
      doc.text('CONFIDENTIAL - FOR INTERNAL BI GOVERNANCE USE ONLY', marginX, pageHeight - 10);
    }

    // Trigger download
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
                 'Certified Report'}
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
                  <span className="review-detail-score-label">KPIs Covered</span>
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
                  <span className="review-detail-score-label">DS Columns Covered</span>
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
                        <span className="review-detail-score-label">KPIs Covered</span>
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
                        <span className="review-detail-score-label">DS Columns Covered</span>
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
        </div>
      )}
    </div>
  );
}
