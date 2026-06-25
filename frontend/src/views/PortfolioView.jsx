import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileSpreadsheet, BarChart3, Database } from 'lucide-react';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { StatCard, Loader, EmptyState } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';

function WorkbookListCard({ wb, catalogEntry, onClick }) {
  const entry = catalogEntry || {};

  return (
    <div className="card card-clickable" onClick={onClick}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6, flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0 }}>{wb.name}</h3>
        </div>
        <p className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: 8 }}>
          {wb.sheet_count} sheets &middot; {wb.calculated_field_count || 0} calc fields
          &middot; {wb.datasource_count || 0} datasources
          {wb.has_vba_macros && <> &middot; <span style={{ color: 'var(--accent-rose)' }}>VBA</span></>}
        </p>
        {(wb.purpose || entry.purpose) && (
          <p className="text-muted" style={{ fontSize: '0.8rem' }}>{entry.purpose || wb.purpose}</p>
        )}
      </div>
    </div>
  );
}

export default function PortfolioView() {
  const navigate = useNavigate();
  const { data: workbooks, loading: wbLoading } = useApi(api.getWorkbooks);
  const { data: catalog, loading: catalogLoading } = useApi(api.getBusinessCatalog);

  const catalogMap = useMemo(() => {
    const map = {};
    (catalog?.workbooks || []).forEach(wb => { map[wb.id] = wb; });
    return map;
  }, [catalog]);

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
        <StatCard icon={FileSpreadsheet} value={(workbooks || []).length} label="Reports" color="blue" />
        <StatCard icon={BarChart3} value={totalSheets} label="Sheets" color="purple" />
        <StatCard icon={Database} value={totalDatasources} label="Datasources" color="emerald" />
      </div>

      {(!workbooks || workbooks.length === 0) ? (
        <EmptyState
          icon={FileSpreadsheet}
          title="No reports yet"
          message="Upload Excel files to get started with rationalization."
        />
      ) : (
        <div className="portfolio-list">
          {workbooks.map(wb => (
            <WorkbookListCard
              key={wb.id}
              wb={wb}
              catalogEntry={catalogMap[wb.id]}
              onClick={() => navigate(`/workbooks/${wb.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
