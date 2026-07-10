import { useState } from 'react';
import { X, Target, Trash2, GitMerge, AlertCircle, Loader2 } from 'lucide-react';

/**
 * ChangeTargetModal — Human-in-the-loop modal for overriding the recommended target.
 *
 * Props:
 *   isOpen          – boolean
 *   onClose         – () => void
 *   onConfirm       – (newTargetId, reason) => Promise<void>
 *   members         – Array of cluster members from getClusterDetail
 *   currentTargetId – The current canonical_target_id
 *   loading         – boolean (saving state)
 */
export default function ChangeTargetModal({
  isOpen, onClose, onConfirm, members, currentTargetId, loading,
}) {
  const [selectedId, setSelectedId] = useState(currentTargetId);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const canSubmit = selectedId
    && selectedId !== currentTargetId
    && reason.trim().length >= 10
    && !loading;

  const getRoleInfo = (role) => {
    if (role === 'canonical_target') return { label: 'Current Target', color: 'var(--accent-emerald)', icon: Target };
    if (role === 'decommission') return { label: 'Archive', color: 'var(--accent-rose)', icon: Trash2 };
    if (role === 'merge_source') return { label: 'Merge', color: 'var(--accent-amber)', icon: GitMerge };
    return { label: 'Review', color: 'var(--text-muted)', icon: AlertCircle };
  };

  const handleSubmit = async () => {
    setError('');
    try {
      await onConfirm(selectedId, reason.trim());
    } catch (err) {
      setError(err.message || 'Failed to change target.');
    }
  };

  // Sort: current target first, then alphabetical
  const sorted = [...(members || [])].sort((a, b) => {
    if (a.workbook_id === currentTargetId) return -1;
    if (b.workbook_id === currentTargetId) return 1;
    return (a.workbook_name || '').localeCompare(b.workbook_name || '');
  });

  return (
    <div className="change-target-modal-backdrop" onClick={onClose}>
      <div className="change-target-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="change-target-header">
          <div className="change-target-header-left">
            <div className="change-target-header-icon">
              <Target size={18} />
            </div>
            <div>
              <h2 className="change-target-title">Change Recommended Target</h2>
              <p className="change-target-desc">
                Select a new target workbook for this consolidation group. All member roles will be re-assigned automatically.
              </p>
            </div>
          </div>
          <button className="change-target-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* Member List */}
        <div className="change-target-list">
          {sorted.map(m => {
            const isCurrentTarget = m.workbook_id === currentTargetId;
            const isSelected = m.workbook_id === selectedId;
            const roleInfo = getRoleInfo(m.cluster_role);
            const RoleIcon = roleInfo.icon;

            return (
              <label
                key={m.workbook_id}
                className={`change-target-member-row ${isCurrentTarget ? 'current' : ''} ${isSelected ? 'selected' : ''}`}
              >
                <input
                  type="radio"
                  name="target-selection"
                  checked={isSelected}
                  onChange={() => setSelectedId(m.workbook_id)}
                  className="change-target-radio"
                />
                <div className="change-target-member-info">
                  <span className="change-target-member-name">{m.workbook_name}</span>
                  <div className="change-target-member-meta">
                    <span className="change-target-meta-pill">{m.kpi_count || 0} KPIs</span>
                    <span className="change-target-meta-pill">{m.ds_count || 0} DS</span>
                    {m.extraction_quality_score != null && (
                      <span className="change-target-meta-pill quality">
                        Q: {Math.round(m.extraction_quality_score * 100)}%
                      </span>
                    )}
                  </div>
                </div>
                <span className="change-target-role-badge" style={{
                  color: roleInfo.color,
                  background: `color-mix(in srgb, ${roleInfo.color} 10%, transparent)`,
                }}>
                  <RoleIcon size={10} style={{ marginRight: 3 }} />
                  {roleInfo.label}
                </span>
              </label>
            );
          })}
        </div>

        {/* Rationale */}
        <div className="change-target-rationale-section">
          <label className="change-target-rationale-label">
            Override Rationale <span style={{ color: 'var(--accent-rose)' }}>*</span>
          </label>
          <textarea
            className="change-target-rationale"
            placeholder="Explain why this workbook should be the recommended target (min 10 characters)..."
            value={reason}
            onChange={e => setReason(e.target.value)}
            rows={3}
          />
          {reason.length > 0 && reason.trim().length < 10 && (
            <span className="change-target-rationale-hint">
              At least 10 characters required ({reason.trim().length}/10)
            </span>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="change-target-error">
            {error}
          </div>
        )}

        {/* Footer */}
        <div className="change-target-footer">
          <button className="btn btn-ghost" onClick={onClose} disabled={loading}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={!canSubmit}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            {loading ? <Loader2 size={14} className="spin" /> : <Target size={14} />}
            {loading ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
