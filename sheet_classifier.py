"""
Sheet Classifier — Content-based classification of Excel sheets.

Replaces hardcoded name matching with analysis of actual sheet content:
formula density, numeric ratio, bold formatting, row count, etc.
Works regardless of what the sheet is named.
"""
import formatting_extractor


def classify_sheet(sheet_name, ws, all_sheets_info):
    """
    Classify a sheet based on content analysis, with name as secondary signal.
    
    Returns: 'summary_report', 'raw_data', 'helper', or 'unknown'.
    """
    max_row = ws.max_row or 0
    max_col = ws.max_column or 0
    
    if max_row == 0 or max_col == 0:
        return "empty"
    
    # 1. Content-based analysis (primary)
    content_type = _classify_by_content(ws, max_row, max_col)
    if content_type != "unknown":
        return content_type
    
    # 2. Name-based heuristics (fallback)
    name_type = _classify_by_name(sheet_name, max_row, max_col, all_sheets_info)
    if name_type != "unknown":
        return name_type
    
    # 3. Relative size comparison (last resort)
    return _classify_by_relative_size(sheet_name, max_row, all_sheets_info)


def _classify_by_content(ws, max_row, max_col):
    """
    Classify based on what the sheet actually contains.
    """
    # Sample the first N rows to gather statistics
    sample_rows = min(max_row, 100)
    sample_cols = min(max_col, 30)
    
    formula_count = 0
    numeric_count = 0
    text_count = 0
    bold_count = 0
    total_cells = 0
    
    for r in range(1, sample_rows + 1):
        for c in range(1, sample_cols + 1):
            cell = ws.cell(row=r, column=c)
            if cell.value is not None:
                total_cells += 1
                
                if isinstance(cell.value, str) and cell.value.startswith('='):
                    formula_count += 1
                elif isinstance(cell.value, (int, float)):
                    numeric_count += 1
                else:
                    text_count += 1
                
                if cell.font and cell.font.bold:
                    bold_count += 1
    
    if total_cells == 0:
        return "empty"
    
    formula_ratio = formula_count / total_cells
    numeric_ratio = numeric_count / total_cells
    text_ratio = text_count / total_cells
    bold_ratio = bold_count / total_cells
    
    # RAW DATA: Very high row count, mostly numeric, very few formulas
    # Raw data sheets are typically database dumps with 500+ rows of flat data
    if max_row > 500 and formula_ratio < 0.05 and numeric_ratio > 0.3:
        return "raw_data"
    
    # RAW DATA: High row count with tabular structure (many columns, consistent data)
    if max_row > 200 and max_col > 5 and formula_ratio < 0.1 and numeric_ratio > 0.25:
        return "raw_data"
    
    # SUMMARY/REPORT: Has formulas and bold formatting (structured report)
    if formula_ratio > 0.1 and bold_ratio > 0.03:
        return "summary_report"
    
    # SUMMARY (pivot-based): No formulas but structured with bold sections
    # Pivot tables don't show formulas in data_only mode, but have bold headers
    if bold_ratio > 0.08 and 10 < max_row < 200 and numeric_ratio > 0.2:
        return "summary_report"
    
    # HELPER: Very small sheet with mostly text
    if max_row < 50 and max_col < 10 and text_ratio > 0.5:
        return "helper"
    
    return "unknown"


def _classify_by_name(sheet_name, max_row, max_col, all_sheets_info):
    """
    Fallback classification using sheet name heuristics.
    """
    name_lower = sheet_name.lower().strip()
    
    # Summary/report indicators
    summary_keywords = [
        "summary", "report", "exhibit", "exb", "dashboard", 
        "overview", "analysis", "reserve detail", "reconciliation",
    ]
    if any(kw in name_lower for kw in summary_keywords):
        return "summary_report"
    
    # Raw data indicators
    raw_keywords = [
        "synthetic_data", "sql_data", "warehouse data", "raw_data", 
        "data", "raw", "extract", "dump", "source", "query",
        "policy_data", "claims_data",
    ]
    if name_lower in raw_keywords or any(kw in name_lower for kw in raw_keywords):
        if max_row > 50:  # Must have substantial data
            return "raw_data"
    
    # Helper indicators
    helper_keywords = [
        "sheet1", "helper", "notes", "readme", "instructions",
        "config", "parameters", "lookup", "reference",
    ]
    if name_lower in helper_keywords:
        if max_row < 100:
            return "helper"
    
    return "unknown"


def _classify_by_relative_size(sheet_name, max_row, all_sheets_info):
    """
    Last resort: classify based on relative size to other sheets.
    """
    if not all_sheets_info:
        return "unknown"
    
    # Find the sheet with most rows (likely raw data)
    max_other_rows = max(s['max_row'] for s in all_sheets_info)
    
    # If this sheet has the most rows and is large, it's likely raw data
    if max_row == max_other_rows and max_row > 100:
        return "raw_data"
    
    # If this sheet is tiny, it's a helper
    if max_row < 50:
        return "helper"
    
    return "unknown"


def classify_all_sheets(wb):
    """
    Classify all sheets in a workbook and return a dict mapping sheet name to type.
    Uses content-based analysis as primary, name-based as fallback.
    """
    # First pass: gather basic info
    all_sheets_info = []
    for name in wb.sheetnames:
        ws = wb[name]
        all_sheets_info.append({
            'name': name,
            'max_row': ws.max_row or 0,
            'max_col': ws.max_column or 0,
        })
    
    # Second pass: classify each sheet using content analysis
    classifications = {}
    for sheet_info in all_sheets_info:
        ws = wb[sheet_info['name']]
        classifications[sheet_info['name']] = classify_sheet(
            sheet_info['name'],
            ws,
            all_sheets_info,
        )
    
    # Post-processing: ensure we have at least one summary and one raw data
    has_summary = any(t == "summary_report" for t in classifications.values())
    has_raw = any(t == "raw_data" for t in classifications.values())
    
    if not has_summary:
        # Promote the first 'unknown' sheet with moderate size
        for name, stype in classifications.items():
            if stype == "unknown":
                ws = wb[name]
                if (ws.max_row or 0) > 10:
                    classifications[name] = "summary_report"
                    break
    
    if not has_raw:
        # The sheet with the most rows that isn't a summary is likely raw data
        non_summary = [
            s for s in all_sheets_info 
            if classifications.get(s['name']) != "summary_report"
        ]
        if non_summary:
            largest = max(non_summary, key=lambda s: s['max_row'])
            if largest['max_row'] > 50:
                classifications[largest['name']] = "raw_data"
    
    return classifications
