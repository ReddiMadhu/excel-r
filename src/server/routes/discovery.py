"""
Discovery Routes — GET /api/discovery/business-catalog

Read-only LOB and business-group catalog grouped by workbook metadata
from discovery extraction and intelligence enrichment.
"""
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from src.server.models.database import get_database
from src.server.models.schemas import (
    BusinessCatalogResponse,
    CatalogSheetSummary,
    CatalogWorkbookEntry,
)
from src.utils.business_metadata import (
    infer_business_metadata,
    pick_primary_business_group,
    pick_primary_lob,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/discovery", tags=["Discovery"])


def _parse_json_field(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def _as_string_list(val: Any) -> List[str]:
    parsed = _parse_json_field(val)
    if not parsed:
        return []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, str):
        return [s.strip() for s in parsed.split(",") if s.strip()]
    return [str(parsed).strip()]


def _parse_user_groups(val: Any) -> List[str]:
    return _as_string_list(val)


def _parse_filters(val: Any) -> List[Dict[str, str]]:
    parsed = _parse_json_field(val)
    if not isinstance(parsed, list):
        return []
    filters = []
    for item in parsed:
        if isinstance(item, dict):
            filters.append({
                "filter_name": str(item.get("filter_name", "")),
                "filter_value": str(item.get("filter_value", "")),
            })
    return filters


def build_business_catalog() -> BusinessCatalogResponse:
    db = get_database()

    workbook_rows = db.query("""
        SELECT id, name, purpose, sheet_count, summary_sheet_name, raw_data_sheet_name,
               primary_inputs, intermediate_calculations, final_outputs,
               has_vba_macros, external_links, extraction_quality_score,
               comparison_mode, vulnerability_rating, uploaded_at
        FROM workbooks
        ORDER BY name
    """)

    dashboard_rows = db.query("""
        SELECT d.id, d.workbook_id, d.name, d.sheet_type, d.line_of_business,
               d.domain_classification, d.user_groups, d.ai_summary,
               d.formula_count, d.table_count, d.pivot_table_count, d.filters,
               d.is_real_ai
        FROM dashboards d
        ORDER BY d.workbook_id, d.id
    """)

    dashboards_by_wb: Dict[int, list] = defaultdict(list)
    for dash in dashboard_rows:
        dashboards_by_wb[dash["workbook_id"]].append(dash)

    by_lob: Dict[str, List[int]] = defaultdict(list)
    by_user_group: Dict[str, List[int]] = defaultdict(list)
    by_domain: Dict[str, List[int]] = defaultdict(list)
    unclassified: List[int] = []
    catalog_workbooks: List[CatalogWorkbookEntry] = []

    for wb in workbook_rows:
        sheets = dashboards_by_wb.get(wb["id"], [])
        summary_sheets = [s for s in sheets if s.get("sheet_type") == "summary_report"]
        classification_sheets = summary_sheets or sheets

        lob = None
        domain = None
        user_groups: set = set()
        metadata_enriched = False

        for sheet in classification_sheets:
            if sheet.get("line_of_business") and not lob:
                lob = sheet["line_of_business"]
            if sheet.get("domain_classification") and not domain:
                domain = sheet["domain_classification"]
            user_groups.update(_parse_user_groups(sheet.get("user_groups")))
            if sheet.get("is_real_ai"):
                metadata_enriched = True

        suggested = False
        if not lob or not domain or not user_groups:
            inf_lob, inf_domain, inf_groups = infer_business_metadata(
                wb.get("purpose"),
                wb.get("name"),
            )
            if not lob and inf_lob:
                lob = inf_lob
                suggested = True
            if not domain and inf_domain:
                domain = inf_domain
                suggested = True
            if not user_groups and inf_groups:
                user_groups = set(inf_groups)
                suggested = True

        primary_lob = pick_primary_lob(lob, wb.get("purpose"), wb.get("name"))
        primary_business = pick_primary_business_group(
            list(user_groups),
            wb.get("purpose"),
            wb.get("name"),
        )
        if primary_lob and not metadata_enriched:
            suggested = True

        external_links = _as_string_list(wb.get("external_links"))
        sheet_models = []
        for sheet in sheets:
            filters = _parse_filters(sheet.get("filters"))
            sheet_models.append(CatalogSheetSummary(
                id=sheet["id"],
                name=sheet["name"],
                sheet_type=sheet.get("sheet_type"),
                line_of_business=sheet.get("line_of_business"),
                domain_classification=sheet.get("domain_classification"),
                user_groups=_parse_user_groups(sheet.get("user_groups")),
                ai_summary=sheet.get("ai_summary"),
                formula_count=sheet.get("formula_count"),
                table_count=sheet.get("table_count"),
                pivot_table_count=sheet.get("pivot_table_count"),
                filter_count=len(filters),
                filters=filters or None,
            ))

        entry = CatalogWorkbookEntry(
            id=wb["id"],
            name=wb["name"],
            purpose=wb.get("purpose"),
            line_of_business=primary_lob,
            primary_business_group=primary_business,
            domain_classification=domain,
            user_groups=[primary_business] if primary_business else [],
            metadata_suggested=suggested and not metadata_enriched,
            summary_sheet_name=wb.get("summary_sheet_name"),
            raw_data_sheet_name=wb.get("raw_data_sheet_name"),
            primary_inputs=_as_string_list(wb.get("primary_inputs")),
            intermediate_calculations=_as_string_list(wb.get("intermediate_calculations")),
            final_outputs=_as_string_list(wb.get("final_outputs")),
            has_vba_macros=bool(wb.get("has_vba_macros", 0)),
            external_link_count=len(external_links),
            extraction_quality_score=wb.get("extraction_quality_score"),
            comparison_mode=wb.get("comparison_mode"),
            vulnerability_rating=wb.get("vulnerability_rating"),
            uploaded_at=wb.get("uploaded_at"),
            sheet_count=wb.get("sheet_count"),
            metadata_enriched=metadata_enriched,
            sheets=sheet_models,
        )
        catalog_workbooks.append(entry)

        if primary_lob:
            by_lob[primary_lob].append(wb["id"])
        else:
            unclassified.append(wb["id"])

        if domain:
            by_domain[domain].append(wb["id"])

        if primary_business:
            by_user_group[primary_business].append(wb["id"])

    return BusinessCatalogResponse(
        workbooks=catalog_workbooks,
        by_lob=dict(sorted(by_lob.items())),
        by_user_group=dict(sorted(by_user_group.items())),
        by_domain=dict(sorted(by_domain.items())),
        unclassified_workbook_ids=unclassified,
        lobs=sorted(by_lob.keys()),
        user_groups=sorted(by_user_group.keys()),
        domains=sorted(by_domain.keys()),
    )


@router.get("/business-catalog", response_model=BusinessCatalogResponse)
async def get_business_catalog():
    """LOB and business-group catalog with workbook-level discovery metadata."""
    return build_business_catalog()
