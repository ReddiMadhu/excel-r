import { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import {
  ArrowLeft, AlertTriangle,
  Layers, Target, GitMerge, Trash2, AlertCircle, Pencil,
} from 'lucide-react';
import { Loader, EmptyState } from '../components/shared';
import ClusterMemberDetailPanel from '../components/detail/ClusterMemberDetailPanel';
import MultiComparePanel from '../components/detail/MultiComparePanel';
import CompareDropdown from '../components/detail/CompareDropdown';
import ChangeTargetModal from '../components/detail/ChangeTargetModal';
import './ClusterDetailView.css';

// ─── Detail View Component ─────────────────────────────────────

export default function ClusterDetailView() {
  const { clusterId } = useParams();
  const navigate = useNavigate();

  const [cluster, setCluster] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Sidebar state
  const [selectedWbId, setSelectedWbId] = useState(null);

  // Comparison state
  const [compareIds, setCompareIds] = useState(new Set());

  // Change Target modal state
  const [changeTargetOpen, setChangeTargetOpen] = useState(false);
  const [changingTarget, setChangingTarget] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const detail = await api.getClusterDetail(clusterId);
      setCluster(detail);
      // Default selected workbook is the golden target/canonical
      if (detail && detail.canonical_target_id) {
        setSelectedWbId(detail.canonical_target_id);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [clusterId]);

  // Index members and recommendations
  const workspaceData = useMemo(() => {
    if (!cluster) return null;
    const members = cluster.members || [];
    const recs = cluster.recommendations || [];

    const recMap = {};
    recs.forEach(r => { recMap[r.workbook_id] = r; });

    const target = members.find(m => m.workbook_id === cluster.canonical_target_id || m.cluster_role === 'canonical_target');
    const candidates = members.filter(m => m.workbook_id !== (target?.workbook_id || cluster.canonical_target_id));

    return { target, candidates, recMap };
  }, [cluster]);

  // Is the selected workbook the Target?
  const isTargetSelected = workspaceData?.target?.workbook_id === selectedWbId;

  // Is multi-compare mode active?
  const isCompareMode = compareIds.size >= 2 && !isTargetSelected;

  // When sidebar selection changes: reset comparison to just that one item
  const handleSidebarSelect = useCallback((wbId) => {
    setSelectedWbId(wbId);
    // If selecting target, clear comparison
    const targetId = workspaceData?.target?.workbook_id || cluster?.canonical_target_id;
    if (wbId === targetId) {
      setCompareIds(new Set());
    } else {
      setCompareIds(new Set([wbId]));
    }
  }, [workspaceData, cluster]);

  // Toggle a candidate in/out of comparison set
  const handleCompareToggle = useCallback((wbId) => {
    setCompareIds(prev => {
      const next = new Set(prev);
      if (next.has(wbId)) {
        // Don't let it drop below 1 (the sidebar-selected item stays)
        if (next.size > 1) next.delete(wbId);
      } else {
        next.add(wbId);
      }
      return next;
    });
  }, []);

  // Exit comparison mode: reset to just the sidebar-selected candidate
  const handleExitCompare = useCallback(() => {
    setCompareIds(new Set([selectedWbId]));
  }, [selectedWbId]);

  // Change Target confirm handler
  const handleChangeTargetConfirm = useCallback(async (newTargetId, reason) => {
    setChangingTarget(true);
    try {
      await api.changeClusterTarget(parseInt(clusterId, 10), newTargetId, reason);
      setChangeTargetOpen(false);
      // Reload cluster data and auto-select new target
      const detail = await api.getClusterDetail(clusterId);
      setCluster(detail);
      setSelectedWbId(newTargetId);
      setCompareIds(new Set());
    } catch (err) {
      throw err; // Let the modal handle the error
    } finally {
      setChangingTarget(false);
    }
  }, [clusterId]);

  if (loading) return <div className="page-enter"><Loader /></div>;

  if (error || !cluster || !workspaceData) return (
    <div className="page-enter">
      <EmptyState icon={AlertTriangle} title="Cluster not found" message={error || 'This cluster does not exist.'} />
    </div>
  );

  const target = workspaceData.target;

  return (
    <div className="workspace-page page-enter">
      {/* Back Button */}
      <button
        className="btn btn-ghost btn-sm"
        style={{ marginBottom: 16 }}
        onClick={() => navigate('/overlap-analysis')}
      >
        <ArrowLeft size={14} /> Back to Overlap Analysis
      </button>

      {/* Main Split Layout Workspace */}
      <div className="consolidation-workspace">
        
        {/* LEFT COLUMN: Sidebar Navigator */}
        <div className="workspace-sidebar card">
          <div className="sidebar-header">
            <Layers size={15} style={{ color: 'var(--accent-blue)' }} />
            <h4>Consolidation Group</h4>
          </div>

          <div className="sidebar-group">
            <div className="sidebar-group-title-row">
              <span className="sidebar-group-title">Recommended Target</span>
              <button
                className="sidebar-edit-btn"
                title="Change recommended target"
                onClick={() => setChangeTargetOpen(true)}
              >
                <Pencil size={11} />
              </button>
            </div>
            {target && (
              <button
                className={`sidebar-item target-item ${selectedWbId === target.workbook_id ? 'active' : ''}`}
                onClick={() => handleSidebarSelect(target.workbook_id)}
              >
                <Target size={13} className="target-icon" />
                <span className="item-name" title={target.workbook_name}>{target.workbook_name}</span>
                <span className="badge badge-keep">Keep</span>
                {cluster.target_override_reason && (
                  <span className="override-badge">Override</span>
                )}
              </button>
            )}
          </div>

          {workspaceData.candidates.length > 0 && (
            <div className="sidebar-group">
              <span className="sidebar-group-title">Consolidation Candidates ({workspaceData.candidates.length})</span>
              <div className="sidebar-scrollable">
                {workspaceData.candidates.map(c => {
                  const rec = workspaceData.recMap[c.workbook_id] || {};
                  const role = c.cluster_role || rec.cluster_role;
                  const roleClass = role === 'decommission' ? 'decommission' : role === 'merge_source' ? 'merge' : 'review';
                  const roleLabel = role === 'decommission' ? 'Archive' : role === 'merge_source' ? 'Merge' : 'Review';
                  const ItemIcon = role === 'decommission' ? Trash2 : role === 'merge_source' ? GitMerge : AlertCircle;
                  const iconColor = role === 'decommission' ? 'var(--accent-rose)' : role === 'merge_source' ? 'var(--accent-amber)' : 'var(--text-muted)';
                  
                  return (
                    <button
                      key={c.workbook_id}
                      className={`sidebar-item candidate-item ${selectedWbId === c.workbook_id ? 'active' : ''}`}
                      onClick={() => handleSidebarSelect(c.workbook_id)}
                    >
                      <ItemIcon size={12} className="git-icon" style={{ color: selectedWbId === c.workbook_id ? 'var(--accent-blue)' : iconColor }} />
                      <span className="item-name" title={c.workbook_name}>{c.workbook_name}</span>
                      <span className={`badge badge-${roleClass}`}>{roleLabel}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: Rich Rationalization Detail Panel */}
        <div className="workspace-details">
          {/* Comparison Toolbar — only for non-target selection */}
          {!isTargetSelected && workspaceData.candidates.length > 1 && (
            <div className="compare-toolbar">
              <CompareDropdown
                candidates={workspaceData.candidates.map(c => ({
                  workbook_id: c.workbook_id,
                  workbook_name: c.workbook_name,
                  cluster_role: c.cluster_role || (workspaceData.recMap[c.workbook_id] || {}).cluster_role,
                }))}
                selectedIds={compareIds}
                onToggle={handleCompareToggle}
                primaryId={selectedWbId}
              />
            </div>
          )}

          {/* Change Target button — when target is selected */}
          {isTargetSelected && (
            <div className="compare-toolbar">
              <button
                className="compare-dropdown-trigger"
                onClick={() => setChangeTargetOpen(true)}
              >
                <Pencil size={13} />
                <span>Change Target</span>
              </button>
            </div>
          )}

          {/* Panel Content */}
          {isCompareMode ? (
            <MultiComparePanel
              key={[...compareIds].sort().join(',')}
              clusterId={parseInt(clusterId, 10)}
              compareIds={compareIds}
              targetId={cluster.canonical_target_id}
              onExit={handleExitCompare}
            />
          ) : selectedWbId ? (
            <ClusterMemberDetailPanel
              key={selectedWbId}
              clusterId={parseInt(clusterId, 10)}
              workbookId={selectedWbId}
            />
          ) : (
            <div className="empty-workspace card">
              <Layers />
              <p>Select a report workbook from the sidebar to inspect consolidation details.</p>
            </div>
          )}
        </div>

      </div>

      {/* Change Target Modal */}
      <ChangeTargetModal
        isOpen={changeTargetOpen}
        onClose={() => setChangeTargetOpen(false)}
        onConfirm={handleChangeTargetConfirm}
        members={cluster.members || []}
        currentTargetId={cluster.canonical_target_id}
        loading={changingTarget}
      />
    </div>
  );
}
