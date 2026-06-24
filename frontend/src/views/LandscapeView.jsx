import { useState, useEffect, useMemo, useRef } from 'react';
import { ChevronDown, Check, X } from 'lucide-react';
import { api } from '../api/client';
import { Loader } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';
import { KPIDashboardGraph } from '../components/shared/KPIDashboardGraph';

export default function LandscapeView() {
  const [workbooks, setWorkbooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState([]); // empty = all
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const fetchWorkbooks = async () => {
      try {
        setLoading(true);
        const data = await api.getWorkbooks();
        setWorkbooks(data || []);
      } catch (err) {
        console.error('Failed to load workbooks:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchWorkbooks();
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const allIds = useMemo(() => workbooks.map(w => w.id), [workbooks]);

  // The IDs to pass to the graph: if none selected, pass all
  const graphWorkbookIds = useMemo(() => {
    if (selectedIds.length === 0) return allIds;
    return selectedIds;
  }, [selectedIds, allIds]);

  const isAllSelected = selectedIds.length === 0;

  const toggleWorkbook = (id) => {
    setSelectedIds(prev => {
      if (prev.includes(id)) {
        return prev.filter(x => x !== id);
      } else {
        return [...prev, id];
      }
    });
  };

  const selectAll = () => {
    setSelectedIds([]);
  };

  const clearSelection = () => {
    setSelectedIds([]);
  };

  // Label for dropdown trigger
  const dropdownLabel = useMemo(() => {
    if (isAllSelected) return 'All Reports';
    if (selectedIds.length === 1) {
      const wb = workbooks.find(w => w.id === selectedIds[0]);
      return wb ? wb.name : '1 Selected';
    }
    return `${selectedIds.length} Reports Selected`;
  }, [isAllSelected, selectedIds, workbooks]);

  if (loading) return <Loader />;

  return (
    <div className="page-enter" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <PageHeader
        title="BI Landscape Graph"
        subtitle="Interactive visualization of report lineage, KPI relationships, shared sources, and connections."
      />

      {/* Workbook Multi-Select Toolbar */}
      <div className="landscape-toolbar">
        <div className="landscape-toolbar-label">Reports:</div>
        <div className="landscape-multiselect" ref={dropdownRef}>
          <button
            className="landscape-multiselect-trigger"
            onClick={() => setDropdownOpen(!dropdownOpen)}
          >
            <span className="landscape-multiselect-text">{dropdownLabel}</span>
            <ChevronDown size={14} className={`landscape-chevron ${dropdownOpen ? 'open' : ''}`} />
          </button>

          {dropdownOpen && (
            <div className="landscape-multiselect-dropdown">
              {/* All option */}
              <label
                className={`landscape-multiselect-option ${isAllSelected ? 'selected' : ''}`}
                onClick={selectAll}
              >
                <span className={`landscape-checkbox ${isAllSelected ? 'checked' : ''}`}>
                  {isAllSelected && <Check size={10} />}
                </span>
                <span>All Reports</span>
              </label>

              <div className="landscape-multiselect-divider" />

              {/* Individual workbooks */}
              {workbooks.map(wb => {
                const checked = selectedIds.includes(wb.id);
                return (
                  <label
                    key={wb.id}
                    className={`landscape-multiselect-option ${checked ? 'selected' : ''}`}
                    onClick={() => toggleWorkbook(wb.id)}
                  >
                    <span className={`landscape-checkbox ${checked ? 'checked' : ''}`}>
                      {checked && <Check size={10} />}
                    </span>
                    <span>{wb.name}</span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        {/* Selected tags */}
        {!isAllSelected && (
          <div className="landscape-selected-tags">
            {selectedIds.map(id => {
              const wb = workbooks.find(w => w.id === id);
              return wb ? (
                <span key={id} className="landscape-tag">
                  {wb.name}
                  <button
                    className="landscape-tag-remove"
                    onClick={() => toggleWorkbook(id)}
                  >
                    <X size={10} />
                  </button>
                </span>
              ) : null;
            })}
            <button className="landscape-clear-btn" onClick={clearSelection}>
              Clear All
            </button>
          </div>
        )}
      </div>

      {/* Graph */}
      <div className="card" style={{ height: '650px', width: '100%', padding: '24px', display: 'flex', flexDirection: 'column' }}>
        {graphWorkbookIds.length > 0 ? (
          <KPIDashboardGraph
            workbookIds={graphWorkbookIds}
            view="landscape"
            height="100%"
            title="Report Relationship Map"
          />
        ) : (
          <div className="card" style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', flexDirection: 'column', gap: '12px', borderColor: 'var(--accent-rose)'
          }}>
            <p style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>No reports available.</p>
          </div>
        )}
      </div>
    </div>
  );
}
