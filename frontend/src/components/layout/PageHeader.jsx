import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trash2, AlertCircle, X } from 'lucide-react';
import { api } from '../../api/client';
import ThemeToggle from './ThemeToggle';

export default function PageHeader({ title, subtitle, leading, actions, className = '' }) {
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const [status, setStatus] = useState('confirm'); // 'confirm' | 'deleting' | 'success' | 'error'
  const [errorMsg, setErrorMsg] = useState('');

  const handleDelete = async () => {
    setStatus('deleting');
    try {
      await api.deleteAllData();
      setStatus('success');
      setTimeout(() => {
        setIsOpen(false);
        setStatus('confirm');
        navigate('/upload');
        window.location.reload();
      }, 1500);
    } catch (err) {
      console.error(err);
      setErrorMsg(err.message || 'Failed to wipe data.');
      setStatus('error');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && status === 'confirm') {
      e.preventDefault();
      handleDelete();
    }
  };

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
        
        {/* Delete All Data Icon Button */}
        <button
          type="button"
          className="theme-toggle" /* reuse theme toggle sizing classes */
          style={{ 
            color: 'var(--accent-rose)', 
            borderColor: 'rgba(244, 63, 94, 0.2)',
            background: 'rgba(244, 63, 94, 0.02)'
          }}
          onClick={() => setIsOpen(true)}
          title="Delete All Data & Start Fresh"
          aria-label="Delete All Data & Start Fresh"
        >
          <Trash2 size={17} />
        </button>

        <ThemeToggle />
      </div>

      {/* Delete Confirmation Modal */}
      {isOpen && (
        <div 
          className="delete-modal-overlay" 
          onClick={() => status !== 'deleting' && setIsOpen(false)}
          onKeyDown={handleKeyDown}
        >
          <div className="delete-modal-card" onClick={(e) => e.stopPropagation()}>
            {status !== 'deleting' && (
              <button 
                className="delete-modal-close" 
                onClick={() => setIsOpen(false)}
                aria-label="Close modal"
              >
                <X size={18} />
              </button>
            )}

            {status === 'confirm' && (
              <>
                <div className="delete-modal-header">
                  <div className="delete-modal-header-icon">
                    <Trash2 size={20} />
                  </div>
                  <h3>Delete All Data?</h3>
                </div>

                <div className="delete-modal-body">
                  <p style={{ margin: '0 0 16px 0', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                    Are you sure you want to permanently delete all uploaded workbooks, scans, intelligence reports, and overlap calculations?
                  </p>
                  <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                    Press <strong style={{ color: 'var(--text-primary)' }}>ENTER</strong> or click Delete to confirm.
                  </p>
                </div>

                <div className="delete-modal-footer">
                  <button 
                    className="btn btn-ghost" 
                    onClick={() => setIsOpen(false)}
                  >
                    Cancel
                  </button>
                  <button
                    className="btn-danger-solid"
                    onClick={handleDelete}
                    autoFocus
                  >
                    Delete Everything
                  </button>
                </div>
              </>
            )}

            {status === 'deleting' && (
              <div className="delete-success-message">
                <div className="delete-spinner" />
                <div>
                  <h3 style={{ margin: '0 0 6px 0', fontSize: '1rem' }}>Wiping system data...</h3>
                  <p className="text-muted" style={{ fontSize: '0.8rem', margin: 0 }}>
                    Clearing database, scans and generated files.
                  </p>
                </div>
              </div>
            )}

            {status === 'success' && (
              <div className="delete-success-message">
                <div className="delete-success-icon">✓</div>
                <div>
                  <h3 style={{ margin: '0 0 6px 0', fontSize: '1.1rem', color: 'var(--accent-emerald)' }}>
                    System Reset Complete
                  </h3>
                  <p className="text-secondary" style={{ fontSize: '0.85rem', margin: 0 }}>
                    Redirecting to upload view...
                  </p>
                </div>
              </div>
            )}

            {status === 'error' && (
              <div className="delete-success-message">
                <div className="delete-modal-header-icon" style={{ width: 48, height: 48, borderRadius: '50%' }}>
                  <AlertCircle size={22} />
                </div>
                <div>
                  <h3 style={{ margin: '0 0 6px 0', fontSize: '1.1rem', color: 'var(--accent-rose)' }}>
                    Reset Failed
                  </h3>
                  <p className="text-secondary" style={{ fontSize: '0.85rem', margin: 0 }}>
                    {errorMsg}
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
                  <button className="btn btn-ghost" onClick={() => setIsOpen(false)}>
                    Close
                  </button>
                  <button className="btn-danger-solid" onClick={handleDelete}>
                    Retry
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

