"""
KPI Graph Routes — GET /api/kpi-graph/data, GET /api/kpi-graph/summary

Generates D3 force-directed graph node-link representations of sheets, tables,
KPIs, LOBs, user groups, and recency.
"""
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Query, HTTPException

from src.server.models.database import get_database
from src.utils.llm_client import get_resilient_llm, stringify_chat_content

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kpi-graph", tags=["KPI Graph"])


def _parse_json_field(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return [val]
    return [val]


def build_graph_data(requested_dashboards: List[str]):
    """Helper to query DB and build node/link graph lists."""
    db = get_database()
    
    # Fetch all dashboards & workbooks
    all_rows = db.query("""
        SELECT d.*, w.name AS workbook_name, w.uploaded_at AS workbook_uploaded_at
        FROM dashboards d
        JOIN workbooks w ON d.workbook_id = w.id
    """)
    
    # Filter by name matching
    matched_dashboards = []
    for r in all_rows:
        name_lower = r["name"].lower()
        wb_lower = r["workbook_name"].lower()
        
        # If requested_dashboards is empty, match everything
        if not requested_dashboards:
            matched_dashboards.append(r)
            continue
            
        matched = False
        for req in requested_dashboards:
            # Match sheet name or workbook source file prefix
            if (req == name_lower or req == wb_lower or 
                req in name_lower or name_lower in req or
                req.replace(".xlsx", "") == wb_lower):
                matched = True
                break
        if matched:
            matched_dashboards.append(r)
            
    nodes = []
    links = []
    node_ids = set()
    
    def add_node(nid: str, group: str, label: str, extra: dict = None):
        if nid not in node_ids:
            nodes.append({
                "id": nid,
                "group": group,
                "label": label,
                **(extra or {})
            })
            node_ids.add(nid)
            
    def add_link(source: str, target: str, label: str = "", extra: dict = None):
        links.append({
            "source": source,
            "target": target,
            "label": label,
            **(extra or {})
        })

    # Read KPI cluster cache for canonical mapping
    cluster_rows = db.query("SELECT original_name, canonical_name FROM kpi_cluster_cache")
    kpi_map = {row["original_name"].lower(): row["canonical_name"] for row in cluster_rows}

    for dash in matched_dashboards:
        dash_id = f"dash_{dash['id']}"
        dash_label = f"{dash['workbook_name']} - {dash['name']}"
        add_node(dash_id, "Dashboard", dash_label, {
            "complexity": dash.get("complexity_score") or 1.0,
            "sheet_id": dash["id"]
        })
        
        # 1. Business Area
        lob = dash.get("line_of_business") or dash.get("domain_classification")
        if lob:
            domain_id = f"domain_{lob.lower().replace(' ', '_')}"
            add_node(domain_id, "Business Area", lob)
            add_link(dash_id, domain_id, "belongs_to")
            
        # 2. User Groups
        ugroups = _parse_json_field(dash.get("user_groups"))
        for g in ugroups:
            if not g:
                continue
            group_id = f"group_{g.lower().replace(' ', '_')}"
            add_node(group_id, "User Group", g)
            add_link(dash_id, group_id, "used_by")
            
        # 3. Access Recency / Frequency
        try:
            up_time_str = dash.get("workbook_uploaded_at")
            if up_time_str:
                # SQLite timestamps can be ISO format
                if " " in up_time_str:
                    dt = datetime.strptime(up_time_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                else:
                    dt = datetime.fromisoformat(up_time_str.split(".")[0])
                days_old = (datetime.now() - dt).days
            else:
                days_old = 0
        except Exception:
            days_old = 0
            
        if days_old <= 30:
            freq_label = "Recent Upload (< 1 month)"
        elif days_old <= 180:
            freq_label = "Active (1-6 months)"
        else:
            freq_label = "Stale (> 6 months)"
            
        freq_id = f"freq_{freq_label.lower().replace(' ', '_').replace('<', 'lt').replace('>', 'gt')}"
        add_node(freq_id, "Access Recency", freq_label)
        add_link(dash_id, freq_id, "accessed")
        
        # 4. Tables (Worksheets inside this sheet)
        tables = db.query("SELECT * FROM worksheets WHERE dashboard_id = ?", (dash["id"],))
        for t in tables:
            t_id = f"table_{t['id']}"
            add_node(t_id, "Table", t["name"])
            add_link(dash_id, t_id, "queries")
            
        # 5. KPIs (Calculated fields in this sheet)
        cfs = db.query("SELECT * FROM calculated_fields WHERE dashboard_id = ?", (dash["id"],))
        for cf in cfs:
            orig_name = cf["name"]
            canon_name = kpi_map.get(orig_name.lower(), orig_name)
            
            # Identify granularity based on "by" or "per" in name
            import re
            match = re.search(r"\b(?:by|per)\s+([a-zA-Z0-9_\s]+)", canon_name, re.IGNORECASE)
            if match:
                gran = f"{match.group(1).strip().title()} Level"
                base_kpi = re.sub(r"\b(?:by|per)\s+([a-zA-Z0-9_\s]+)", "", canon_name, flags=re.IGNORECASE).strip()
            else:
                gran = "Overall Level"
                base_kpi = canon_name
                
            kpi_id = f"kpi_{base_kpi.lower().replace(' ', '_')}"
            add_node(kpi_id, "KPI", base_kpi, {"definition": cf.get("definition") or ""})
            
            gran_id = f"granularity_{gran.lower().replace(' ', '_')}"
            add_node(gran_id, "Granularity Level", gran)
            
            # Links: Dashboard -> KPI, KPI -> Granularity
            add_link(dash_id, kpi_id, "", {"granularity": gran})
            add_link(kpi_id, gran_id, "")
            
    return nodes, links, matched_dashboards


@router.get("/data")
async def get_kpi_graph_data(
    dashboards: Optional[str] = Query(None, description="Comma separated list of dashboard names")
):
    """Retrieve nodes and links for D3 network graph visualization."""
    cleaned_dashboards = []
    if dashboards:
        cleaned = dashboards.replace("|||", ",")
        cleaned_dashboards = [d.strip().lower() for d in cleaned.split(",") if d.strip()]
        
    nodes, links, _ = build_graph_data(cleaned_dashboards)
    return {"nodes": nodes, "links": links}


@router.get("/summary")
async def get_kpi_graph_summary(
    dashboards: Optional[str] = Query(None, description="Comma-separated list of dashboards"),
    focus_type: str = Query("all", description="Type of node highlights focused on")
):
    """Generates an LLM summary describing landscape connections and overlaps."""
    cleaned_dashboards = []
    if dashboards:
        cleaned = dashboards.replace("|||", ",")
        cleaned_dashboards = [d.strip().lower() for d in cleaned.split(",") if d.strip()]
        
    nodes, links, matched = build_graph_data(cleaned_dashboards)
    if not matched:
        return {"summary": "No dashboards found matching query."}
        
    # Get LLM client
    llm = get_resilient_llm(temperature=0.0, json_mode=False)
    if not llm:
        return {"summary": "LLM client is not configured. Cannot generate landscape insights summary."}
        
    # Format graph nodes and links for LLM
    nodes_str = "\n".join([f"- {n['group']}: {n['label']}" for n in nodes[:50]]) # limit to avoid bloating token counts
    links_str = "\n".join([f"- {l['source']} --({l['label']})--> {l['target']}" for l in links[:60]])
    dash_summaries = "\n".join([
        f"Dashboard Name: {d['name']}\nWorkbook: {d['workbook_name']}\nLOB: {d.get('line_of_business')}\nAI Summary: {d.get('ai_summary') or 'N/A'}"
        for d in matched
    ])

    prompt = f"""You are a BI governance expert analyzing a network graph of Excel workbooks (dashboards), tables, KPIs, business areas (LOBs), user groups, and recency.

The user is current highlighting the '{focus_type}' view in the graph.
Analyze the connections and details below to extract high-level strategic insights.

CRITICAL INSTRUCTIONS:
- Start your response exactly with: 'The key insights from the graph are:'
- Output a simple list of bullet points using dashes '-'.
- PROVIDE EXACTLY 3 to 4 bullet points. Focus on the most important and surprising insights.
- EACH bullet point MUST be exactly 1 short sentence (maximum 15 words).
- DO NOT use bold (**) or other markdown formats besides dashes.
- Output PLAIN TEXT ONLY.
- If multiple workbooks are present, provide combined insights (e.g. 'Both X and Y share table Z but target different users'). Do not list dashboards individually.

--- Graph Nodes ---
{nodes_str}

--- Graph Links ---
{links_str}

--- Dashboard Details ---
{dash_summaries}
"""

    try:
        response = llm.invoke(prompt)
        summary_text = stringify_chat_content(response.content).strip()
        return {"summary": summary_text}
    except Exception as e:
        logger.error("Failed to generate KPI graph summary: %s", e)
        return {"summary": "Unable to connect to AI provider to compile graph insights."}
