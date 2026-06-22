import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { AlertCircle, Sparkles, Maximize2, X, Loader2 } from 'lucide-react';
import { api } from '../../api/client';
import { Loader } from './index';

const COLOR_MAP = {
  'Dashboard': 'var(--accent-blue)',       // orange primary
  'KPI': 'var(--accent-emerald)',          // green
  'Business Area': 'var(--accent-purple)', // coral/purple
  'User Group': 'var(--accent-amber)',     // yellow/amber
  'Table': 'var(--accent-rose)',           // red
  'Granularity Level': '#8b4513',          // brown
  'Access Recency': '#ec4899'              // pink
};

export function KPIDashboardGraph({ dashboards, height = '600px', isMaximizedView = false, onMinimize }) {
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

  // References to D3 nodes/links to trigger updates from parent React events
  const highlightGraphRef = useRef(null);

  useEffect(() => {
    let simulation;
    let tooltipDiv = d3.select(tooltipRef.current);

    const fetchDataAndDraw = async () => {
      try {
        setIsLoading(true);
        setError(null);
        
        const data = await api.getKpiGraphData(dashboards);
        
        if (!data.nodes || data.nodes.length === 0) {
          throw new Error('No relational graph nodes found for the selected dashboards.');
        }

        drawGraph(data.nodes, data.links);
      } catch (err) {
        logger.error('Failed to load KPI graph:', err);
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
        .attr('stroke-width', 2)
        .selectAll('line')
        .data(links)
        .join('line');

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
        .attr('r', d => d.group === 'Dashboard' ? 24 : 16)
        .attr('fill', d => COLOR_MAP[d.group] || 'var(--text-muted)')
        .attr('stroke', 'var(--bg-surface)')
        .attr('stroke-width', 2.5)
        .style('cursor', 'grab');

      // Draw text label on nodes
      node.append('text')
        .text(d => d.label)
        .attr('x', 0)
        .attr('y', d => d.group === 'Dashboard' ? 36 : 28)
        .attr('text-anchor', 'middle')
        .attr('font-size', '11px')
        .attr('font-weight', d => d.group === 'Dashboard' ? 'bold' : '500')
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
        tooltipDiv.html(`<div class="kpi-graph-tooltip-title">${d.group}: ${d.label}</div>${descHtml}`);
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
        } else if (type === 'access-recency') {
          nodes.forEach(n => { if (n.group === 'Access Recency') highlightTargets.add(n.id); });
        } else if (type === 'common-kpi') {
          // Highlight KPIs shared by 2 or more dashboards
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
  }, [dashboards]);

  // Fetch summary context from Gemini LLM
  useEffect(() => {
    const fetchSummary = async () => {
      setIsLoadingSummary(true);
      try {
        const data = await api.getKpiGraphSummary(dashboards, activeHighlight || 'all');
        setAiSummary(data.summary);
      } catch (err) {
        console.error('Failed to fetch summary:', err);
        setAiSummary('Failed to retrieve landscape analytics summary.');
      } finally {
        setIsLoadingSummary(false);
      }
    };
    
    fetchSummary();
  }, [dashboards, activeHighlight]);

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
        <button
          onClick={() => handleHighlightClick('user-group')}
          className={`btn ${activeHighlight === 'user-group' ? 'btn-primary' : 'btn-ghost'}`}
          style={{ padding: '6px 12px', fontSize: '0.8rem' }}
        >
          User Group
        </button>
        <button
          onClick={() => handleHighlightClick('access-recency')}
          className={`btn ${activeHighlight === 'access-recency' ? 'btn-primary' : 'btn-ghost'}`}
          style={{ padding: '6px 12px', fontSize: '0.8rem' }}
        >
          Upload Recency
        </button>

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
              <div style={{ fontWeight: 650 }}>Failed to Load Relational Graph</div>
              <div className="text-secondary" style={{ fontSize: '0.85rem', marginTop: 4, textAlign: 'center' }}>{error}</div>
            </div>
          )}

          <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />

          {/* Floating Legend */}
          <div className="kpi-graph-legend">
            <div className="kpi-graph-legend-title">Legend</div>
            <div className="kpi-graph-legend-grid">
              <div className="kpi-graph-legend-item">
                <div className="kpi-graph-legend-dot" style={{ background: COLOR_MAP['Dashboard'] }} />
                <span className="kpi-graph-legend-label">Dashboard</span>
              </div>
              <div className="kpi-graph-legend-item">
                <div className="kpi-graph-legend-dot" style={{ background: COLOR_MAP['KPI'] }} />
                <span className="kpi-graph-legend-label">KPI</span>
              </div>
              <div className="kpi-graph-legend-item">
                <div className="kpi-graph-legend-dot" style={{ background: COLOR_MAP['Business Area'] }} />
                <span className="kpi-graph-legend-label">Business Area</span>
              </div>
              <div className="kpi-graph-legend-item">
                <div className="kpi-graph-legend-dot" style={{ background: COLOR_MAP['User Group'] }} />
                <span className="kpi-graph-legend-label">User Group</span>
              </div>
              <div className="kpi-graph-legend-item">
                <div className="kpi-graph-legend-dot" style={{ background: COLOR_MAP['Table'] }} />
                <span className="kpi-graph-legend-label">Table</span>
              </div>
              <div className="kpi-graph-legend-item">
                <div className="kpi-graph-legend-dot" style={{ background: COLOR_MAP['Granularity Level'] }} />
                <span className="kpi-graph-legend-label">Granularity</span>
              </div>
              <div className="kpi-graph-legend-item">
                <div className="kpi-graph-legend-dot" style={{ background: COLOR_MAP['Access Recency'] }} />
                <span className="kpi-graph-legend-label">Recency</span>
              </div>
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
                Landscape Insights
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
            height="100%"
            isMaximizedView={true}
            onMinimize={() => setIsMaximized(false)}
          />
        </div>
      )}
    </div>
  );
}
