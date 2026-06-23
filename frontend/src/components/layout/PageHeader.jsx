import ThemeToggle from './ThemeToggle';

export default function PageHeader({ title, subtitle, leading, actions, className = '' }) {
  return (
    <div className={`page-header ${className}`.trim()}>
      <div className="page-header-main">
        {leading}
        <div className="page-header-text">
          <h1>{title}</h1>
          {subtitle && <p className="page-header-subtitle">{subtitle}</p>}
        </div>
      </div>
      <div className="page-header-actions">
        {actions}
        <ThemeToggle />
      </div>
    </div>
  );
}
