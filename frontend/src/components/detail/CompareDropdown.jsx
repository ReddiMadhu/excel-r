import { useState, useRef, useEffect } from 'react';
import { GitCompare, ChevronDown, Trash2, GitMerge, AlertCircle, Check } from 'lucide-react';

/**
 * CompareDropdown — Multi-select checkbox dropdown for picking candidate
 * reports to compare against the Target.
 *
 * Props:
 *   candidates   – Array of { workbook_id, workbook_name, cluster_role }
 *   selectedIds  – Set<number> of currently-selected workbook IDs
 *   onToggle     – (workbookId: number) => void
 *   primaryId    – The sidebar-selected workbook ID (always checked & listed first)
 */
export default function CompareDropdown({ candidates, selectedIds, onToggle, primaryId }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  if (!candidates || candidates.length === 0) return null;

  // Sort: primary first, then alphabetical
  const sorted = [...candidates].sort((a, b) => {
    if (a.workbook_id === primaryId) return -1;
    if (b.workbook_id === primaryId) return 1;
    return (a.workbook_name || '').localeCompare(b.workbook_name || '');
  });

  const selectedCount = selectedIds.size;

  const getRoleInfo = (role) => {
    if (role === 'decommission') return { icon: Trash2, label: 'Archive', color: 'var(--accent-rose)' };
    if (role === 'merge_source') return { icon: GitMerge, label: 'Merge', color: 'var(--accent-amber)' };
    return { icon: AlertCircle, label: 'Review', color: 'var(--text-muted)' };
  };

  return (
    <div className="compare-dropdown-container" ref={ref}>
      <button
        className={`compare-dropdown-trigger ${open ? 'active' : ''} ${selectedCount > 1 ? 'comparing' : ''}`}
        onClick={() => setOpen(!open)}
      >
        <GitCompare size={14} />
        <span>Compare Reports</span>
        {selectedCount > 1 && (
          <span className="compare-dropdown-badge">{selectedCount}</span>
        )}
        <ChevronDown size={13} className={`compare-dropdown-chevron ${open ? 'open' : ''}`} />
      </button>

      {open && (
        <div className="compare-dropdown-popover">
          <div className="compare-dropdown-header">
            <span>Select reports to compare</span>
            <span className="compare-dropdown-hint">{selectedCount} selected</span>
          </div>
          <div className="compare-dropdown-list">
            {sorted.map(c => {
              const isChecked = selectedIds.has(c.workbook_id);
              const isPrimary = c.workbook_id === primaryId;
              const roleInfo = getRoleInfo(c.cluster_role);
              const RoleIcon = roleInfo.icon;

              return (
                <label
                  key={c.workbook_id}
                  className={`compare-dropdown-item ${isChecked ? 'checked' : ''} ${isPrimary ? 'primary' : ''}`}
                >
                  <span className={`compare-checkbox ${isChecked ? 'checked' : ''}`}>
                    {isChecked && <Check size={10} />}
                  </span>
                  <RoleIcon size={12} style={{ color: roleInfo.color, flexShrink: 0 }} />
                  <span className="compare-dropdown-name" title={c.workbook_name}>
                    {c.workbook_name}
                  </span>
                  <span className="compare-dropdown-role-badge" style={{
                    color: roleInfo.color,
                    background: `color-mix(in srgb, ${roleInfo.color} 10%, transparent)`,
                  }}>
                    {roleInfo.label}
                  </span>
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => onToggle(c.workbook_id)}
                    style={{ display: 'none' }}
                  />
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
