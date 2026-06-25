import { useEffect, useRef, useState, useMemo } from 'react';
import * as d3 from 'd3';
import { AlertCircle, Sparkles, Maximize2, X, Loader2 } from 'lucide-react';
import { api } from '../../api/client';
import { Loader } from './index';

const COLOR_MAP = {
  'Report': '#6366f1',            // Bright Indigo
  'Dashboard': '#2563eb',         // Royal Blue
  'KPI': '#10b981',               // Emerald Green
  'Shared KPI': '#d946ef',        // Bright Fuchsia
  'Unique KPI': '#f59e0b',        // Amber — exclusive to one report
  'Line of Business': '#8b5cf6',  // Violet
  'Business Area': '#a855f7',     // Purple
  'User Group': '#ec4899',        // Pink
  'Table': '#e11d48',             // Crimson
  'Datasource': '#ea580c',        // Rust Orange
  'Shared Datasource': '#0891b2', // Dark Cyan/Teal
};

const LEGEND_ITEMS = [
  { group: 'Report', label: 'Report' },
  { group: 'Dashboard', label: 'Sheet' },
  { group: 'KPI', label: 'KPI' },
  { group: 'Shared KPI', label: 'Shared KPI' },
  { group: 'Unique KPI', label: 'Unique KPI' },
  { group: 'Line of Business', label: 'Line of Business' },
  { group: 'Business Area', label: 'Business Area' },
  { group: 'User Group', label: 'User Group' },
  { group: 'Table', label: 'Table' },
  { group: 'Datasource', label: 'Datasource' },
  { group: 'Shared Datasource', label: 'Shared Source' },
];

const ACTION_COLORS = {
  keep: 'var(--accent-emerald)',
  merge: 'var(--accent-amber)',
  decommission: 'var(--status-decommission)',
  delete: 'var(--status-decommission)',
  review: 'var(--accent-blue)',
};

const getLegendShapeSvg = (group, color) => {
  const size = 12;
  return (
    <svg width={size} height={size} style={{ marginRight: 8, flexShrink: 0 }}>
      <circle cx={6} cy={6} r={5} fill={color} />
    </svg>
  );
};

export function KPIDashboardGraph({
  dashboards,
  workbookId,
  workbookIds,
  view = 'landscape',
  height = '600px',
  isMaximizedView = false,
  onMinimize,
  filterAction = null,
  title = null,
}) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const tooltipRef = useRef(null);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isMaximized, setIsMaximized] = useState(false);
  const [activeHighlight, setActiveHighlight] = useState(null);
  const [presentGroups, setPresentGroups] = useState(new Set());
  const [clickedNode, setClickedNode] = useState(null);

  const nodesRef = useRef([]);
  const linksRef = useRef([]);
  const nodeSelectionRef = useRef(null);
  const linkSelectionRef = useRef(null);
  const linkLabelSelectionRef = useRef(null);

  const graphParams = useMemo(() => ({
    dashboards,
    workbookId,
    workbookIds,
    view,
  }), [dashboards, workbookId, workbookIds, view]);

  const isRationalization = view === 'rationalization';

  const filterActionRef = useRef(null);

  useEffect(() => {
    setClickedNode(null);
  }, [filterAction]);

  useEffect(() => {
    let simulation;
    let tooltipDiv = d3.select(tooltipRef.current);

    const fetchDataAndDraw = async () => {
      try {
        setIsLoading(true);
        setError(null);
        
        const rawData = await api.getKpiGraphData(graphParams);
        const excludedGroups = new Set(['Line of Business', 'Business Area', 'User Group', 'Granularity Level', 'Upload Age']);
        const filteredNodes = (rawData.nodes || []).filter(n => !excludedGroups.has(n.group));
        const filteredNodeIds = new Set(filteredNodes.map(n => n.id));
        const filteredLinks = (rawData.links || []).filter(l => {
          const sourceId = typeof l.source === 'object' ? l.source.id : l.source;
          const targetId = typeof l.target === 'object' ? l.target.id : l.target;
          return filteredNodeIds.has(sourceId) && filteredNodeIds.has(targetId);
        });

        const data = { nodes: filteredNodes, links: filteredLinks };

        if (!data.nodes || data.nodes.length === 0) {
          throw new Error('No graph nodes found for the selected scope.');
        }

        const sharedKpiIds = new Set();
        const uniqueKpiIds = new Set();
        data.nodes.forEach(n => {
          if (n.group !== 'KPI') return;
          const connectedWbs = new Set();
          data.links.forEach(l => {
            const s = typeof l.source === 'object' ? l.source.id : l.source;
            const t = typeof l.target === 'object' ? l.target.id : l.target;
            if (s === n.id) {
              const other = data.nodes.find(node => node.id === t);
              if (other && (other.group === 'Report' || other.group === 'Dashboard')) connectedWbs.add(other.id);
            }
            if (t === n.id) {
              const other = data.nodes.find(node => node.id === s);
              if (other && (other.group === 'Report' || other.group === 'Dashboard')) connectedWbs.add(other.id);
            }
          });
          if (connectedWbs.size > 1) sharedKpiIds.add(n.id);
          else if (connectedWbs.size === 1) uniqueKpiIds.add(n.id);
        });
        const legendGroups = new Set(data.nodes.map(n => n.group));
        if (sharedKpiIds.size > 0) legendGroups.add('Shared KPI');
        if (uniqueKpiIds.size > 0) legendGroups.add('Unique KPI');
        setPresentGroups(legendGroups);
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

      nodesRef.current = nodes;
      linksRef.current = links;
      nodeSelectionRef.current = node;
      linkSelectionRef.current = link;
      linkLabelSelectionRef.current = linkLabel;

      // Compute shared / unique KPI nodes dynamically
      const sharedNodeIds = new Set();
      const uniqueNodeIds = new Set();
      const getConnectedReportIds = (nodeId) => {
        const connectedWbs = new Set();
        links.forEach(l => {
          const s = typeof l.source === 'object' ? l.source.id : l.source;
          const t = typeof l.target === 'object' ? l.target.id : l.target;
          if (s === nodeId) {
            const other = nodes.find(node => node.id === t);
            if (other && (other.group === 'Report' || other.group === 'Dashboard')) connectedWbs.add(other.id);
          }
          if (t === nodeId) {
            const other = nodes.find(node => node.id === s);
            if (other && (other.group === 'Report' || other.group === 'Dashboard')) connectedWbs.add(other.id);
          }
        });
        return connectedWbs;
      };

      nodes.forEach(n => {
        if (n.group === 'KPI' || n.group === 'Datasource') {
          const connectedWbs = getConnectedReportIds(n.id);
          if (connectedWbs.size > 1) {
            sharedNodeIds.add(n.id);
          } else if (connectedWbs.size === 1) {
            uniqueNodeIds.add(n.id);
          }
        }
      });

      // Setup symbol generator
      const symbolGen = d3.symbol();

      const getSymbolType = (group) => {
        return d3.symbolCircle;
      };

      const getSymbolSize = (group) => {
        if (group === 'Report' || group === 'Dashboard') {
          return 900; // area in square pixels
        }
        return 400; // area in square pixels
      };

      // Draw node shapes
      node.append('path')
        .attr('d', d => symbolGen.type(getSymbolType(d.group)).size(getSymbolSize(d.group))())
        .attr('fill', d => {
          if (d.group === 'Report' && d.action) {
            return ACTION_COLORS[d.action] || COLOR_MAP['Report'];
          }
          if (d.group === 'KPI' && sharedNodeIds.has(d.id)) {
            return COLOR_MAP['Shared KPI'];
          }
          if (d.group === 'KPI' && uniqueNodeIds.has(d.id)) {
            return COLOR_MAP['Unique KPI'];
          }
          if (d.group === 'Datasource' && sharedNodeIds.has(d.id)) {
            return COLOR_MAP['Shared Datasource'];
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
        .attr('y', d => (d.group === 'Report' || d.group === 'Dashboard') ? 28 : 20)
        .attr('text-anchor', 'middle')
        .attr('font-size', '11px')
        .attr('font-weight', d => (d.group === 'Report' || d.group === 'Dashboard') ? 'bold' : '500')
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
        setClickedNode(prev => prev?.id === d.id ? null : d);
      });

      svg.on('click', () => {
        setClickedNode(null);
        setActiveHighlight(null);
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

      // Selections refs are updated here for state-driven updates
    };

    fetchDataAndDraw();

    return () => {
      if (simulation) simulation.stop();
    };
  }, [graphParams]);

  // Apply styling highlights dynamically when filters, clicks, or state changes
  useEffect(() => {
    if (isLoading || !nodeSelectionRef.current || !linkSelectionRef.current) return;

    const nodes = nodesRef.current || [];
    const links = linksRef.current || [];
    const nodeSelection = nodeSelectionRef.current;
    const linkSelection = linkSelectionRef.current;
    const linkLabelSelection = linkLabelSelectionRef.current;

    // Helper to get source/target IDs regardless of whether they are objects or strings
    const getSourceId = (l) => typeof l.source === 'object' ? l.source.id : l.source;
    const getTargetId = (l) => typeof l.target === 'object' ? l.target.id : l.target;

    // Helper to find links between two nodes
    const getLinksBetween = (idA, idB) => {
      return links.filter(l => {
        const s = getSourceId(l);
        const t = getTargetId(l);
        return (s === idA && t === idB) || (s === idB && t === idA);
      });
    };

    // Helper to find links connected to a single node
    const getLinksConnectedTo = (id) => {
      return links.filter(l => {
        const s = getSourceId(l);
        const t = getTargetId(l);
        return s === id || t === id;
      });
    };

    const isBridgeGroup = (group) => (
      group === 'KPI' || group === 'Shared KPI' || group === 'Shared Datasource'
    );

    const highlightBridgesBetween = (srcId, tgtId, srcColor, tgtColor, flowClass = null) => {
      nodes.forEach(n => {
        if (!isBridgeGroup(n.group)) return;
        const linksSrc = getLinksBetween(n.id, srcId);
        const linksTgt = getLinksBetween(n.id, tgtId);

        if (linksSrc.length > 0 && linksTgt.length > 0) {
          nodesToHighlight.add(n.id);
          linksSrc.forEach(l => {
            linksToHighlight.add(l);
            linkColors.set(l, srcColor);
            linkStrokeWidths.set(l, 3);
            if (flowClass) linkFlowClasses.set(l, flowClass);
          });
          linksTgt.forEach(l => {
            linksToHighlight.add(l);
            linkColors.set(l, tgtColor);
            linkStrokeWidths.set(l, 3);
          });
          return;
        }

        if (n.group === 'KPI' && linksSrc.length > 0 && linksTgt.length === 0) {
          nodesToHighlight.add(n.id);
          linksSrc.forEach(l => {
            linksToHighlight.add(l);
            linkColors.set(l, srcColor);
            linkStrokeWidths.set(l, 3);
            if (flowClass) linkFlowClasses.set(l, flowClass);
          });
          return;
        }

        if (n.group === 'KPI' && linksTgt.length > 0 && linksSrc.length === 0) {
          nodesToHighlight.add(n.id);
          linksTgt.forEach(l => {
            linksToHighlight.add(l);
            linkColors.set(l, tgtColor);
            linkStrokeWidths.set(l, 3);
          });
        }
      });
    };

    // 1. Reset all styles
    nodeSelection.style('opacity', 1);
    nodeSelection.selectAll('path')
      .attr('stroke', 'var(--bg-surface)')
      .attr('stroke-width', 2.5)
      .classed('d3-node-pulse-decom', false)
      .classed('d3-node-pulse-merge', false)
      .classed('d3-node-pulse-keep', false);

    linkSelection
      .attr('stroke-opacity', 0.6)
      .attr('stroke', 'var(--glass-border)')
      .attr('stroke-width', d => d.stroke_width || 2)
      .classed('d3-link-flow', false)
      .classed('d3-link-pulse', false);

    if (linkLabelSelection) {
      linkLabelSelection.style('opacity', 1);
    }

    // Determine what to highlight
    let nodesToHighlight = new Set();
    let nodePulseClasses = new Map(); // id -> 'decom' | 'merge' | 'keep'
    let linksToHighlight = new Set();
    let linkColors = new Map(); // link -> color string
    let linkStrokeWidths = new Map(); // link -> number
    let linkFlowClasses = new Map(); // link -> 'flow' | 'pulse'

    let isAnyHighlightActive = false;

    // A. Priority 1: User clicked on a specific node in the graph
    if (clickedNode) {
      isAnyHighlightActive = true;
      const d = clickedNode;
      nodesToHighlight.add(d.id);

      if (d.group === 'Report') {
        const action = d.action || 'keep';
        if (action === 'decommission' || action === 'delete') {
          nodePulseClasses.set(d.id, 'decom');
          const targetName = d.merge_with_name;
          const targetNode = nodes.find(n => n.group === 'Report' && n.label === targetName);

          if (targetNode) {
            nodesToHighlight.add(targetNode.id);
            nodePulseClasses.set(targetNode.id, 'keep');

            // Direct link
            getLinksBetween(d.id, targetNode.id).forEach(l => {
              linksToHighlight.add(l);
              linkColors.set(l, 'var(--accent-rose)');
              linkStrokeWidths.set(l, 4);
              linkFlowClasses.set(l, 'flow');
            });

            // Shared + unique KPI bridges
            highlightBridgesBetween(
              d.id,
              targetNode.id,
              'var(--accent-rose)',
              'var(--accent-emerald)',
              'flow',
            );
          } else {
            getLinksConnectedTo(d.id).forEach(l => {
              linksToHighlight.add(l);
              linkColors.set(l, 'var(--accent-rose)');
              linkStrokeWidths.set(l, 3);
              linkFlowClasses.set(l, 'flow');
              const otherId = getSourceId(l) === d.id ? getTargetId(l) : getSourceId(l);
              nodesToHighlight.add(otherId);
            });
          }
        } else if (action === 'merge') {
          nodePulseClasses.set(d.id, 'merge');
          const targetName = d.merge_with_name;
          const targetNode = nodes.find(n => n.group === 'Report' && n.label === targetName);

          if (targetNode) {
            nodesToHighlight.add(targetNode.id);
            nodePulseClasses.set(targetNode.id, 'keep');

            // Direct link
            getLinksBetween(d.id, targetNode.id).forEach(l => {
              linksToHighlight.add(l);
              linkColors.set(l, 'var(--accent-amber)');
              linkStrokeWidths.set(l, 5);
              linkFlowClasses.set(l, 'pulse');
            });

            highlightBridgesBetween(
              d.id,
              targetNode.id,
              'var(--accent-amber)',
              'var(--accent-emerald)',
              'pulse',
            );
          } else {
            getLinksConnectedTo(d.id).forEach(l => {
              linksToHighlight.add(l);
              linkColors.set(l, 'var(--accent-amber)');
              linkStrokeWidths.set(l, 3.5);
              linkFlowClasses.set(l, 'pulse');
              const otherId = getSourceId(l) === d.id ? getTargetId(l) : getSourceId(l);
              nodesToHighlight.add(otherId);
            });
          }
        } else if (action === 'keep') {
          nodePulseClasses.set(d.id, 'keep');
          getLinksConnectedTo(d.id).forEach(l => {
            linksToHighlight.add(l);
            linkColors.set(l, 'var(--accent-emerald)');
            linkStrokeWidths.set(l, 3);
            const otherId = getSourceId(l) === d.id ? getTargetId(l) : getSourceId(l);
            nodesToHighlight.add(otherId);
          });
        } else {
          getLinksConnectedTo(d.id).forEach(l => {
            linksToHighlight.add(l);
            linkColors.set(l, 'var(--accent-blue)');
            linkStrokeWidths.set(l, 3);
            const otherId = getSourceId(l) === d.id ? getTargetId(l) : getSourceId(l);
            nodesToHighlight.add(otherId);
          });
        }
      } else {
        // Clicked a shared/KPI node
        getLinksConnectedTo(d.id).forEach(l => {
          linksToHighlight.add(l);
          linkColors.set(l, 'var(--accent-blue)');
          linkStrokeWidths.set(l, 3);
          const otherId = getSourceId(l) === d.id ? getTargetId(l) : getSourceId(l);
          nodesToHighlight.add(otherId);
        });
      }
    }
    // B. Priority 2: Filter action pill is selected
    else if (filterAction) {
      isAnyHighlightActive = true;

      const matchAction = (nodeAction) => {
        if (filterAction === 'decommission') return nodeAction === 'decommission' || nodeAction === 'delete';
        return nodeAction === filterAction;
      };

      const sourceNodes = nodes.filter(n => n.group === 'Report' && matchAction(n.action));

      sourceNodes.forEach(srcNode => {
        nodesToHighlight.add(srcNode.id);
        
        if (filterAction === 'decommission') {
          nodePulseClasses.set(srcNode.id, 'decom');
          const targetName = srcNode.merge_with_name;
          const targetNode = nodes.find(n => n.group === 'Report' && n.label === targetName);

          if (targetNode) {
            nodesToHighlight.add(targetNode.id);
            nodePulseClasses.set(targetNode.id, 'keep');

            // Direct link
            getLinksBetween(srcNode.id, targetNode.id).forEach(l => {
              linksToHighlight.add(l);
              linkColors.set(l, 'var(--accent-rose)');
              linkStrokeWidths.set(l, 4);
              linkFlowClasses.set(l, 'flow');
            });

            highlightBridgesBetween(
              srcNode.id,
              targetNode.id,
              'var(--accent-rose)',
              'var(--accent-emerald)',
              'flow',
            );
          } else {
            getLinksConnectedTo(srcNode.id).forEach(l => {
              linksToHighlight.add(l);
              linkColors.set(l, 'var(--accent-rose)');
              linkStrokeWidths.set(l, 3);
              linkFlowClasses.set(l, 'flow');
              const otherId = getSourceId(l) === srcNode.id ? getTargetId(l) : getSourceId(l);
              nodesToHighlight.add(otherId);
            });
          }
        } else if (filterAction === 'merge') {
          nodePulseClasses.set(srcNode.id, 'merge');
          const targetName = srcNode.merge_with_name;
          const targetNode = nodes.find(n => n.group === 'Report' && n.label === targetName);

          if (targetNode) {
            nodesToHighlight.add(targetNode.id);
            nodePulseClasses.set(targetNode.id, 'keep');

            // Direct link
            getLinksBetween(srcNode.id, targetNode.id).forEach(l => {
              linksToHighlight.add(l);
              linkColors.set(l, 'var(--accent-amber)');
              linkStrokeWidths.set(l, 5);
              linkFlowClasses.set(l, 'pulse');
            });

            highlightBridgesBetween(
              srcNode.id,
              targetNode.id,
              'var(--accent-amber)',
              'var(--accent-emerald)',
              'pulse',
            );
          } else {
            getLinksConnectedTo(srcNode.id).forEach(l => {
              linksToHighlight.add(l);
              linkColors.set(l, 'var(--accent-amber)');
              linkStrokeWidths.set(l, 3.5);
              linkFlowClasses.set(l, 'pulse');
              const otherId = getSourceId(l) === srcNode.id ? getTargetId(l) : getSourceId(l);
              nodesToHighlight.add(otherId);
            });
          }
        } else if (filterAction === 'keep') {
          nodePulseClasses.set(srcNode.id, 'keep');
          getLinksConnectedTo(srcNode.id).forEach(l => {
            linksToHighlight.add(l);
            linkColors.set(l, 'var(--accent-emerald)');
            linkStrokeWidths.set(l, 3);
            const otherId = getSourceId(l) === srcNode.id ? getTargetId(l) : getSourceId(l);
            nodesToHighlight.add(otherId);
          });
        }
      });
    }
    // C. Priority 3: Toolbar highlight category is selected
    else if (activeHighlight) {
      isAnyHighlightActive = true;
      const highlightTargets = new Set();
      
      if (activeHighlight === 'kpi') {
        nodes.forEach(n => { if (n.group === 'KPI') highlightTargets.add(n.id); });
      } else if (activeHighlight === 'unique-kpi') {
        nodes.forEach(n => {
          if (n.group !== 'KPI') return;
          const connectedWbs = new Set();
          links.forEach(l => {
            const s = getSourceId(l);
            const t = getTargetId(l);
            if (s === n.id) {
              const other = nodes.find(node => node.id === t);
              if (other && (other.group === 'Report' || other.group === 'Dashboard')) connectedWbs.add(other.id);
            }
            if (t === n.id) {
              const other = nodes.find(node => node.id === s);
              if (other && (other.group === 'Report' || other.group === 'Dashboard')) connectedWbs.add(other.id);
            }
          });
          if (connectedWbs.size === 1) highlightTargets.add(n.id);
        });
      } else if (activeHighlight === 'tables') {
        nodes.forEach(n => { if (n.group === 'Table') highlightTargets.add(n.id); });
      } else if (activeHighlight === 'user-group') {
        nodes.forEach(n => { if (n.group === 'User Group') highlightTargets.add(n.id); });
      } else if (activeHighlight === 'upload-age') {
        nodes.forEach(n => { if (n.group === 'Upload Age') highlightTargets.add(n.id); });
      } else if (activeHighlight === 'datasource') {
        nodes.forEach(n => { if (n.group === 'Datasource') highlightTargets.add(n.id); });
      } else if (activeHighlight === 'common-kpi' || activeHighlight === 'shared-kpi') {
        nodes.forEach(n => {
          if (n.group === 'KPI') {
            const connectedWbs = new Set();
            links.forEach(l => {
              const s = getSourceId(l);
              const t = getTargetId(l);
              if (s === n.id) {
                const other = nodes.find(node => node.id === t);
                if (other && (other.group === 'Report' || other.group === 'Dashboard')) {
                  connectedWbs.add(other.id);
                }
              }
              if (t === n.id) {
                const other = nodes.find(node => node.id === s);
                if (other && (other.group === 'Report' || other.group === 'Dashboard')) {
                  connectedWbs.add(other.id);
                }
              }
            });
            if (connectedWbs.size > 1) {
              highlightTargets.add(n.id);
            }
          } else if (view === 'rationalization' && n.group === 'Shared KPI') {
            highlightTargets.add(n.id);
          }
        });
      } else if (activeHighlight === 'shared-source') {
        if (view === 'rationalization') {
          nodes.forEach(n => { if (n.group === 'Shared Datasource') highlightTargets.add(n.id); });
        } else {
          nodes.forEach(n => {
            if (n.group === 'Shared Datasource' || n.group === 'Datasource') {
              const connectedWbs = new Set();
              links.forEach(l => {
                const s = getSourceId(l);
                const t = getTargetId(l);
                if (s === n.id) {
                  const other = nodes.find(node => node.id === t);
                  if (other && (other.group === 'Report' || other.group === 'Dashboard')) {
                    connectedWbs.add(other.id);
                  }
                }
                if (t === n.id) {
                  const other = nodes.find(node => node.id === s);
                  if (other && (other.group === 'Report' || other.group === 'Dashboard')) {
                    connectedWbs.add(other.id);
                  }
                }
              });
              if (connectedWbs.size > 1) {
                highlightTargets.add(n.id);
              }
            }
          });
        }
      } else if (activeHighlight === 'report') {
        nodes.forEach(n => { if (n.group === 'Report') highlightTargets.add(n.id); });
      }

      highlightTargets.forEach(id => nodesToHighlight.add(id));

      links.forEach(l => {
        const s = getSourceId(l);
        const t = getTargetId(l);
        if (highlightTargets.has(s) || highlightTargets.has(t)) {
          linksToHighlight.add(l);
          linkColors.set(l, 'var(--accent-blue)');
          nodesToHighlight.add(s);
          nodesToHighlight.add(t);
        }
      });
    }

    // Apply styles to elements based on computed highlights
    if (isAnyHighlightActive) {
      nodeSelection.style('opacity', n => nodesToHighlight.has(n.id) ? 1 : 0.06);

      nodeSelection.selectAll('path')
        .each(function(n) {
          const p = d3.select(this);
          const pulse = nodePulseClasses.get(n.id);
          p.classed('d3-node-pulse-decom', pulse === 'decom');
          p.classed('d3-node-pulse-merge', pulse === 'merge');
          p.classed('d3-node-pulse-keep', pulse === 'keep');
          
          if (pulse) {
            p.attr('stroke-width', null).attr('stroke', null);
          } else if (nodesToHighlight.has(n.id) && activeHighlight) {
            p.attr('stroke', 'var(--accent-purple)').attr('stroke-width', 4);
          } else {
            p.attr('stroke', 'var(--bg-surface)').attr('stroke-width', 2.5);
          }
        });

      linkSelection
        .attr('stroke-opacity', l => linksToHighlight.has(l) ? 1 : 0.04)
        .attr('stroke', l => {
          if (linksToHighlight.has(l)) {
            return linkColors.get(l) || 'var(--accent-blue)';
          }
          return 'var(--glass-border)';
        })
        .attr('stroke-width', l => {
          if (linksToHighlight.has(l)) {
            return linkStrokeWidths.get(l) || 4;
          }
          return l.stroke_width || 2;
        })
        .classed('d3-link-flow', l => linkFlowClasses.get(l) === 'flow')
        .classed('d3-link-pulse', l => linkFlowClasses.get(l) === 'pulse');

      if (linkLabelSelection) {
        linkLabelSelection.style('opacity', l => linksToHighlight.has(l) ? 1 : 0.04);
      }
    }
  }, [filterAction, clickedNode, activeHighlight, isLoading]);

  const handleHighlightClick = (type) => {
    const nextHighlight = activeHighlight === type ? null : type;
    setActiveHighlight(nextHighlight);
    setClickedNode(null);
  };

  return (
    <div className="kpi-graph-container" style={{ height }}>
      {/* Toolbar / Filters */}
      <div className="kpi-graph-toolbar">
        {title && <h3 style={{ margin: 0, fontSize: '1.125rem', fontWeight: 700, marginRight: '16px', color: 'var(--text-primary)' }}>{title}</h3>}
        <span className="kpi-graph-toolbar-title">Highlight Connections:</span>
        {isRationalization ? (
          <>
            <button
              onClick={() => handleHighlightClick('report')}
              className={`btn ${activeHighlight === 'report' ? 'btn-primary' : 'btn-ghost'}`}
              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
            >
              Reports
            </button>
            <button
              onClick={() => handleHighlightClick('shared-kpi')}
              className={`btn ${activeHighlight === 'shared-kpi' ? 'btn-primary' : 'btn-ghost'}`}
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
            {presentGroups.has('Unique KPI') && (
              <button
                onClick={() => handleHighlightClick('unique-kpi')}
                className={`btn ${activeHighlight === 'unique-kpi' ? 'btn-primary' : 'btn-ghost'}`}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              >
                Unique KPIs
              </button>
            )}
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
            {presentGroups.has('Datasource') && (
              <button
                onClick={() => handleHighlightClick('shared-source')}
                className={`btn ${activeHighlight === 'shared-source' ? 'btn-primary' : 'btn-ghost'}`}
                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              >
                Filter Shared Sources
              </button>
            )}
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
          </>
        )}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
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
                  {getLegendShapeSvg(item.group, COLOR_MAP[item.group])}
                  <span className="kpi-graph-legend-label">{item.label}</span>
                </div>
              ))}
              {isRationalization && presentGroups.has('Report') && (
                <>
                  <div className="kpi-graph-legend-item">
                    {getLegendShapeSvg('Report', ACTION_COLORS.keep)}
                    <span className="kpi-graph-legend-label">Keep</span>
                  </div>
                  <div className="kpi-graph-legend-item">
                    {getLegendShapeSvg('Report', ACTION_COLORS.merge)}
                    <span className="kpi-graph-legend-label">Merge</span>
                  </div>
                  <div className="kpi-graph-legend-item">
                    {getLegendShapeSvg('Report', ACTION_COLORS.decommission)}
                    <span className="kpi-graph-legend-label">Decommission</span>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Floating Tooltip */}
          <div ref={tooltipRef} className="kpi-graph-tooltip" />
        </div>

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
