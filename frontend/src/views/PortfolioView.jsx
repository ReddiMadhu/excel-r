import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileSpreadsheet, BarChart3, Database, Building2, Users,
  GitCompare, ChevronDown, ChevronRight, List,
} from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { StatCard, Loader, EmptyState } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';

const VIEW_MODES = [
  { id: 'list', label: 'All Workbooks', icon: List },
  { id: 'lob', label: 'By LOB', icon: Building2 },
  { id: 'user_group', label: 'By Business', icon: Users },
];

function effectiveRecAction(wbId, rec, allRecs) {
  if (!rec) return null;
  const retainedBy = (allRecs || []).find(
    r => (r.action === 'decommission' || r.action === 'delete') && r.merge_with_id === wbId
  );
  if (retainedBy && retainedBy.workbook_id !== wbId) return 'keep';
  if (rec.action === 'decommission' || rec.action === 'delete') {
    const opposing = (allRecs || []).find(
      r => (r.action === 'decommission' || r.action === 'delete')
        && r.workbook_id === rec.merge_with_id && r.merge_with_id === wbId
    );
    if (opposing && (rec.uniqueness_score || 0) > (opposing.uniqueness_score || 0)) return 'keep';
  }
  return rec.action;
}

function shouldShowRecHint(wbId, rec, allRecs) {
  const action = effectiveRecAction(wbId, rec, allRecs);
  if (!rec || action === 'keep' || !rec.merge_with_name) return false;
  return true;
}

function primaryBusiness(entry) {
  return entry.primary_business_group || entry.user_groups?.[0] || null;
}

function WorkbookListCard({ wb, catalogEntry, rec, recommendations, onClick }) {
  const displayAction = effectiveRecAction(wb.id, rec, recommendations);
  const entry = catalogEntry || {};
  const mainLob = entry.line_of_business;
  const mainBusiness = primaryBusiness(entry);
  const suggested = entry.metadata_suggested;

  return (
    <div className="card card-clickable" onClick={onClick}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0 }}>{wb.name}</h3>
          {mainLob && (
            <span className={`badge badge-blue ${suggested ? 'badge-suggested' : ''}`} title={suggested ? 'Suggested from report' : undefined}>
              {mainLob}
            </span>
          )}
          {mainBusiness && (
            <span className={`badge badge-amber ${suggested ? 'badge-suggested' : ''}`} title={suggested ? 'Suggested from report' : undefined}>
              {mainBusiness}
            </span>
          )}
        </div>
        <p className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: 8 }}>
          {wb.sheet_count} sheets &middot; {wb.calculated_field_count || 0} calc fields
          &middot; {wb.datasource_count || 0} datasources
          {wb.has_vba_macros && <> &middot; <span style={{ color: 'var(--accent-rose)' }}>VBA</span></>}
        </p>
        {(wb.purpose || entry.purpose) && (
          <p className="text-muted" style={{ fontSize: '0.8rem' }}>{entry.purpose || wb.purpose}</p>
        )}
        {rec && shouldShowRecHint(wb.id, rec, recommendations) && (
          <p style={{ fontSize: '0.8rem', color: 'var(--accent-amber)', marginTop: 8 }}>
            <GitCompare size={13} style={{ verticalAlign: -2 }} />{' '}
            {displayAction === 'decommission'
              ? `Decommission → retain "${rec.merge_with_name}"`
              : displayAction === 'merge'
                ? `Merge with "${rec.merge_with_name}"`
                : `Related to "${rec.merge_with_name}"`}
            {rec.kpi_overlap_score > 0 && ` (${Math.round(rec.kpi_overlap_score * 100)}% KPI overlap)`}
          </p>
        )}
      </div>
    </div>
  );
}

function GroupSection({ title, subtitle, workbookIds, catalogMap, workbooks, recMap, recommendations, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const navigate = useNavigate();

  const items = workbookIds
    .map(id => {
      const wb = workbooks.find(w => w.id === id);
      if (!wb) return null;
      return { wb, catalogEntry: catalogMap[id] };
    })
    .filter(Boolean);

  if (items.length === 0) return null;

  return (
    <div className="portfolio-group card">
      <button
        type="button"
        className="portfolio-group-header"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <div className="portfolio-group-title">
          <div className="portfolio-group-name">{title}</div>
          {subtitle && <div className="portfolio-group-subtitle">{subtitle}</div>}
        </div>
        <span className="badge badge-blue">
          {items.length} workbook{items.length !== 1 ? 's' : ''}
        </span>
      </button>

      {open && (
        <div className="portfolio-group-body">
          {items.map(({ wb, catalogEntry }) => (
            <WorkbookListCard
              key={wb.id}
              wb={wb}
              catalogEntry={catalogEntry}
              rec={recMap[wb.id]}
              recommendations={recommendations}
              onClick={() => navigate(`/workbooks/${wb.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function PortfolioView() {
  const navigate = useNavigate();
  const { data: workbooks, loading: wbLoading } = useApi(api.getWorkbooks);
  const { data: catalog, loading: catalogLoading } = useApi(api.getBusinessCatalog);
  const { data: recommendations } = useApi(api.getRecommendations);
  const [viewMode, setViewMode] = useState('list');

  const catalogMap = useMemo(() => {
    const map = {};
    (catalog?.workbooks || []).forEach(wb => { map[wb.id] = wb; });
    return map;
  }, [catalog]);

  const recMap = useMemo(() => {
    const map = {};
    (recommendations || []).forEach(r => { map[r.workbook_id] = r; });
    return map;
  }, [recommendations]);

  const groups = useMemo(() => {
    if (!catalog || viewMode === 'list') return [];

    if (viewMode === 'user_group') {
      return (catalog.user_groups || []).map(name => ({
        key: name,
        title: name,
        subtitle: 'Primary business group',
        ids: catalog.by_user_group[name] || [],
      }));
    }

    const lobGroups = (catalog.lobs || []).map(name => ({
      key: name,
      title: name,
      subtitle: 'Primary line of business',
      ids: catalog.by_lob[name] || [],
    }));

    if (catalog.unclassified_workbook_ids?.length) {
      lobGroups.push({
        key: '__unclassified__',
        title: 'Unclassified',
        subtitle: 'No LOB suggested yet',
        ids: catalog.unclassified_workbook_ids,
      });
    }

    return lobGroups;
  }, [catalog, viewMode]);

  if (wbLoading || catalogLoading) return <Loader />;

  const totalSheets = (workbooks || []).reduce((s, w) => s + (w.sheet_count || 0), 0);
  const totalDatasources = (workbooks || []).reduce((s, w) => s + (w.datasource_count || 0), 0);

  return (
    <div className="page-enter">
      <PageHeader
        title="Portfolio Overview"
        actions={(
          <button className="btn btn-primary" onClick={() => navigate('/upload')}>
            <FileSpreadsheet size={16} /> Upload Files
          </button>
        )}
      />

      <div className="stat-grid">
        <StatCard icon={FileSpreadsheet} value={(workbooks || []).length} label="Workbooks" color="blue" />
        <StatCard icon={BarChart3} value={totalSheets} label="Sheets" color="purple" />
        <StatCard icon={Database} value={totalDatasources} label="Datasources" color="emerald" />
        <StatCard icon={Building2} value={catalog?.lobs?.length ?? 0} label="LOBs" color="amber" />
      </div>

      {(!workbooks || workbooks.length === 0) ? (
        <EmptyState
          icon={FileSpreadsheet}
          title="No workbooks yet"
          message="Upload Excel files to get started with rationalization."
        />
      ) : (
        <>
          <div className="portfolio-tabs" role="tablist" aria-label="Portfolio views">
            {VIEW_MODES.map(mode => {
              const Icon = mode.icon;
              const isActive = viewMode === mode.id;
              return (
                <button
                  key={mode.id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  className={`portfolio-tab ${isActive ? 'active' : ''}`}
                  onClick={() => setViewMode(mode.id)}
                >
                  <Icon size={14} />
                  {mode.label}
                </button>
              );
            })}
          </div>

          <div className="portfolio-tab-panel" role="tabpanel">
            {viewMode === 'list' ? (
              <div className="portfolio-list">
                {workbooks.map(wb => (
                  <WorkbookListCard
                    key={wb.id}
                    wb={wb}
                    catalogEntry={catalogMap[wb.id]}
                    rec={recMap[wb.id]}
                    recommendations={recommendations}
                    onClick={() => navigate(`/workbooks/${wb.id}`)}
                  />
                ))}
              </div>
            ) : groups.length === 0 ? (
              <div className="card portfolio-empty">
                <p className="text-secondary">
                  No {viewMode === 'user_group' ? 'business groups' : 'LOB classifications'} found yet.
                </p>
              </div>
            ) : (
              <div className="portfolio-groups">
                {groups.map((group, index) => (
                  <GroupSection
                    key={group.key}
                    title={group.title}
                    subtitle={group.subtitle}
                    workbookIds={group.ids}
                    catalogMap={catalogMap}
                    workbooks={workbooks}
                    recMap={recMap}
                    recommendations={recommendations}
                    defaultOpen={index === 0}
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
