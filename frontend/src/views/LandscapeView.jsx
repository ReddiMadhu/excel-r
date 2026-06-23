import { useState, useEffect, useMemo } from 'react';
import { Filter, Users, ChevronDown, RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import { Loader } from '../components/shared';
import PageHeader from '../components/layout/PageHeader';
import { KPIDashboardGraph } from '../components/shared/KPIDashboardGraph';

export default function LandscapeView() {
  const [dashboardsList, setDashboardsList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedLOBs, setSelectedLOBs] = useState([]);
  const [selectedUserGroups, setSelectedUserGroups] = useState([]);
  const [isLOBOpen, setIsLOBOpen] = useState(false);
  const [isGroupOpen, setIsGroupOpen] = useState(false);

  useEffect(() => {
    const fetchDashboards = async () => {
      try {
        setLoading(true);
        const data = await api.getDashboards();
        setDashboardsList(data || []);
      } catch (err) {
        console.error('Failed to load dashboards:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchDashboards();
  }, []);

  // Dynamically extract LOBs and User Groups from backend dashboard rows
  const { lobs, userGroups } = useMemo(() => {
    const lobsSet = new Set();
    const groupsSet = new Set();

    dashboardsList.forEach(dash => {
      const lob = dash.line_of_business || dash.domain_classification;
      if (lob) {
        lobsSet.add(lob);
      }

      // Handle user groups JSON or comma string
      let groups = [];
      if (Array.isArray(dash.user_groups)) {
        groups = dash.user_groups;
      } else if (typeof dash.user_groups === 'string') {
        try {
          groups = JSON.parse(dash.user_groups);
        } catch {
          groups = dash.user_groups.split(',').map(s => s.trim());
        }
      }
      
      groups.forEach(g => {
        if (g) groupsSet.add(g);
      });
    });

    return {
      lobs: Array.from(lobsSet).sort(),
      userGroups: Array.from(groupsSet).sort()
    };
  }, [dashboardsList]);

  // Compute matched dashboards as a comma-separated filter string
  const dashboardsStr = useMemo(() => {
    const matchedNames = [];
    
    dashboardsList.forEach(dash => {
      const lob = dash.line_of_business || dash.domain_classification;
      const lobMatch = selectedLOBs.length === 0 || 
        (lob && selectedLOBs.some(sl => sl.toLowerCase().trim() === String(lob).toLowerCase().trim()));

      let groups = [];
      if (Array.isArray(dash.user_groups)) {
        groups = dash.user_groups;
      } else if (typeof dash.user_groups === 'string') {
        try {
          groups = JSON.parse(dash.user_groups);
        } catch {
          groups = dash.user_groups.split(',').map(s => s.trim());
        }
      }
      
      const groupMatch = selectedUserGroups.length === 0 || 
        groups.some(g => selectedUserGroups.some(sg => sg.toLowerCase().trim() === String(g).toLowerCase().trim()));

      if (lobMatch && groupMatch && dash.name) {
        matchedNames.push(dash.name);
      }
    });

    return matchedNames.join(',');
  }, [dashboardsList, selectedLOBs, selectedUserGroups]);

  const toggleLOB = (lob) => {
    setSelectedLOBs(prev =>
      prev.includes(lob) ? prev.filter(l => l !== lob) : [...prev, lob]
    );
  };

  const toggleGroup = (grp) => {
    setSelectedUserGroups(prev =>
      prev.includes(grp) ? prev.filter(g => g !== grp) : [...prev, grp]
    );
  };

  if (loading) return <Loader />;

  return (
    <div className="page-enter" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header and Global Filter Dropdowns */}
      <PageHeader
        title="BI Landscape Graph"
        subtitle="Interactive D3 visualization of workbook lineage, calculation columns, and KPI relationships."
        actions={(
          <div style={{ display: 'flex', gap: '12px', position: 'relative' }}>
          {/* LOB Dropdown Filter */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => { setIsLOBOpen(!isLOBOpen); setIsGroupOpen(false); }}
              className="btn btn-ghost"
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px', fontSize: '0.85rem' }}
            >
              <Filter size={14} />
              LOB {selectedLOBs.length > 0 && <span className="badge badge-purple" style={{ padding: '2px 6px', fontSize: '0.65rem' }}>{selectedLOBs.length}</span>}
              <ChevronDown size={14} />
            </button>
            {isLOBOpen && (
              <div style={{
                position: 'absolute', right: 0, marginTop: '8px', width: '220px',
                background: 'var(--bg-surface)', border: '1px solid var(--glass-border)',
                borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)', zIndex: 110,
                maxHeight: '260px', overflowY: 'auto', padding: '6px 0'
              }}>
                {lobs.length === 0 ? (
                  <div style={{ padding: '12px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>No LOB classifications found</div>
                ) : (
                  lobs.map(lob => (
                    <label key={lob} style={{
                      display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 16px',
                      cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-primary)'
                    }} className="nav-link">
                      <input
                        type="checkbox"
                        checked={selectedLOBs.includes(lob)}
                        onChange={() => toggleLOB(lob)}
                        style={{ accentColor: 'var(--accent-blue)', cursor: 'pointer' }}
                      />
                      <span>{lob}</span>
                    </label>
                  ))
                )}
              </div>
            )}
          </div>

          {/* User Group Dropdown Filter */}
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => { setIsGroupOpen(!isGroupOpen); setIsLOBOpen(false); }}
              className="btn btn-ghost"
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px', fontSize: '0.85rem' }}
            >
              <Users size={14} />
              User Group {selectedUserGroups.length > 0 && <span className="badge badge-purple" style={{ padding: '2px 6px', fontSize: '0.65rem' }}>{selectedUserGroups.length}</span>}
              <ChevronDown size={14} />
            </button>
            {isGroupOpen && (
              <div style={{
                position: 'absolute', right: 0, marginTop: '8px', width: '220px',
                background: 'var(--bg-surface)', border: '1px solid var(--glass-border)',
                borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-lg)', zIndex: 110,
                maxHeight: '260px', overflowY: 'auto', padding: '6px 0'
              }}>
                {userGroups.length === 0 ? (
                  <div style={{ padding: '12px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>No user groups found</div>
                ) : (
                  userGroups.map(grp => (
                    <label key={grp} style={{
                      display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 16px',
                      cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-primary)'
                    }} className="nav-link">
                      <input
                        type="checkbox"
                        checked={selectedUserGroups.includes(grp)}
                        onChange={() => toggleGroup(grp)}
                        style={{ accentColor: 'var(--accent-blue)', cursor: 'pointer' }}
                      />
                      <span>{grp}</span>
                    </label>
                  ))
                )}
              </div>
            )}
          </div>
        )}
      />

      {/* Render the core D3 Graph view */}
      <div style={{ height: '650px', width: '100%' }}>
        {dashboardsStr ? (
          <KPIDashboardGraph dashboards={dashboardsStr} height="100%" />
        ) : (
          <div className="card" style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', flexDirection: 'column', gap: '12px', borderColor: 'var(--accent-rose)'
          }}>
            <p style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>No sheets match the selected filter configuration.</p>
            <button
              onClick={() => { setSelectedLOBs([]); setSelectedUserGroups([]); }}
              className="btn btn-ghost"
              style={{ fontSize: '0.8rem' }}
            >
              Reset Filters
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
