"""
DB Loader — Transform extracted JSON output into SQLite table rows.

Reads the complete JSON dict produced by json_builder.build_workbook_json()
and inserts rows into all relevant tables: workbooks, dashboards, worksheets,
columns, calculated_fields, datasources, tables, table_joins.
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from src.server.models.database import Database
from src.utils.validation import compute_comparison_readiness
from src.utils.timing_log import PipelineTimer, log_step
from src.utils.business_metadata import (
    infer_business_metadata,
    merge_business_metadata,
    pick_primary_business_group,
    pick_primary_lob,
)

logger = logging.getLogger(__name__)


def _safe_json(value: Any) -> Optional[str]:
    """Serialize a value to JSON string if it's a dict/list, otherwise return as-is."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def load_workbook_json(
    output_json: Dict[str, Any],
    scan_id: int,
    db: Database,
    json_output_path: Optional[str] = None
) -> int:
    """
    Load a complete workbook JSON dict into the database.

    Returns the workbook_id of the inserted workbook row.
    """
    file_name = output_json.get("file_name", "")
    base_name = os.path.splitext(file_name)[0]
    timer = PipelineTimer("db_load", file_name=file_name or base_name)

    with timer.step("prepare_metadata"):
        metadata = output_json.get("workbook_metadata", {})
        process_flow = output_json.get("process_flow", {})
        sheets_data = output_json.get("sheets", [])
        readiness = output_json.get("comparison_readiness") or compute_comparison_readiness(output_json)

        wb_lob, wb_domain, wb_groups = merge_business_metadata(
            output_json.get("line_of_business", ""),
            output_json.get("domain_classification", ""),
            output_json.get("user_groups") or [],
            infer_business_metadata(
                output_json.get("purpose") or output_json.get("workbook_purpose", ""),
                base_name,
            ),
        )
        wb_lob = pick_primary_lob(wb_lob, output_json.get("purpose"), base_name) or ""
        primary_business = pick_primary_business_group(wb_groups, output_json.get("purpose"), base_name)
        wb_groups = [primary_business] if primary_business else []

        # Identify raw / summary sheet names
        raw_data_sheet_name = ""
        summary_sheet_name = ""
        sheet_names_list = []
        for sheet in sheets_data:
            s_name = sheet.get("sheet_name", "")
            sheet_names_list.append(s_name)
            s_type = sheet.get("sheet_type", "")
            if s_type == "raw_data":
                raw_data_sheet_name = s_name
            elif s_type == "summary_report":
                summary_sheet_name = s_name

        workbook_row = {
            "scan_id": scan_id,
            "name": base_name,
            "source_file": file_name,
            "file_hash_md5": output_json.get("file_hash_md5", ""),
            "schema_version": output_json.get("schema_version", ""),
            "generated_at": output_json.get("generated_at", ""),
            "purpose": output_json.get("purpose") or output_json.get("workbook_purpose", ""),
            "sheet_count": len(sheets_data),
            "sheet_names": sheet_names_list,
            "has_vba_macros": metadata.get("has_vba_macros", False),
            "vba_macro_streams": metadata.get("vba_macro_streams", []),
            "external_links": metadata.get("external_links", []),
            "named_ranges": metadata.get("named_ranges", []),
            "raw_data_sheet_name": raw_data_sheet_name,
            "summary_sheet_name": summary_sheet_name,
            "primary_inputs": process_flow.get("primary_inputs", []),
            "intermediate_calculations": process_flow.get("intermediate_calculations", []),
            "final_outputs": process_flow.get("final_outputs", []),
            "vulnerability_rating": process_flow.get("vulnerability_rating", ""),
            "extraction_quality_score": readiness.get("extraction_quality_score", 0.0),
            "comparison_mode": readiness.get("comparison_mode", "insufficient"),
            "json_output_path": json_output_path or "",
        }

    with timer.step("insert_workbook_row"):
        workbook_id = db.insert("workbooks", workbook_row)
    logger.info("Inserted workbook '%s' (id=%d)", base_name, workbook_id)

    # ── 2. Process each sheet ────────────────────────────────
    t_sheets = time.perf_counter()
    for sheet in sheets_data:
        s_name = sheet.get("sheet_name", "")
        s_type = sheet.get("sheet_type", "")
        tables_data = sheet.get("tables", [])

        # Count pivot tables
        pivot_count = sum(1 for t in tables_data if t.get("table_type") == "pivot_table")

        # Collect column headers for this sheet
        all_col_names = []
        for t in tables_data:
            for col in t.get("columns", []):
                cn = col.get("column_name", "")
                if cn and cn not in all_col_names:
                    all_col_names.append(cn)

        dashboard_row = {
            "workbook_id": workbook_id,
            "name": s_name,
            "sheet_type": s_type,
            "sheet_range": sheet.get("sheet_range", ""),
            "row_count": sheet.get("row_count", 0),
            "column_count": sheet.get("column_count", 0),
            "formula_count": sheet.get("formula_count", 0),
            "non_empty_cells": sheet.get("non_empty_cells", 0),
            "table_count": len(tables_data),
            "pivot_table_count": pivot_count,
            "hidden_row_count": sheet.get("sheet_metadata", {}).get("hidden_row_count", 0)
                if isinstance(sheet.get("sheet_metadata"), dict) else 0,
            "hidden_column_count": sheet.get("sheet_metadata", {}).get("hidden_column_count", 0)
                if isinstance(sheet.get("sheet_metadata"), dict) else 0,
            "print_area": sheet.get("sheet_metadata", {}).get("print_area", "")
                if isinstance(sheet.get("sheet_metadata"), dict) else "",
            "columns_list": all_col_names,
            "filters": sheet.get("filters", []),
            "raw_metadata": {
                **(sheet.get("sheet_metadata") or {}),
                "pivot_tables": sheet.get("pivot_tables", []),
            },
        }

        if s_type == "summary_report" and (wb_lob or wb_domain or wb_groups):
            if wb_lob:
                dashboard_row["line_of_business"] = wb_lob
            if wb_domain:
                dashboard_row["domain_classification"] = wb_domain
            if wb_groups:
                dashboard_row["user_groups"] = _safe_json(wb_groups)

        dashboard_id = db.insert("dashboards", dashboard_row)

        # ── 2a. Raw data sheets → datasources table ─────────
        if s_type == "raw_data":
            raw_columns_list = sheet.get("raw_columns", [])
            # Also try to get from column_maps if present
            if not raw_columns_list and tables_data:
                for t in tables_data:
                    for col in t.get("columns", []):
                        cn = col.get("column_name", "")
                        if cn:
                            raw_columns_list.append(cn)

            ds_row = {
                "workbook_id": workbook_id,
                "name": s_name,
                "caption": s_name,
                "column_headers": raw_columns_list,
                "row_count": sheet.get("row_count", 0),
                "column_count": sheet.get("column_count", 0),
            }
            datasource_id = db.insert("datasources", ds_row)

            # Insert into tables table
            db.insert("tables", {
                "datasource_id": datasource_id,
                "name": s_name,
                "business_name": s_name,
                "columns": raw_columns_list,
            })

        # ── 2b. Process tables within the sheet ──────────────
        for table in tables_data:
            t_name = table.get("table_name", "")
            t_type = table.get("table_type", "")
            columns_data = table.get("columns", [])
            row_classification = table.get("row_classification", {})

            data_rows = row_classification.get("data_rows", [])
            header_rows = row_classification.get("header_rows", [])
            total_rows = row_classification.get("total_rows", [])
            check_rows = row_classification.get("check_rows", [])

            # Build business context
            business_def = table.get("business_definition", {})
            if isinstance(business_def, str):
                business_def = {"business_purpose": business_def}

            worksheet_row = {
                "workbook_id": workbook_id,
                "dashboard_id": dashboard_id,
                "name": t_name,
                "table_type": t_type,
                "table_range": table.get("table_range", ""),
                "section_title": table.get("section_title", ""),
                "header_row": header_rows[0] if header_rows else None,
                "data_start_row": data_rows[0] if data_rows else None,
                "data_end_row": data_rows[-1] if data_rows else None,
                "row_count": table.get("row_count", len(data_rows)),
                "column_count": table.get("column_count", len(columns_data)),
                "input_cell_count": table.get("input_cell_count", 0),
                "total_rows": total_rows,
                "check_rows": check_rows,
                "row_header_columns": table.get("row_header_columns", []),
                "column_header_rows": header_rows,
                "business_purpose": business_def.get("business_purpose", ""),
                "measures": business_def.get("measures", []),
                "dimensions": business_def.get("dimensions", []),
                "inter_table_relationships": table.get("inter_table_relationships", []),
                "summary_rows": table.get("summary_rows", []),
                "pivot_configuration": table.get("pivot_tables", table.get("pivot_meta", None)),
                "mark_type": "pivot" if t_type == "pivot_table" else "table",
            }

            worksheet_id = db.insert("worksheets", worksheet_row)

            # ── 2c. Process columns within the table ─────────
            for col in columns_data:
                col_name = col.get("column_name", "")
                col_type = col.get("type", "raw")
                lineage = col.get("formula_lineage", None)
                resolved_by = col.get("resolved_by", "")
                if lineage and isinstance(lineage, dict) and lineage.get("resolved_by"):
                    resolved_by = lineage.get("resolved_by")

                column_row = {
                    "worksheet_id": worksheet_id,
                    "dashboard_id": dashboard_id,
                    "workbook_id": workbook_id,
                    "column_name": col_name,
                    "table_name": t_name,
                    "data_type": col.get("data_type", ""),
                    "column_type": col_type,
                    "formula": col.get("formula", ""),
                    "formula_count": col.get("formula_count", 0),
                    "formula_pattern": col.get("formula_pattern", ""),
                    "number_format": col.get("number_format", ""),
                    "number_format_type": col.get("number_format_type", ""),
                    "sample_values": col.get("sample_values", []),
                    "nesting_depth": col.get("nesting_depth", 0),
                    "function_chain": col.get("function_chain", []),
                    "definition": col.get("definition", ""),
                    "formula_lineage": lineage,
                    "resolved_by": resolved_by,
                }

                db.insert("columns", column_row)

                # ── 2d. Insert into calculated_fields if formula column ──
                if col_type in ("formula_based", "pivot_value", "total", "check"):
                    fingerprint = ""
                    computation_type = ""
                    ultimate_raw_sources = []

                    if lineage and isinstance(lineage, dict):
                        fingerprint = lineage.get("fingerprint", "")
                        computation_type = lineage.get("computation_type", "")
                        ultimate_raw_sources = lineage.get("ultimate_raw_sources", [])

                    calc_field_row = {
                        "dashboard_id": dashboard_id,
                        "workbook_id": workbook_id,
                        "name": col_name,
                        "formula": col.get("formula", ""),
                        "datatype": col.get("data_type", ""),
                        "formula_pattern": col.get("formula_pattern", ""),
                        "definition": col.get("definition", ""),
                        "column_type": col_type,
                        "nesting_depth": col.get("nesting_depth", 0),
                        "function_chain": col.get("function_chain", []),
                        "computation_type": computation_type,
                        "ultimate_raw_sources": ultimate_raw_sources,
                        "fingerprint": fingerprint,
                        "table_name": t_name,
                    }

                    db.insert("calculated_fields", calc_field_row)

            # ── 2e. Build table_joins from formula references ──
            for col in columns_data:
                ds_sheet = col.get("data_source_sheet", "")
                ds_cols = col.get("data_source_columns", [])
                if ds_sheet and ds_sheet != s_name and ds_cols:
                    for ds_col in ds_cols:
                        # Find the datasource id
                        ds = db.query_one(
                            "SELECT id FROM datasources WHERE workbook_id = ? AND name = ?",
                            (workbook_id, ds_sheet)
                        )
                        db.insert("table_joins", {
                            "datasource_id": ds["id"] if ds else None,
                            "workbook_id": workbook_id,
                            "left_table": t_name,
                            "right_table": ds_sheet,
                            "join_type": "formula_ref",
                            "left_column": col.get("column_name", ""),
                            "right_column": ds_col,
                        })

    log_step(
        "db_load",
        "insert_sheets_tables_columns",
        time.perf_counter() - t_sheets,
        file_name=file_name or base_name,
        sheet_count=len(sheets_data),
    )

    logger.info(
        "Loaded workbook '%s' into DB: %d sheets, workbook_id=%d",
        base_name, len(sheets_data), workbook_id
    )
    timer.finish("DB_LOAD_TOTAL")
    return workbook_id
