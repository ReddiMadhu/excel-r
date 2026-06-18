import zipfile
import xml.etree.ElementTree as ET
import os

def parse_pivot_metadata(file_path):
    """
    Extract pivot table metadata from the Excel file ZIP archive.
    Returns a list of dicts containing pivot table definitions, or [] if none are found.
    """
    if not zipfile.is_zipfile(file_path):
        return []
        
    namespaces = {
        'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    }
    
    pivot_tables = []
    
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            namelist = z.namelist()
            
            # Find all pivotTable XMLs
            pt_files = [x for x in namelist if 'xl/pivotTables/pivotTable' in x and x.endswith('.xml')]
            if not pt_files:
                return []
                
            # Find all cacheDefinition XMLs
            cache_files = [x for x in namelist if 'xl/pivotCache/pivotCacheDefinition' in x and x.endswith('.xml')]
            
            # Load cache definitions first
            caches = {}
            for cf_path in cache_files:
                # E.g. 'xl/pivotCache/pivotCacheDefinition1.xml' -> cacheId or we parse the index
                # Cache files map field index to column name
                try:
                    with z.open(cf_path) as f:
                        tree = ET.parse(f)
                        root = tree.getroot()
                        
                        # Cache source sheet/range
                        source_sheet = ""
                        source_range = ""
                        cache_source = root.find('ns:cacheSource', namespaces)
                        if cache_source is not None:
                            ws_source = cache_source.find('ns:worksheetSource', namespaces)
                            if ws_source is not None:
                                source_sheet = ws_source.get('sheet', '')
                                source_range = ws_source.get('ref', '')
                                
                        # Fields in cache
                        fields = []
                        cache_fields_el = root.find('ns:cacheFields', namespaces)
                        if cache_fields_el is not None:
                            for cf in cache_fields_el.findall('ns:cacheField', namespaces):
                                name = cf.get('name')
                                fields.append(name)
                                
                        # Find the relationship or ID
                        # E.g. Definition1 maps to cache index 1, but we can match definition name numbers
                        # to pivotTable cacheId.
                        # We can extract the file basename number: pivotCacheDefinition1.xml -> index 1
                        base_name = os.path.basename(cf_path)
                        num_part = ''.join(filter(str.isdigit, base_name))
                        cache_idx = int(num_part) if num_part else len(caches) + 1
                        caches[cache_idx] = {
                            "sheet": source_sheet,
                            "range": source_range,
                            "fields": fields
                        }
                except Exception as e:
                    print(f"Warning parsing cache definition {cf_path}: {e}")
                    
            # Parse pivotTableDefinitions
            for pt_path in pt_files:
                try:
                    with z.open(pt_path) as f:
                        tree = ET.parse(f)
                        root = tree.getroot()
                        
                        name = root.get('name', 'PivotTable')
                        cache_id = int(root.get('cacheId', 0))
                        
                        # Match to cache
                        # In openxml, cacheId in pivotTable refers to the cacheId in workbook.xml.
                        # Typically it aligns with the number in pivotCacheDefinitionX.xml
                        # Let's fallback to cache_id or index-based match if needed.
                        cache_info = caches.get(cache_id)
                        if not cache_info:
                            # Try matching by index of the pivotTable number
                            base_name = os.path.basename(pt_path)
                            num_part = ''.join(filter(str.isdigit, base_name))
                            pt_idx = int(num_part) if num_part else 1
                            cache_info = caches.get(pt_idx)
                            if not cache_info and caches:
                                # Fallback to first cache
                                cache_info = list(caches.values())[0]
                                
                        fields_list = cache_info["fields"] if cache_info else []
                        data_source_sheet = cache_info["sheet"] if cache_info else "Unknown"
                        
                        location_el = root.find('ns:location', namespaces)
                        ref_range = location_el.get('ref', '') if location_el is not None else ''
                        
                        # Filters (pageFields)
                        filters = []
                        page_fields_el = root.find('ns:pageFields', namespaces)
                        if page_fields_el is not None:
                            for pf in page_fields_el.findall('ns:pageField', namespaces):
                                fld_idx = int(pf.get('fld', -1))
                                if 0 <= fld_idx < len(fields_list):
                                    filters.append(fields_list[fld_idx])
                                    
                        # Row fields
                        row_fields = []
                        row_fields_el = root.find('ns:rowFields', namespaces)
                        if row_fields_el is not None:
                            for rf in row_fields_el.findall('ns:field', namespaces):
                                fld_idx = int(rf.get('x', -1))
                                if 0 <= fld_idx < len(fields_list):
                                    row_fields.append(fields_list[fld_idx])
                                    
                        # Column fields
                        col_fields = []
                        col_fields_el = root.find('ns:colFields', namespaces)
                        if col_fields_el is not None:
                            for cf in col_fields_el.findall('ns:field', namespaces):
                                fld_idx = int(cf.get('x', -1))
                                if 0 <= fld_idx < len(fields_list):
                                    col_fields.append(fields_list[fld_idx])
                                    
                        # Data value fields
                        data_fields = []
                        data_fields_el = root.find('ns:dataFields', namespaces)
                        if data_fields_el is not None:
                            for df in data_fields_el.findall('ns:dataField', namespaces):
                                fld_name = df.get('name', '')
                                fld_idx = int(df.get('fld', -1))
                                subtotal = df.get('subtotal', 'sum').upper()
                                source_col = fields_list[fld_idx] if 0 <= fld_idx < len(fields_list) else ""
                                data_fields.append({
                                    "name": fld_name,
                                    "source_column": source_col,
                                    "aggregation": subtotal
                                })
                                
                        pivot_tables.append({
                            "pivot_table_name": name,
                            "table_range": ref_range,
                            "raw_data_sheet_name": data_source_sheet,
                            "row_fields": row_fields,
                            "column_fields": col_fields,
                            "filter_fields": filters,
                            "value_fields": data_fields
                        })
                except Exception as e:
                    print(f"Warning parsing pivot table {pt_path}: {e}")
                    
    except Exception as e:
        print(f"General warning parsing zip for pivots: {e}")
        
    return pivot_tables

def reconstruct_pivot_formulas(pivot_info, summary_ws_val):
    """
    For a detected pivot table, extract filter values from the sheet
    and generate human-readable formula patterns for each value column.
    
    Returns a dict mapping the pivot value column name to pivot details.
    """
    filters_dict = {}
    
    # Try to extract current filter values from above the pivot range.
    # Pivot range starts at ref_range, e.g., 'A6:I67'.
    # Filters are usually listed in rows 1 to 4 in columns A and B.
    pt_range = pivot_info.get("table_range", "")
    start_row = 1
    if pt_range:
        try:
            start_row = int(''.join(filter(str.isdigit, pt_range.split(':')[0])))
        except:
            start_row = 6
            
    # Look for filters in rows above the pivot table (from row 1 to start_row - 2)
    filter_names = pivot_info.get("filter_fields", [])
    for r in range(1, start_row - 1):
        cell_a = summary_ws_val.cell(row=r, column=1).value
        cell_b = summary_ws_val.cell(row=r, column=2).value
        if cell_a is not None and str(cell_a).strip() in filter_names:
            filters_dict[str(cell_a).strip()] = str(cell_b).strip() if cell_b is not None else "(All)"
            
    # Fill remaining filters as (All) if not found in cells
    for fld in filter_names:
        if fld not in filters_dict:
            filters_dict[fld] = "(All)"
            
    value_formulas = {}
    row_fields = pivot_info.get("row_fields", [])
    data_source_sheet = pivot_info.get("raw_data_sheet_name", "Synthetic_Data")
    
    for vf in pivot_info.get("value_fields", []):
        col_name = vf["name"]
        agg = vf["aggregation"]
        src_col = vf["source_column"]
        
        # Build formula pattern
        group_by_str = ", ".join(row_fields)
        filter_items = [f"{k} = {v}" for k, v in filters_dict.items()]
        filter_str = ", ".join(filter_items)
        
        formula_pattern = f"{agg}({data_source_sheet}[{src_col}])"
        if group_by_str:
            formula_pattern += f" GROUP BY {group_by_str}"
            
        definition = f"Sum of {src_col} from {data_source_sheet} aggregated as {agg} grouped by {group_by_str}"
        
        value_formulas[col_name] = {
            "aggregation": agg,
            "source_column": src_col,
            "data_source_sheet": data_source_sheet,
            "data_source_columns": [src_col],
            "group_by_fields": row_fields,
            "pivot_filters": filters_dict,
            "formula_pattern": formula_pattern,
            "definition": definition
        }
        
    return value_formulas
