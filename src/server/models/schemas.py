"""
Pydantic schemas for FastAPI request/response models.

Mirrors the BI Compass frontend contract with Excel-specific adaptations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Scan Models ──────────────────────────────────────────────

class ScanCreateResponse(BaseModel):
    scan_id: str
    status: str = "pending"
    total_files: int = 0
    message: str = "Scan created. Extraction will begin shortly."


class ScanProgress(BaseModel):
    scan_id: str
    status: str  # pending|extracting|completed|failed
    phase: str = "discovery"  # discovery (extraction only)
    total_files: int = 0
    processed_files: int = 0
    current_file: Optional[str] = None
    progress_percent: float = 0.0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


# ── Agent Models ─────────────────────────────────────────────

class AgentStatus(BaseModel):
    status: str  # idle|pending|running|completed|stale|failed|ready|empty|extracting
    label: str
    description: str
    last_run_at: Optional[str] = None
    workbook_count_at_run: Optional[int] = None
    error: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    workbook_count: Optional[int] = None
    kpi_cluster_count: Optional[int] = None
    recommendation_count: Optional[int] = None
    risk_count: Optional[int] = None


class AgentsStatusResponse(BaseModel):
    discovery: AgentStatus
    intelligence: AgentStatus
    rationalization: AgentStatus


class AgentRunResponse(BaseModel):
    agent: str
    status: str
    message: str


# ── Workbook Models ──────────────────────────────────────────

class WorkbookSummary(BaseModel):
    id: int
    name: str
    source_file: str
    file_hash_md5: Optional[str] = None
    schema_version: Optional[str] = None
    purpose: Optional[str] = None
    sheet_count: Optional[int] = None
    has_vba_macros: bool = False
    vulnerability_rating: Optional[str] = None
    extraction_complexity: Optional[float] = None
    structural_risk: Optional[float] = None
    computation_depth: Optional[float] = None
    extraction_quality_score: Optional[float] = None
    comparison_mode: Optional[str] = None
    uploaded_at: Optional[str] = None
    # Counts for quick summary
    dashboard_count: Optional[int] = None
    calculated_field_count: Optional[int] = None
    datasource_count: Optional[int] = None


class WorkbookDetail(WorkbookSummary):
    sheet_names: Optional[List[str]] = None
    external_links: Optional[List[str]] = None
    named_ranges: Optional[List[Dict[str, Any]]] = None
    raw_data_sheet_name: Optional[str] = None
    summary_sheet_name: Optional[str] = None
    primary_inputs: Optional[List[str]] = None
    intermediate_calculations: Optional[List[str]] = None
    final_outputs: Optional[List[str]] = None
    vba_macro_streams: Optional[List[str]] = None
    json_output_path: Optional[str] = None
    dashboards: List[DashboardSummary] = Field(default_factory=list)
    datasources: List[DatasourceSummary] = Field(default_factory=list)


# ── Dashboard (Sheet) Models ────────────────────────────────

class DashboardSummary(BaseModel):
    id: int
    workbook_id: int
    workbook_name: Optional[str] = None
    name: str
    sheet_type: Optional[str] = None
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    formula_count: Optional[int] = None
    table_count: Optional[int] = None
    pivot_table_count: Optional[int] = None
    hidden_row_count: int = 0
    hidden_column_count: int = 0
    ai_summary: Optional[str] = None
    domain_classification: Optional[str] = None
    line_of_business: Optional[str] = None
    complexity_score: Optional[float] = None
    is_real_ai: bool = False


class WorksheetSummary(BaseModel):
    id: int
    name: str
    table_type: Optional[str] = None
    table_range: Optional[str] = None
    section_title: Optional[str] = None
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    business_purpose: Optional[str] = None
    measures: Optional[List[str]] = None
    dimensions: Optional[List[str]] = None
    mark_type: str = "table"


class ColumnSummary(BaseModel):
    id: int
    column_name: str
    table_name: Optional[str] = None
    data_type: Optional[str] = None
    column_type: Optional[str] = None
    formula: Optional[str] = None
    formula_pattern: Optional[str] = None
    nesting_depth: int = 0
    definition: Optional[str] = None
    formula_lineage: Optional[Dict[str, Any]] = None


class DashboardDetail(DashboardSummary):
    sheet_range: Optional[str] = None
    non_empty_cells: Optional[int] = None
    print_area: Optional[str] = None
    columns_list: Optional[List[str]] = None
    filters: Optional[List[Dict[str, str]]] = None
    raw_metadata: Optional[Dict[str, Any]] = None
    worksheets: List[WorksheetSummary] = Field(default_factory=list)
    columns: List[ColumnSummary] = Field(default_factory=list)


# ── Calculated Field Models ──────────────────────────────────

class CalculatedFieldSummary(BaseModel):
    id: int
    workbook_id: int
    workbook_name: Optional[str] = None
    dashboard_id: int
    dashboard_name: Optional[str] = None
    name: str
    formula: Optional[str] = None
    datatype: Optional[str] = None
    formula_pattern: Optional[str] = None
    definition: Optional[str] = None
    column_type: Optional[str] = None
    nesting_depth: int = 0
    computation_type: Optional[str] = None
    ultimate_raw_sources: Optional[List[str]] = None
    fingerprint: Optional[str] = None
    table_name: Optional[str] = None


# ── Datasource Models ────────────────────────────────────────

class DatasourceSummary(BaseModel):
    id: int
    workbook_id: int
    workbook_name: Optional[str] = None
    name: str
    caption: Optional[str] = None
    column_headers: Optional[List[str]] = None
    row_count: Optional[int] = None
    column_count: Optional[int] = None


# ── KPI Cluster Models ───────────────────────────────────────

class KpiCluster(BaseModel):
    canonical_name: str
    original_names: List[str] = Field(default_factory=list)
    workbook_count: int = 0
    cluster_method: Optional[str] = None


# ── Governance Models ────────────────────────────────────────

class GovernanceRecommendation(BaseModel):
    id: int
    workbook_id: int
    workbook_name: Optional[str] = None
    action: str  # keep|decommission|merge|remediate|review
    merge_with_name: Optional[str] = None
    merge_with_id: Optional[int] = None
    kpi_overlap_score: Optional[float] = None
    datasource_overlap_score: Optional[float] = None
    uniqueness_score: Optional[float] = None
    common_kpis: Optional[List[str]] = None
    common_datasources: Optional[List[str]] = None
    matching_fingerprints: Optional[List[str]] = None
    reasons: Optional[List[str]] = None
    llm_justification: Optional[str] = None
    llm_override: bool = False
    scores: Optional[Dict[str, Any]] = None
    calculated_at: Optional[str] = None


class GovernanceRisk(BaseModel):
    id: int
    workbook_id: int
    workbook_name: Optional[str] = None
    dashboard_id: Optional[int] = None
    dashboard_name: Optional[str] = None
    risk_category: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    affected_element: Optional[str] = None
    detected_at: Optional[str] = None


class PairwiseOverlap(BaseModel):
    workbook_id_a: int
    workbook_id_b: int
    workbook_name_a: str
    workbook_name_b: str
    kpi_overlap: float
    ds_overlap: float
    structural_overlap: float = 0.0
    fingerprint_ratio: float = 0.0
    combined_score: float = 0.0
    overlap_class: str = "distinct"
    common_kpis: List[str] = Field(default_factory=list)


class PairwiseMatrixResponse(BaseModel):
    workbooks: List[Dict[str, Any]]
    pairs: List[PairwiseOverlap]


# Fix forward references
WorkbookDetail.model_rebuild()
