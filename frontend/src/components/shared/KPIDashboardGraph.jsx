import { useEffect, useRef, useState, useMemo } from 'react';
import * as d3 from 'd3';
import { AlertCircle, Sparkles, Maximize2, X, Loader2 } from 'lucide-react';
import { api } from '../../api/client';
import { Loader } from './index';

const COLOR_MAP = {
  'Workbook': 'var(--accent-blue)',
  'Dashboard': 'var(--accent-blue)',
  'KPI': 'var(--accent-emerald)',
  'Shared KPI': 'var(--accent-emerald)',
  'Line of Business': 'var(--accent-blue)',
  'Business Area': 'var(--accent-purple)',
  'User Group': 'var(--accent-amber)',
  'Table': 'var(--accent-rose)',
  'Datasource': '#0d9488',
  'Shared Datasource': '#0d9488',
  'Granularity Level': '#8b4513',
  'Upload Age': '#ec4899',
};

const LEGEND_ITEMS = [
  { group: 'Workbook', label: 'Workbook' },
  { group: 'Dashboard', label: 'Sheet' },
  { group: 'KPI', label: 'KPI' },
  { group: 'Shared KPI', label: 'Shared KPI' },
  { group: 'Line of Business', label: 'Line of Business' },
  { group: 'Business Area', label: 'Business Area' },
  { group: 'User Group', label: 'User Group' },
  { group: 'Table', label: 'Table' },
  { group: 'Datasource', label: 'Datasource' },
  { group: 'Shared Datasource', label: 'Shared Source' },
  { group: 'Granularity Level', label: 'Granularity' },
  { group: 'Upload Age', label: 'Upload Age' },
];

const ACTION_COLORS = {
  keep: 'var(--accent-emerald)',
  merge: 'var(--accent-amber)',
  decommission: 'var(--status-decommission)',
  delete: 'var(--status-decommission)',
  review: 'var(--accent-blue)',
};

export function KPIDashboardGraph({
  dashboards,
  workbookId,
  workbookIds,
  view = 'landscape',
  height = '600px',
  isMaximizedView = false,
  onMinimize,
}) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const tooltipRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [aiSummary, setAiSummary] = useState(null);
  const [isLoadingSummary, setIsLoadingSummary] = useState(false);
  const [showSummary, setShowSummary] = useState(true);
  const [isMaximized, setIsMaximized] = useState(false);
  const [activeHighlight, setActiveHighlight] = useState(null);
  const [presentGroups, setPresentGroups] = useState(new Set());

  const graphParams = useMemo(() => ({
    dashboards,
    workbookId,
    workbookIds,
    view,
  }), [dashboards, workbookId, workbookIds, view]);

  const isRationalization = view === 'rationalization';

  // References to D3 nodes/links to trigger updates from parent React events
  const highlightGraphRef = useRef(null);

  useEffect(() => {
    let simulation;
    let tooltipDiv = d3.select(tooltipRef.current);

    const fetchDataAndDraw = async () => {
      try {
        setIsLoading(true);
        setError(null);
        
        const data = await api.getKpiGraphData(graphParams);

        if (!data.nodes || data.nodes.length === 0) {
          throw new Error('No graph nodes found for the selected scope.');
        }

        setPresentGroups(new Set(data.nodes.map(n => n.group)));
        drawGraph(data.nodes, data.links);
      } catch (err) {
        console.error('Failed to load KPI graph:', err);
        setError(err.message || 'Failed to render D3 visualization.');
      } finally {
        setIsLoading(false);
      }
    };

    const drawGraph = (nodes, links) => {
      if (!svgRef.current || !containerRef.current) return;

      const width = containerRef.current.clientWidth;
      const heightVal = containerRef.current.clientHeight || 600;

      const svg = d3.select(svgRef.current);
      svg.selectAll('*').remove();

      // Main inner container for zooming
      const g = svg.append('g');

      // Setup zoom behavior
      const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => {
          g.attr('transform', event.transform);
        });

      svg.call(zoom);

      // Setup force simulation
      simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(130))
        .force('charge', d3.forceManyBody().strength(-350))
        .force('center', d3.forceCenter(width / 2, heightVal / 2))
        .force('collide', d3.forceCollide().radius(45));

      // Draw link lines
      const link = g.append('g')
        .attr('stroke', 'var(--glass-border)')
        .attr('stroke-opacity', 0.6)
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke-width', d => d.stroke_width || 2);

      // Draw link labels if present
      const linkLabel = g.append('g')
        .selectAll('text')
        .data(links)
        .join('text')
        .attr('font-size', '9px')
        .attr('fill', 'var(--text-muted)')
        .attr('text-anchor', 'middle')
        .text(d => d.label || '');

      // Create group elements for nodes
      const node = g.append('g')
        .selectAll('g')
        .data(nodes)
        .join('g')
        .call(d3.drag()
          .on('start', dragstarted)
          .on('drag', dragged)
          .on('end', dragended)
        );

      // Draw node circles
      node.append('circle')
        .attr('r', d => (d.group === 'Workbook' || d.group === 'Dashboard') ? 24 : 16)
        .attr('fill', d => {
          if (d.group === 'Workbook' && d.action) {
            return ACTION_COLORS[d.action] || COLOR_MAP['Workbook'];
          }
          return COLOR_MAP[d.group] || 'var(--text-muted)';
        })
        .attr('stroke', 'var(--bg-surface)')
        .attr('stroke-width', 2.5)
        .style('cursor', 'grab');

      // Draw text label on nodes
      node.append('text')
        .text(d => d.label)
        .attr('x', 0)
        .attr('y', d => (d.group === 'Workbook' || d.group === 'Dashboard') ? 36 : 28)
        .attr('text-anchor', 'middle')
        .attr('font-size', '11px')
        .attr('font-weight', d => (d.group === 'Workbook' || d.group === 'Dashboard') ? 'bold' : '500')
        .attr('fill', 'var(--text-primary)')
        .style('pointer-events', 'none')
        .each(function(d) {
          const el = d3.select(this);
          const words = d.label.split(/\s+/);
          if (words.length > 2) {
            el.text('');
            el.append('tspan').text(words.slice(0, 2).join(' ')).attr('x', 0).attr('dy', 0);
            el.append('tspan').text(words.slice(2).join(' ')).attr('x', 0).attr('dy', 12);
          }
        });

      // Mouse interactive hooks
      node.on('mouseover', (event, d) => {
        tooltipDiv.transition().duration(150).style('opacity', 1).style('display', 'block');
        const descHtml = d.definition ? `<div class="kpi-graph-tooltip-desc">${d.definition}</div>` : '';
        const actionHtml = d.action ? `<div class="kpi-graph-tooltip-desc">Action: ${d.action}${d.merge_with_name ? ` → retain ${d.merge_with_name}` : ''}</div>` : '';
        tooltipDiv.html(`<div class="kpi-graph-tooltip-title">${d.group}: ${d.label}</div>${actionHtml}${descHtml}`);
      })
      .on('mousemove', (event) => {
        // Position relative to SVG container bounding box
        const bounds = containerRef.current.getBoundingClientRect();
        const x = event.clientX - bounds.left + 15;
        const y = event.clientY - bounds.top - 15;
        tooltipDiv.style('left', `${x}px`).style('top', `${y}px`);
      })
      .on('mouseleave', () => {
        tooltipDiv.transition().duration(250).style('opacity', 0).style('display', 'none');
      });

      // Highlight connection mapping on node click
      node.on('click', (event, d) => {
        setActiveHighlight(null);
        event.stopPropagation();

        // Dim everything
        node.style('opacity', 0.25);
        link.attr('stroke-opacity', 0.1).attr('stroke', 'var(--glass-border)');

        const connectedIds = new Set([d.id]);
        
        link.filter(l => {
          const isSrc = l.source.id === d.id;
          const isTgt = l.target.id === d.id;
          if (isSrc || isTgt) {
            connectedIds.add(l.source.id);
            connectedIds.add(l.target.id);
            return true;
          }
          return false;
        })
        .attr('stroke-opacity', 1)
        .attr('stroke', 'var(--accent-blue)');

        node.filter(n => connectedIds.has(n.id))
          .style('opacity', 1);
      });

      svg.on('click', () => {
        setActiveHighlight(null);
        node.style('opacity', 1);
        link.attr('stroke-opacity', 0.6).attr('stroke', 'var(--glass-border)');
      });

      // Simulation ticks
      simulation.on('tick', () => {
        link
          .attr('x1', d => d.source.x)
          .attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x)
          .attr('y2', d => d.target.y);

        linkLabel
          .attr('x', d => (d.source.x + d.target.x) / 2)
          .attr('y', d => (d.source.y + d.target.y) / 2);

        node.attr('transform', d => `translate(${d.x},${d.y})`);
      });

      function dragstarted(event) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        event.subject.fx = event.subject.x;
        event.subject.fy = event.subject.y;
      }

      function dragged(event) {
        event.subject.fx = event.x;
        event.subject.fy = event.y;
      }

      function dragended(event) {
        if (!event.active) simulation.alphaTarget(0);
        // Retain pinned coordinates so nodes do not collapse back
      }

      // External highlighting function
      highlightGraphRef.current = (type) => {
        // Reset styles first
        node.style('opacity', 1);
        node.selectAll('circle')
          .attr('stroke', 'var(--bg-surface)')
          .attr('stroke-width', 2.5);
        link.attr('stroke-opacity', 0.6).attr('stroke', 'var(--glass-border)');

        if (!type) return;

        node.style('opacity', 0.2);
        link.attr('stroke-opacity', 0.1);

        const highlightTargets = new Set();
        
        if (type === 'kpi') {
          nodes.forEach(n => { if (n.group === 'KPI') highlightTargets.add(n.id); });
        } else if (type === 'tables') {
          nodes.forEach(n => { if (n.group === 'Table') highlightTargets.add(n.id); });
        } else if (type === 'user-group') {
          nodes.forEach(n => { if (n.group === 'User Group') highlightTargets.add(n.id); });
        } else if (type === 'upload-age') {
          nodes.forEach(n => { if (n.group === 'Upload Age') highlightTargets.add(n.id); });
        } else if (type === 'datasource') {
          nodes.forEach(n => { if (n.group === 'Datasource') highlightTargets.add(n.id); });
        } else if (type === 'common-kpi' || type === 'shared-kpi') {
          if (view === 'rationalization') {
            nodes.forEach(n => { if (n.group === 'Shared KPI') highlightTargets.add(n.id); });
          } else {
            nodes.forEach(n => {
              if (n.group === 'KPI') {
                const connectedDashes = links.filter(l => {
                  const sId = typeof l.source === 'object' ? l.source.id : l.source;
                  const tId = typeof l.target === 'object' ? l.target.id : l.target;
                  return (sId === n.id || tId === n.id);
                });
                if (connectedDashes.length > 1) {
                  highlightTargets.add(n.id);
                }
              }
            });
          }
        } else if (type === 'shared-source') {
          nodes.forEach(n => { if (n.group === 'Shared Datasource' || n.group === 'Datasource') highlightTargets.add(n.id); });
        } else if (type === 'workbook') {
          nodes.forEach(n => { if (n.group === 'Workbook') highlightTargets.add(n.id); });
        }

        const connectedSet = new Set(highlightTargets);

        // Highlight connected links
        link.filter(l => {
          const sId = typeof l.source === 'object' ? l.source.id : l.source;
          const tId = typeof l.target === 'object' ? l.target.id : l.target;
          const isConnected = highlightTargets.has(sId) || highlightTargets.has(tId);
          if (isConnected) {
            connectedSet.add(sId);
            connectedSet.add(tId);
          }
          return isConnected;
        })
        .attr('stroke-opacity', 1)
        .attr('stroke', 'var(--accent-blue)');

        // Restore opacity on nodes in target set
        node.filter(n => connectedSet.has(n.id))
          .style('opacity', 1)
          .selectAll('circle')
          .filter(n => highlightTargets.has(n.id))
          .attr('stroke', 'var(--accent-purple)')
          .attr('stroke-width', 4);
      };
    };

    fetchDataAndDraw();

    return () => {
      if (simulation) simulation.stop();
    };
  }, [graphParams]);

  // Fetch summary context from Gemini LLM
  useEffect(() => {
    const fetchSummary = async () => {
      setIsLoadingSummary(true);
      try {
        const data = await api.getKpiGraphSummary(graphParams, activeHighlight || 'all');
        setAiSummary(data.summary);
      } catch (err) {
        console.error('Failed to fetch summary:', err);
        setAiSummary('Failed to retrieve landscape analytics summary.');
      } finally {
        setIsLoadingSummary(false);
      }
    };
    
    fetchSummary();
  }, [graphParams, activeHighlight]);

  const handleHighlightClick = (type) => {
    const nextHighlight = activeHighlight === type ? null : type;
    setActiveHighlight(nextHighlight);
    if (highlightGraphRef.current) {
      highlightGraphRef.current(nextHighlight);
    }
  };

  return (
    <div className="kpi-graph-container" style={{ height }}>
      {/* Toolbar / Filters */}
      <div className="kpi-graph-toolbar">
        <span className="kpi-graph-toolbar-title">Highlight Connections:</span>
        {isRationalization ? (
          <>
            <button
              onClick={() => handleHighlightClick('workbook')}
              className={`btn ${activeHighlight === 'workbook' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            >
              Workbooks
            </button>
            <button
              onClick={() => handleHighlightClick('shared-kpi')}
              className={`btn ${activeHighlight === 'shared-kpi' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            >
              Shared KPIs
            </button>
            {presentGroups.has('Shared Datasource') && (
              <button
                onClick={() => handleHighlightClick('shared-source')}
                className={`btn ${activeHighlight === 'shared-source' ? 'btn-primary' : 'btn-ghost'}`}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              >
                Shared Sources
              </button>
            )}
          </>
        ) : (
          <>
            <button
              onClick={() => handleHighlightClick('common-kpi')}
              className={`btn ${activeHighlight === 'common-kpi' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            >
              Shared KPIs
            </button>
            <button
              onClick={() => handleHighlightClick('kpi')}
              className={`btn ${activeHighlight === 'kpi' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            >
              KPI Nodes
            </button>
            <button
              onClick={() => handleHighlightClick('tables')}
              className={`btn ${activeHighlight === 'tables' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            >
              Tables
            </button>
            {presentGroups.has('Datasource') && (
              <button
                onClick={() => handleHighlightClick('datasource')}
                className={`btn ${activeHighlight === 'datasource' ? 'btn-primary' : 'btn-ghost'}`}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              >
                Datasources
              </button>
            )}
            {presentGroups.has('User Group') && (
              <button
                onClick={() => handleHighlightClick('user-group')}
                className={`btn ${activeHighlight === 'user-group' ? 'btn-primary' : 'btn-ghost'}`}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              >
                User Group
              </button>
            )}
            {presentGroups.has('Upload Age') && (
              <button
                onClick={() => handleHighlightClick('upload-age')}
                className={`btn ${activeHighlight === 'upload-age' ? 'btn-primary' : 'btn-ghost'}`}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              >
                Upload Age
              </button>
            )}
          </>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setShowSummary(!showSummary)}
            className={`btn ${showSummary ? 'btn-primary' : 'btn-ghost'}`}
            style={{ padding: '6px 12px', fontSize: '0.8rem' }}
          >
            {showSummary ? 'Hide AI Insights' : 'AI Insights'}
          </button>

          {!isMaximizedView ? (
            <button
              onClick={() => setIsMaximized(true)}
              className="btn btn-ghost"
              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            >
              <Maximize2 size={13} /> Full Screen
            </button>
          ) : (
            onMinimize && (
              <button
                onClick={onMinimize}
                className="btn btn-ghost hover-red-btn"
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              >
                <X size={13} /> Minimize
              </button>
            )
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="kpi-graph-content" style={{ height: 'calc(100% - 60px)' }}>
        {/* SVG Area */}
        <div ref={containerRef} className="kpi-graph-svg-wrapper">
          {isLoading && (
            <div style={{ position: 'absolute', inset: 0, background: 'var(--bg-glass)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
              <Loader />
            </div>
          )}
          {error && (
            <div style={{ position: 'absolute', inset: 0, background: 'var(--bg-glass)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24, zIndex: 100, color: 'var(--accent-rose)' }}>
              <AlertCircle size={32} style={{ marginBottom: 12 }} />
              <div style={{ fontWeight: 650 }}>Failed to Load Graph</div>
              <div className="text-secondary" style={{ fontSize: '0.85rem', marginTop: 4, textAlign: 'center' }}>{error}</div>
            </div>
          )}

          <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />

          {/* Floating Legend */}
          <div className="kpi-graph-legend">
            <div className="kpi-graph-legend-title">Legend</div>
            <div className="kpi-graph-legend-grid">
              {LEGEND_ITEMS.filter(item => presentGroups.has(item.group)).map(item => (
                <div key={item.group} className="kpi-graph-legend-item">
                  <div className="kpi-graph-legend-dot" style={{ background: COLOR_MAP[item.group] }} />
                  <span className="kpi-graph-legend-label">{item.label}</span>
                </div>
              ))}
              {isRationalization && presentGroups.has('Workbook') && (
                <>
                  <div className="kpi-graph-legend-item">
                    <div className="kpi-graph-legend-dot" style={{ background: ACTION_COLORS.keep }} />
                    <span className="kpi-graph-legend-label">Keep</span>
                  </div>
                  <div className="kpi-graph-legend-item">
                    <div className="kpi-graph-legend-dot" style={{ background: ACTION_COLORS.merge }} />
                    <span className="kpi-graph-legend-label">Merge</span>
                  </div>
                  <div className="kpi-graph-legend-item">
                    <div className="kpi-graph-legend-dot" style={{ background: ACTION_COLORS.decommission }} />
                    <span className="kpi-graph-legend-label">Decommission</span>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Floating Tooltip */}
          <div ref={tooltipRef} className="kpi-graph-tooltip" />
        </div>

        {/* AI summary */}
        {showSummary && (
          <div className="kpi-graph-summary-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <div style={{ padding: 6, background: 'rgba(236, 63, 6, 0.08)', borderRadius: 8, color: 'var(--accent-blue)' }}>
                <Sparkles size={16} />
              </div>
              <div style={{ fontSize: '0.85rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
                {isRationalization ? 'Rationalization Insights' : 'Landscape Insights'}
              </div>
            </div>

            <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
              {isLoadingSummary ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8 }}>
                  <Loader />
                  <span className="text-secondary" style={{ fontSize: '0.8rem', textAlign: 'center' }}>Compiling graph contexts...</span>
                </div>
              ) : (
                <div style={{ fontSize: '0.875rem', lineHeight: '1.6', color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
                  {aiSummary || 'Insights summary not available.'}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {isMaximized && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'var(--bg-base)', padding: '24px', display: 'flex', flexDirection: 'column' }}>
          <KPIDashboardGraph
            dashboards={dashboards}
            workbookId={workbookId}
            workbookIds={workbookIds}
            view={view}
            height="100%"
            isMaximizedView={true}
            onMinimize={() => setIsMaximized(false)}
          />
        </div>
      )}
    </div>
  );
}
