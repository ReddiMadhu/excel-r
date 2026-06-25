"""
LLM Prompt Templates for the 3-phase rationalization pipeline.

Phase 1: KPI Canonicalization
Phase 2: Ambiguous-pair similarity assessment
Phase 3: Per-action-group recommendation justification + AI fields
"""


KPI_CANONICALIZATION_PROMPT = """You are an expert actuarial and financial business analyst.

The groups below were formed because the Excel columns share identical computation
content — not because their names look similar. Each group matched on one or more of:
  - fingerprint: identical formula structure AND identical raw data sources
  - source_type: same upstream raw data tables AND same aggregation type (SUMIFS, COUNTIFS, etc.)
  - pattern: identical formula pattern string
  - definition: identical column definition text

Your job is to confirm or split these content-based groups into final canonical KPI clusters.

Pre-clusters (each group already shares computation content):
{pre_clusters}

Rules:
1. canonical_name MUST be one of the exact member names from the group — choose the most complete and meaningful name from the list. Do NOT invent or rewrite names.
2. If two groups share fingerprints or raw sources AND represent the same business concept, merge them into one cluster and pick the best member name as canonical.
3. If members within a group share identical computation but represent genuinely different business concepts (e.g. two metrics that happen to use the same source table for unrelated purposes), split them into separate clusters.
4. Never merge groups that have different fingerprints AND different raw sources — identical computation is required for merging.
5. Maintain every original member name exactly as provided — do not modify, abbreviate, or rename any member.

Return a JSON array:
[
  {{
    "canonical_name": "one of the exact member names from this cluster",
    "members": ["original_name_1", "original_name_2"]
  }}
]

Return ONLY the JSON array. No markdown, no explanation."""


AMBIGUOUS_PAIR_PROMPT = """You are a BI governance analyst assessing Excel workbook redundancy.

These two Excel workbooks have moderate overlap. Assess whether
they serve the same business purpose or are genuinely different:

Workbook A: "{name_a}"
  Purpose: {purpose_a}
  KPIs (canonical): {kpis_a}
  Raw Data Sources: {sources_a}
  Overlap Scores: KPI={kpi_score:.2f}, DataSource={ds_score:.2f}

Workbook B: "{name_b}"
  Purpose: {purpose_b}
  KPIs (canonical): {kpis_b}
  Raw Data Sources: {sources_b}

Are these doing the same work? Consider:
- Do they aggregate the same metrics from the same data?
- Do they serve different business units or different reporting periods?
- Is one a subset of the other?

Return JSON:
{{
  "same_work": true or false,
  "confidence": 0.0 to 1.0,
  "reasoning": "1-2 sentence explanation"
}}

Return ONLY the JSON object. No markdown."""


RECOMMENDATION_GROUP_PROMPT = """You are a BI governance analyst providing rationalization recommendations for Excel workbooks.

For each Excel workbook below, write a 1-2 sentence business justification for the proposed action.
Also provide semantic metadata fields.

Action Group: {action_group}

Workbooks:
{workbooks_context}

For each workbook, return a JSON object with:
{{
  "workbook_name": "exact name as provided",
  "final_action": "{action_group}",
  "justification": "1-2 sentence business justification for this action",
  "ai_summary": "2-3 sentence summary of what this workbook does",
  "domain_classification": "one of: reserves, compensation, claims, underwriting, investments, operations, other",
  "line_of_business": "high-level line of business using simple labels (e.g., Insurance, Group Benefits, Annuities)",
  "user_groups": ["list of business user groups or teams that use this workbook, e.g. Actuarial, Finance, Underwriting"],
  "override_reason": null
}}

If you believe the proposed action is WRONG based on the workbook's purpose, you may override it.
Set final_action to your recommended action and override_reason to your explanation.
Only override if you have a strong business reason.

Return a JSON array of objects, one per workbook.
Return ONLY the JSON array. No markdown, no explanation."""


INTELLIGENCE_METADATA_PROMPT = """You are a BI governance analyst classifying Excel workbook summary reports.

Workbook: "{workbook_name}"
Purpose: {purpose}
Sheet names: {sheet_names}
Sample KPIs: {kpis}

Return a JSON object:
{{
  "ai_summary": "2-3 sentence plain-language summary of what this workbook does and who uses it",
  "domain_classification": "one of: reserves, compensation, claims, underwriting, investments, operations, other",
  "line_of_business": "high-level line of business using simple labels (e.g., Insurance, Group Benefits, Annuities)",
  "user_groups": ["business teams or roles that would use this workbook, e.g. Actuarial, Finance"]
}}

Return ONLY the JSON object. No markdown."""
