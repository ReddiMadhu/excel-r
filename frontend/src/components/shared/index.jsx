export function StatCard({ icon: Icon, value, label, color = 'blue' }) {
  return (
    <div className="stat-card">
      <div className={`stat-icon ${color}`}><Icon size={22} /></div>
      <div className="stat-content">
        <h3>{value}</h3>
        <p>{label}</p>
      </div>
    </div>
  );
}

export function Badge({ action }) {
  const cls = action === 'keep' ? 'badge-keep'
    : action === 'merge' ? 'badge-merge'
    : action === 'review' ? 'badge-merge'
    : action === 'decommission' || action === 'delete' ? 'badge-decommission'
    : 'badge-blue';
  return <span className={`badge ${cls}`}>{action}</span>;
}

export function ComplexityBar({ value, max = 5 }) {
  const pct = Math.min(100, (value / max) * 100);
  const cls = value <= 1.5 ? 'low' : value <= 3 ? 'medium' : 'high';
  return (
    <div className="complexity-bar">
      <div className="complexity-track">
        <div className={`complexity-fill ${cls}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="complexity-value">{value?.toFixed(1) ?? '—'}</span>
    </div>
  );
}

export function Loader() {
  return <div className="loader"><div className="spinner" /></div>;
}

export function EmptyState({ icon: Icon, title, message }) {
  return (
    <div className="empty-state">
      {Icon && <Icon />}
      <h3>{title}</h3>
      <p>{message}</p>
    </div>
  );
}

export { KPIDashboardGraph } from './KPIDashboardGraph';
