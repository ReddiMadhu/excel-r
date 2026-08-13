import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, CheckCircle, FileWarning, Search, RefreshCw, XCircle,
} from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { Loader, EmptyState, StatCard } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';

const TYPE_LABELS = {
  HARDCODED_OVERRIDE: 'Hardcoded Override',
  FORMULA_INCONSISTENCY: 'Formula Inconsistency',
  BROKEN_REF: 'Broken Reference',
  EXTERNAL_DEPENDENCY: 'External Dependency',
  UNSUPPORTED_FEATURE: 'Unsupported Feature',
  DEGRADED_LINEAGE: 'Degraded Lineage',
  STRUCTURAL_RISK: 'Structural Risk',
};

function severityClass(sev) {
  if (sev === 'HIGH') return 'badge-rose';
  if (sev === 'MEDIUM') return 'badge-amber';
  return 'badge-blue';
}

export default function ExcelReviewView() {
  const { data: findings, loading, error, refetch } = useApi(api.getExcelReviewFindings);
  const { data: summary, loading: sumLoading } = useApi(api.getExcelReviewSummary);
  const { data: agents } = useApi(api.getAgentsStatus);
  const navigate = useNavigate();

  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [running, setRunning] = useState(false);
  const [runMsg, setRunMsg] = useState('');

  const rationStatus = agents?.rationalization?.status;
  const discoveryStatus = agents?.discovery?.status;

  const filtered = useMemo(() => {
    let rows = findings || [];
    if (typeFilter !== 'all') {
      rows = rows.filter(f => f.finding_type === typeFilter || f.type === typeFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter(f =>
        (f.workbook_name || '').toLowerCase().includes(q)
        || (f.sheet || '').toLowerCase().includes(q)
        || (f.cell || '').toLowerCase().includes(q)
        || (f.actual || '').toLowerCase().includes(q)
        || (f.finding_type || '').toLowerCase().includes(q)
      );
    }
    return rows;
  }, [findings, search, typeFilter]);

  const handleRerun = async () => {
    setRunning(true);
    setRunMsg('');
    try {
      const res = await api.runExcelReview();
      setRunMsg(`Excel Review ${res.status}: ${res.findings ?? 0} finding(s)`);
      if (refetch) refetch();
      window.dispatchEvent(new Event('portfolio-updated'));
    } catch (e) {
      setRunMsg(e.message || 'Excel Review failed');
    } finally {
      setRunning(false);
    }
  };

  if (loading || sumLoading) return <Loader text="Loading Excel Review…" />;

  // Honest empty / error states — never conflate with "no issues"
  if (error) {
    return (
      <div>
        <PageHeader title="Excel Review" subtitle="Cell and formula inspection inside workbooks" />
        <div className="agent-run-banner tone-error" style={{ margin: '1rem 0', padding: '1rem' }}>
          <XCircle size={18} />
          <span>Analysis Failed: {error}</span>
          <button type="button" className="btn btn-sm" onClick={() => refetch?.()}>Retry</button>
        </div>
      </div>
    );
  }

  const count = (findings || []).length;
  const wbCount = summary?.workbooks ?? 0;
  const unsupported = (findings || []).some(f => f.finding_type === 'UNSUPPORTED_FEATURE');

  return (
    <div>
      <PageHeader
        title="Excel Review"
        subtitle="What inside each workbook a human analyst should inspect (not portfolio merge/keep)"
        actions={
          <button type="button" className="btn btn-secondary" onClick={handleRerun} disabled={running}>
            <RefreshCw size={14} className={running ? 'spin' : ''} />
            {running ? 'Running…' : 'Re-run Excel Review'}
          </button>
        }
      />

      {runMsg && (
        <div className="agent-run-banner" style={{ marginBottom: '1rem', padding: '0.75rem' }}>
          {runMsg}
        </div>
      )}

      {wbCount === 0 ? (
        <EmptyState
          icon={FileWarning}
          title="No workbooks uploaded"
          message="Upload Excel files via Discovery before Excel Review can run."
        />
      ) : (
        <>
          <div className="stats-row" style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <StatCard label="Findings" value={count} icon={AlertTriangle} />
            <StatCard label="Workbooks" value={wbCount} icon={CheckCircle} />
            <StatCard
              label="With findings"
              value={summary?.workbooks_with_findings ?? 0}
              icon={FileWarning}
            />
          </div>

          {unsupported && (
            <div className="agent-run-banner tone-warning" style={{ marginBottom: '1rem', padding: '0.75rem' }}>
              Workbook(s) contain unsupported Excel features — do not treat missing other findings as “safe”.
            </div>
          )}

          {count === 0 ? (
            <EmptyState
              icon={CheckCircle}
              title="No review findings detected"
              message={
                discoveryStatus === 'empty'
                  ? 'Upload workbooks first.'
                  : 'Excel Review completed and found no formula overrides, broken refs, or unsupported constructs in the scanned regions.'
              }
            />
          ) : (
            <>
              <div className="ration-toolbar" style={{ marginBottom: '1rem' }}>
                <div className="ration-search">
                  <Search size={14} />
                  <input
                    type="text"
                    placeholder="Search sheet, cell, workbook…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <select
                  className="ration-workbook-select"
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                >
                  <option value="all">All types</option>
                  {Object.keys(TYPE_LABELS).map(t => (
                    <option key={t} value={t}>{TYPE_LABELS[t]}</option>
                  ))}
                </select>
              </div>

              <p style={{ marginBottom: '0.75rem', opacity: 0.8 }}>
                {filtered.length} finding{filtered.length === 1 ? '' : 's'} requiring review
              </p>

              <div className="excel-review-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {filtered.map(f => (
                  <div
                    key={f.id}
                    className="rec-card"
                    style={{ padding: '1rem', cursor: 'pointer' }}
                    onClick={() => f.workbook_id && navigate(`/workbooks/${f.workbook_id}`)}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                      <div>
                        <strong>{TYPE_LABELS[f.finding_type] || f.finding_type}</strong>
                        <div style={{ fontSize: '0.85rem', opacity: 0.8, marginTop: 4 }}>
                          {f.workbook_name}
                          {f.sheet ? ` · ${f.sheet}` : ''}
                          {f.cell ? `!${f.cell}` : ''}
                        </div>
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
                        <span className={`badge ${severityClass(f.severity)}`}>{f.severity}</span>
                        <span className="badge badge-blue">conf: {f.confidence}</span>
                      </div>
                    </div>
                    <div style={{ marginTop: '0.75rem', fontSize: '0.9rem' }}>
                      {f.actual != null && (
                        <div><strong>Actual:</strong> <code>{String(f.actual).slice(0, 200)}</code></div>
                      )}
                      {f.expected_pattern && (
                        <div><strong>Expected:</strong> <code>{String(f.expected_pattern).slice(0, 200)}</code></div>
                      )}
                    </div>
                    {Array.isArray(f.evidence) && f.evidence.length > 0 && (
                      <ul style={{ margin: '0.5rem 0 0', paddingLeft: '1.25rem', fontSize: '0.85rem' }}>
                        {f.evidence.slice(0, 4).map((e, i) => <li key={i}>{e}</li>)}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {rationStatus && rationStatus !== 'idle' && (
            <p style={{ marginTop: '1.5rem', fontSize: '0.8rem', opacity: 0.65 }}>
              Note: Portfolio Rationalization agent status is <code>{rationStatus}</code>.
              That is Governance Review (merge/keep), not Excel Review.
            </p>
          )}
        </>
      )}
    </div>
  );
}
