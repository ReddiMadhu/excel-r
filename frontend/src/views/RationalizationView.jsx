import { useMemo } from 'react';
import { CheckCircle, GitMerge, Trash2, AlertCircle } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { StatCard, Badge, Loader, EmptyState } from '../components/shared';

export default function RationalizationView() {
  const { data: recs, loading } = useApi(api.getRecommendations);
  const { data: pairwise, loading: pwLoading } = useApi(api.getPairwiseMatrix);

  const counts = useMemo(() => {
    if (!recs) return { keep: 0, merge: 0, decommission: 0, review: 0 };
    return {
      keep: recs.filter(r => r.action === 'keep').length,
      merge: recs.filter(r => r.action === 'merge').length,
      decommission: recs.filter(r => r.action === 'decommission' || r.action === 'delete').length,
      review: recs.filter(r => r.action === 'review').length,
    };
  }, [recs]);

  if (loading) return <Loader />;

  return (
    <div className="page-enter">
      <h1 style={{ marginBottom: 24 }}>Rationalization Results</h1>

      <div className="stat-grid">
        <StatCard icon={CheckCircle} value={counts.keep} label="Keep" color="emerald" />
        <StatCard icon={GitMerge} value={counts.merge} label="Merge" color="amber" />
        <StatCard icon={Trash2} value={counts.decommission} label="Decommission" color="rose" />
        <StatCard icon={AlertCircle} value={counts.review} label="Review" color="blue" />
      </div>

      {(!recs || recs.length === 0) ? (
        <EmptyState
          icon={GitMerge}
          title="No recommendations yet"
          message="Upload multiple workbooks and the rationalization engine will produce recommendations."
        />
      ) : (
        <div>
          {pairwise && pairwise.workbooks?.length > 1 && (
            <div className="card" style={{ marginBottom: 24 }}>
              <h3 style={{ marginBottom: 16 }}>KPI Overlap Matrix</h3>
              {pwLoading ? <Loader /> : (
                <OverlapHeatmap
                  workbooks={pairwise.workbooks}
                  pairs={pairwise.pairs}
                />
              )}
            </div>
          )}

          {['decommission', 'delete', 'merge', 'review', 'keep'].map(action => {
            const group = recs.filter(r => r.action === action);
            if (!group.length) return null;
            return (
              <div key={action} style={{ marginBottom: 24 }}>
                <h3 className="section-title" style={{ marginBottom: 12 }}>
                  {action.toUpperCase()} — {group.length} workbook{group.length > 1 ? 's' : ''}
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {group.map(rec => (
                    <RecommendationCard key={rec.id} rec={rec} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

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
    if (val >= 0.7) return 'rgba(244, 63, 94, 0.7)';
    if (val >= 0.4) return 'rgba(245, 158, 11, 0.6)';
    if (val > 0) return 'rgba(59, 130, 246, 0.3)';
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

function RecommendationCard({ rec }) {
  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <h3 style={{ fontSize: '1rem' }}>{rec.workbook_name}</h3>
            <Badge action={rec.action} />
            {rec.llm_override && <span className="badge badge-purple">AI Override</span>}
          </div>

          {rec.scores?.comparison_mode && (
            <p className="text-muted" style={{ fontSize: '0.75rem', marginBottom: 6 }}>
              Mode: {rec.scores.comparison_mode}
              {rec.scores.extraction_quality_score != null && (
                <> · Quality: {Math.round(rec.scores.extraction_quality_score * 100)}%</>
              )}
            </p>
          )}

          {rec.merge_with_name && (
            <p className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: 6 }}>
              <GitMerge size={14} style={{ verticalAlign: -2 }} />{' '}
              {rec.action === 'merge' ? 'Merge' : 'Compare'} with "{rec.merge_with_name}"
            </p>
          )}

          {rec.reasons && rec.reasons.map((reason, i) => (
            <p key={i} className="text-muted" style={{ fontSize: '0.8rem', marginBottom: 2 }}>
              {reason}
            </p>
          ))}

          {rec.llm_justification && (
            <p style={{ fontSize: '0.85rem', color: 'var(--accent-purple)', marginTop: 8, fontStyle: 'italic' }}>
              AI: {rec.llm_justification}
            </p>
          )}
        </div>

        <div style={{ textAlign: 'right', minWidth: 120 }}>
          <ScoreRow label="KPI Overlap" value={rec.kpi_overlap_score} />
          <ScoreRow label="DS Overlap" value={rec.datasource_overlap_score} />
          <ScoreRow label="Uniqueness" value={rec.uniqueness_score} inverse />
        </div>
      </div>

      {rec.common_kpis && rec.common_kpis.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--glass-border)' }}>
          <span className="text-muted" style={{ fontSize: '0.7rem' }}>Common KPIs: </span>
          {rec.common_kpis.map((k, i) => (
            <span key={i} className="badge badge-purple" style={{ marginRight: 4, marginTop: 2 }}>{k}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function ScoreRow({ label, value, inverse }) {
  const pct = (value || 0) * 100;
  const color = inverse
    ? (pct >= 60 ? 'var(--accent-emerald)' : pct >= 30 ? 'var(--accent-amber)' : 'var(--accent-rose)')
    : (pct >= 70 ? 'var(--accent-rose)' : pct >= 40 ? 'var(--accent-amber)' : 'var(--text-muted)');

  return (
    <div style={{ fontSize: '0.75rem', marginBottom: 4 }}>
      <span className="text-muted">{label}: </span>
      <span style={{ color, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}
