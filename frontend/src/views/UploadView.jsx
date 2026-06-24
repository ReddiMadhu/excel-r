import { useState, useCallback, useEffect, useRef } from 'react';
import { Upload, FileSpreadsheet, CheckCircle, AlertCircle, Clock, X } from 'lucide-react';
import { api } from '../api/client';
import PageHeader from '../components/layout/PageHeader';

export default function UploadView() {
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [scans, setScans] = useState([]);
  const fileInputRef = useRef(null);

  const addFiles = useCallback((filesList) => {
    const xlsxFiles = Array.from(filesList).filter(f =>
      f.name.endsWith('.xlsx') && !f.name.startsWith('~$')
    );
    setSelectedFiles(prev => {
      const updated = [...prev];
      xlsxFiles.forEach(file => {
        if (!updated.some(existing => existing.name === file.name && existing.size === file.size)) {
          updated.push(file);
        }
      });
      return updated;
    });
  }, []);

  const removeFile = useCallback((idx) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== idx));
  }, []);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
    addFiles(e.dataTransfer.files);
  }, [addFiles]);

  const handleUpload = async () => {
    if (!selectedFiles.length) return;
    setIsUploading(true);
    try {
      const result = await api.createScan(selectedFiles);
      setScans(prev => [{ ...result, files: selectedFiles.map(f => f.name) }, ...prev]);
      setSelectedFiles([]);
    } catch (e) {
      console.error('Upload failed:', e);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="page-enter">
      <div className="animate-fade-in">
        <PageHeader
          title="Upload Reports"
          subtitle="Upload runs BI Discovery only (fast extraction). Run Intelligence and Rationalization from their sidebar agents when you are ready."
        />

        <div className="upload-pipeline">
          <div className="upload-pipeline-step">
            <strong>1. BI Discovery</strong>
            <span>On upload — sheets, datasources, structure</span>
          </div>
          <div className="upload-pipeline-step">
            <strong>2. BI Intelligence</strong>
            <span>On demand — KPI clusters, formula analysis</span>
          </div>
          <div className="upload-pipeline-step">
            <strong>3. BI Rationalization</strong>
            <span>On demand — overlap, risks, recommendations</span>
          </div>
        </div>

        {/* Drop zone */}
        <div
          className={`dropzone ${isDragging ? 'active' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={onDrop}
          onClick={() => !isUploading && fileInputRef.current?.click()}
          style={isUploading ? { opacity: 0.6, cursor: 'not-allowed' } : {}}
        >
          <div className="dropzone-icon"><Upload size={24} /></div>
          <h3>Drag & drop Excel files or folders here</h3>
          <p>Or click to browse folders. Only .xlsx files are processed.</p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            webkitdirectory=""
            directory=""
            accept=".xlsx"
            style={{ display: 'none' }}
            onChange={(e) => addFiles(e.target.files)}
            disabled={isUploading}
          />
        </div>

        {/* File List & Form Action */}
        {selectedFiles.length > 0 && (
          <div className="animate-slide-up" style={{ marginTop: 24 }}>
            <p className="text-secondary" style={{ fontSize: '0.8rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>
              Selected Reports ({selectedFiles.length})
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
              {selectedFiles.map((file, idx) => (
                <div
                  key={idx}
                  className="card"
                  style={{
                    padding: '12px 16px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--glass-border)'
                  }}
                >
                  <div style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: 'rgba(236, 63, 6, 0.08)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--accent-blue)',
                    flexShrink: 0
                  }}>
                    <FileSpreadsheet size={18} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <p style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-primary)', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {file.name}
                    </p>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '2px 0 0 0' }}>
                      {(file.size / 1024 / 1024).toFixed(2)} MB &middot; Excel Report
                    </p>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); removeFile(idx); }}
                    disabled={isUploading}
                    style={{
                      border: 'none',
                      background: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 6,
                      borderRadius: '50%',
                      transition: 'all 0.2s'
                    }}
                    className="hover-red-btn"
                  >
                    <X size={16} />
                  </button>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, alignItems: 'center' }}>
              <button
                className="btn btn-ghost"
                onClick={() => setSelectedFiles([])}
                disabled={isUploading}
              >
                Clear All
              </button>
              <button
                className="btn btn-primary"
                onClick={handleUpload}
                disabled={isUploading}
              >
                {isUploading ? 'Uploading...' : 'Upload & Run Discovery'}
              </button>
            </div>
          </div>
        )}

        {scans.length > 0 && (
          <div style={{ marginTop: 32 }}>
            <h3 className="section-title" style={{ marginBottom: 16 }}>Active & Recent Scans</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {scans.map((scan, i) => (
                <ScanCard key={scan.scan_id || i} scan={scan} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ScanCard({ scan }) {
  const [progress, setProgress] = useState(scan);

  useEffect(() => {
    if (progress.status === 'completed' || progress.status === 'failed') return;

    const interval = setInterval(async () => {
      try {
        const p = await api.getScanProgress(scan.scan_id);
        setProgress(p);
        if (p.status === 'completed' || p.status === 'failed') clearInterval(interval);
      } catch (e) { /* ignore */ }
    }, 3000);

    return () => clearInterval(interval);
  }, [scan.scan_id, progress.status]);

  const isComplete = progress.status === 'completed';
  const isFailed = progress.status === 'failed';
  const pct = progress.progress_percent || 0;

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {isComplete ? <CheckCircle size={18} style={{ color: 'var(--accent-emerald)' }} />
           : isFailed ? <AlertCircle size={18} style={{ color: 'var(--accent-rose)' }} />
           : <Clock size={18} style={{ color: 'var(--accent-blue)' }} />}
          <span style={{ fontWeight: 600 }}>
            Scan {scan.scan_id?.slice(0, 8)}...
          </span>
          <span className="badge badge-blue">{progress.status}</span>
        </div>
        <span className="text-muted" style={{ fontSize: '0.8rem' }}>
          {progress.processed_files || 0}/{progress.total_files || scan.total_files} files
        </span>
      </div>

      {!isComplete && !isFailed && (
        <>
          <div className="progress-bar" style={{ marginBottom: 8 }}>
            <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="text-muted" style={{ fontSize: '0.8rem' }}>
            {progress.phase === 'discovery' || progress.phase === 'extraction'
              ? progress.current_file
                ? `Discovery: ${progress.current_file}`
                : 'Starting discovery extraction...'
              : progress.current_file
              ? `Processing: ${progress.current_file}`
              : 'Processing...'}
          </div>
        </>
      )}

      {isComplete && (
        <p className="text-secondary" style={{ fontSize: '0.85rem' }}>
          Discovery complete. View portfolio under BI Discovery, then run Intelligence and Rationalization from the sidebar.
          {progress.errors?.length > 0 && ` (${progress.errors.length} warnings)`}
        </p>
      )}
    </div>
  );
}

