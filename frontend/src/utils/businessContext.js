/**
 * Plain-language helpers for business-facing Intelligence views.
 */

export function sheetTypeLabel(sheetType) {
  if (sheetType === 'summary_report') return 'Summary report';
  if (sheetType === 'raw_data') return 'Source data';
  if (sheetType === 'helper') return 'Supporting sheet';
  return sheetType?.replace(/_/g, ' ') || 'Sheet';
}

export function columnTypeLabel(columnType) {
  if (columnType === 'formula_based' || columnType === 'pivot_value') return 'Calculated';
  if (columnType === 'label') return 'Category';
  return 'Data';
}

export function describeActiveFilters(filters) {
  if (!filters?.length) return null;
  return filters.map(f => {
    const name = f.filter_name || f.name || 'Filter';
    const value = f.filter_value ?? f.value ?? '(All)';
    return { name, value, text: `${name} is set to ${value}` };
  });
}

export function parsePivotLayouts(pivotConfiguration) {
  if (!pivotConfiguration) return [];
  const items = Array.isArray(pivotConfiguration) ? pivotConfiguration : [pivotConfiguration];
  return items.filter(Boolean).map((p, i) => ({
    name: p.pivot_table_name || p.name || `Report ${i + 1}`,
    dataSource: p.raw_data_sheet_name || p.data_source_sheet || null,
    rowFields: p.row_fields || p.rows || [],
    columnFields: p.column_fields || p.columns || [],
    filterFields: p.filter_fields || [],
    valueFields: (p.value_fields || p.values || []).map(v =>
      typeof v === 'string' ? v : (v.name || v.source_column || v.label)
    ).filter(Boolean),
    range: p.table_range || null,
  }));
}

export function describePivotLayout(pivot) {
  const parts = [];
  if (p.dataSource) parts.push(`pulls data from the "${p.dataSource}" sheet`);
  if (p.rowFields.length) parts.push(`broken down by ${p.rowFields.join(', ')}`);
  if (p.columnFields.length) parts.push(`columns: ${p.columnFields.join(', ')}`);
  if (p.valueFields.length) parts.push(`shows ${p.valueFields.join(', ')}`);
  if (p.filterFields.length) parts.push(`can be filtered by ${p.filterFields.join(', ')}`);
  return parts.length ? parts.join('; ') + '.' : 'Pivot-style summary report.';
}

export function describeRelationships(relationships) {
  if (!relationships?.length) return [];
  return relationships.map(rel => {
    if (typeof rel === 'string') return rel;
    if (rel?.description) return rel.description;
    return String(rel);
  });
}

export function workbookSummaryText(workbook, summaryDashboard) {
  if (summaryDashboard?.ai_summary?.trim()) return summaryDashboard.ai_summary.trim();
  if (workbook?.purpose?.trim() && !workbook.purpose.includes('decommission and rationalization')) {
    return workbook.purpose.trim();
  }
  return null;
}

export function sheetSummaryText(dashboard, worksheets) {
  if (dashboard?.ai_summary?.trim()) return dashboard.ai_summary.trim();

  const purposes = (worksheets || [])
    .map(ws => ws.business_purpose)
    .filter(Boolean);
  if (purposes.length === 1) return purposes[0];
  if (purposes.length > 1) {
    return `This sheet contains ${purposes.length} tables: ${purposes.slice(0, 2).join(' ')}${purposes.length > 2 ? '…' : ''}`;
  }

  if (dashboard?.sheet_type === 'raw_data') {
    return 'Source data sheet that feeds summary reports and calculations.';
  }

  return null;
}
