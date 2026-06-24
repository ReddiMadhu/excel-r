import React, { useMemo } from 'react';
import ReactFlow, { Background, Controls, MiniMap, Handle, Position } from 'reactflow';
import 'reactflow/dist/style.css';

// Custom node component matching the BI Compass node style
function FormulaNode({ data }) {
  const isTarget = data.isTarget;
  const isRaw = data.column_type === 'raw' || data.is_raw;
  
  // Custom orange/amber palette styling to match BI Compass styles
  let bgColor = '#3b82f6'; // blue for standard formula columns
  let borderStyle = '1px solid #2563eb';
  
  if (isTarget) {
    bgColor = '#ec3f06'; // primary orange for target column
    borderStyle = '2px solid #c42e08';
  } else if (isRaw) {
    bgColor = '#10b981'; // emerald green for raw inputs
    borderStyle = '1px solid #059669';
  } else if (data.computation_type === 'SUMIFS' || data.computation_type === 'COUNTIFS') {
    bgColor = '#fb7e3c'; // orange/amber for aggregations
    borderStyle = '1px solid #d97706';
  }

  return (
    <div
      style={{
        backgroundColor: bgColor,
        border: borderStyle,
        minWidth: 200,
        boxShadow: 'var(--shadow-md)',
        padding: '12px 16px',
        borderRadius: 'var(--radius-md)',
        color: 'white',
        fontFamily: "'Inter', sans-serif",
        position: 'relative',
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ background: '#ffffff', width: 6, height: 6 }}
      />
      <Handle
        type="source"
        position={Position.Right}
        style={{ background: '#ffffff', width: 6, height: 6 }}
      />
      <div style={{ fontWeight: 600, fontSize: '0.875rem', marginBottom: 4 }}>{data.label}</div>
      <div style={{ fontSize: '10px', opacity: 0.9, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: "'JetBrains Mono', monospace", marginBottom: 4 }}>
        {data.table_name ? `${data.table_name}` : 'Report'}
      </div>
      {data.formula && (
        <div style={{ fontSize: '10px', opacity: 0.8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: "'JetBrains Mono', monospace" }} title={data.formula}>
          {data.formula}
        </div>
      )}
      <div style={{ fontSize: '9px', opacity: 0.75, marginTop: 4, display: 'flex', justifyContent: 'space-between' }}>
        <span>{data.column_type || (isRaw ? 'RAW' : 'FORMULA')}</span>
        <span>{data.data_type || ''}</span>
      </div>
    </div>
  );
}

const nodeTypes = {
  formulaNode: FormulaNode,
};

export default function LineageGraph({ columnName, tableName, formula, lineage }) {
  const { nodes, edges } = useMemo(() => {
    const nodesList = [];
    const edgesList = [];
    const nodeSet = new Set();
    const edgeSet = new Set();
    
    function traverse(nodeData, depth = 0) {
      const currentTable = nodeData.table_name || tableName;
      const currentColumn = nodeData.column_name || columnName;
      const nodeId = `${currentTable}::${currentColumn}`;
      
      if (nodeSet.has(nodeId)) return nodeId;
      nodeSet.add(nodeId);
      
      const isTarget = depth === 0;
      
      // Recursively traverse inputs
      const directInputs = nodeData.direct_inputs || (nodeData.nested_lineage?.direct_inputs) || [];
      const inputIds = [];
      
      directInputs.forEach(input => {
        const childId = traverse(input, depth + 1);
        inputIds.push(childId);
      });
      
      nodesList.push({
        id: nodeId,
        type: 'formulaNode',
        data: {
          label: currentColumn,
          table_name: currentTable,
          column_type: nodeData.column_type,
          is_raw: nodeData.is_raw || nodeData.column_type === 'raw',
          isTarget,
          formula: isTarget ? formula : (nodeData.nested_lineage?.formula || ''),
          data_type: nodeData.data_type,
          computation_type: nodeData.nested_lineage?.computation_type || nodeData.computation_type,
        },
        depth,
      });
      
      inputIds.forEach(childId => {
        const edgeId = `${childId}->${nodeId}`;
        if (!edgeSet.has(edgeId)) {
          edgeSet.add(edgeId);
          edgesList.push({
            id: edgeId,
            source: childId,
            target: nodeId,
            animated: true,
            style: { stroke: 'var(--accent-blue)', strokeWidth: 2 },
          });
        }
      });
      
      return nodeId;
    }
    
    if (lineage) {
      traverse(lineage, 0);
    } else {
      traverse({
        column_name: columnName,
        table_name: tableName,
        column_type: 'formula_based',
        is_raw: false,
      }, 0);
    }
    
    // Position calculations
    const depthGroups = {};
    nodesList.forEach(node => {
      if (!depthGroups[node.depth]) depthGroups[node.depth] = [];
      depthGroups[node.depth].push(node);
    });
    
    const depths = Object.keys(depthGroups).map(Number).sort((a, b) => b - a);
    const maxDepth = depths[0] || 0;
    
    nodesList.forEach(node => {
      const rank = maxDepth - node.depth;
      const x = rank * 300;
      
      const group = depthGroups[node.depth];
      const index = group.indexOf(node);
      const total = group.length;
      const y = 200 + (index - (total - 1) / 2) * 120;
      
      node.position = { x, y };
    });
    
    return { nodes: nodesList, edges: edgesList };
  }, [columnName, tableName, formula, lineage]);

  if (nodes.length === 0) {
    return (
      <div className="text-center text-muted" style={{ padding: 20 }}>
        No lineage graph data available.
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '400px', background: 'var(--bg-surface)', borderColor: 'var(--glass-border)', borderWidth: 1, borderStyle: 'solid', borderRadius: 'var(--radius-lg)' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        attributionPosition="bottom-left"
      >
        <Background color="var(--glass-border)" gap={16} />
        <Controls style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--glass-border)' }} />
        <MiniMap
          nodeColor={(node) => {
            if (node.data.isTarget) return '#ec3f06';
            if (node.data.column_type === 'raw' || node.data.is_raw) return '#10b981';
            return '#3b82f6';
          }}
          maskColor="rgba(0, 0, 0, 0.1)"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--glass-border)' }}
        />
      </ReactFlow>
    </div>
  );
}
