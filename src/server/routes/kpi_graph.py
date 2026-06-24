"""
KPI Graph Routes — GET /api/kpi-graph/data, GET /api/kpi-graph/summary

Generates D3 force-directed graph node-link representations of sheets, tables,
KPIs, LOBs, user groups, upload age, datasources, and schema relationships.
"""
import json
import logging
import re
from datetime import datetime
from typing import List, Optional, Set, Tuple

from fastapi import APIRouter, Query

from src.server.models.database import get_database
from src.rationalization.overlap_scorer import compute_pairwise_overlaps
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
            return [val] if val else []
    return [val]


def _parse_workbook_ids(workbook_ids: Optional[str]) -> Optional[List[int]]:
    if not workbook_ids:
        return None
    ids = []
    for part in workbook_ids.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids or None


def build_graph_data(
    requested_dashboards: Optional[List[str]] = None,
    workbook_id: Optional[int] = None,
    workbook_ids: Optional[List[int]] = None,
):
    """Query DB and build node/link graph lists."""
    db = get_database()
    requested_dashboards = requested_dashboards or []

    all_rows = db.query("""
        SELECT d.*, w.name AS workbook_name, w.uploaded_at AS workbook_uploaded_at
        FROM dashboards d
        JOIN workbooks w ON d.workbook_id = w.id
    """)

    id_filter: Optional[Set[int]] = None
    if workbook_id is not None:
        id_filter = {workbook_id}
    elif workbook_ids:
        id_filter = set(workbook_ids)

    matched_dashboards = []
    for r in all_rows:
        if id_filter is not None and r["workbook_id"] not in id_filter:
            continue

        if id_filter is None and requested_dashboards:
            name_lower = r["name"].lower()
            wb_lower = r["workbook_name"].lower()
            matched = False
            for req in requested_dashboards:
                if (
                    req == name_lower or req == wb_lower
                    or req in name_lower or name_lower in req
                    or req.replace(".xlsx", "") == wb_lower
                ):
                    matched = True
                    break
            if not matched:
                continue

        matched_dashboards.append(r)

    nodes = []
    links = []
    node_ids: Set[str] = set()
    link_keys: Set[Tuple[str, str, str]] = set()

    def add_node(nid: str, group: str, label: str, extra: dict = None):
        if nid not in node_ids:
            nodes.append({
                "id": nid,
                "group": group,
                "label": label,
                **(extra or {}),
            })
            node_ids.add(nid)

    def add_link(source: str, target: str, label: str = "", extra: dict = None):
        key = (source, target, label)
        if key in link_keys:
            return
        link_keys.add(key)
        links.append({
            "source": source,
            "target": target,
            "label": label,
            **(extra or {}),
        })

    cluster_rows = db.query("SELECT original_name, canonical_name FROM kpi_cluster_cache")
    kpi_map = {row["original_name"].lower(): row["canonical_name"] for row in cluster_rows}

    # Index tables and datasources per workbook for relationship resolution
    table_index: dict = {}  # (workbook_id, name_lower) -> node_id
    datasource_index: dict = {}  # (workbook_id, name_lower) -> node_id

    for dash in matched_dashboards:
        if dash.get("sheet_type") == "raw_data":
            ds_id = f"ds_{dash['id']}"
            add_node(ds_id, "Datasource", dash["name"], {
                "sheet_id": dash["id"],
                "workbook_id": dash["workbook_id"],
            })
            datasource_index[(dash["workbook_id"], dash["name"].lower())] = ds_id
            datasources = db.query(
                "SELECT name FROM datasources WHERE workbook_id = ? AND name = ?",
                (dash["workbook_id"], dash["name"]),
            )
            for ds in datasources:
                datasource_index[(dash["workbook_id"], ds["name"].lower())] = ds_id

    for dash in matched_dashboards:
        if dash.get("sheet_type") == "raw_data":
            continue

        dash_id = f"dash_{dash['id']}"
        dash_label = f"{dash['workbook_name']} - {dash['name']}"
        add_node(dash_id, "Dashboard", dash_label, {
            "complexity": dash.get("complexity_score") or 1.0,
            "sheet_id": dash["id"],
            "workbook_id": dash["workbook_id"],
        })

        lob = dash.get("line_of_business")
        if lob:
            lob_id = f"lob_{lob.lower().replace(' ', '_')}"
            add_node(lob_id, "Line of Business", lob)
            add_link(dash_id, lob_id, "belongs_to")

        domain = dash.get("domain_classification")
        if domain:
            domain_id = f"domain_{domain.lower().replace(' ', '_')}"
            add_node(domain_id, "Business Area", domain)
            add_link(dash_id, domain_id, "in_domain")

        ugroups = _parse_json_field(dash.get("user_groups"))
        for g in ugroups:
            if not g:
                continue
            group_id = f"group_{str(g).lower().replace(' ', '_')}"
            add_node(group_id, "User Group", str(g))
            add_link(dash_id, group_id, "used_by")

        try:
            up_time_str = dash.get("workbook_uploaded_at")
            if up_time_str:
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
            age_label = "Recent Upload (< 1 month)"
        elif days_old <= 180:
            age_label = "Active (1-6 months)"
        else:
            age_label = "Stale (> 6 months)"

        age_id = f"upload_age_{age_label.lower().replace(' ', '_').replace('<', 'lt').replace('>', 'gt')}"
        add_node(age_id, "Upload Age", age_label)
        add_link(dash_id, age_id, "uploaded")

        tables = db.query("SELECT * FROM worksheets WHERE dashboard_id = ?", (dash["id"],))
        for t in tables:
            t_id = f"table_{t['id']}"
            t_name = t["name"]
            add_node(t_id, "Table", t_name, {"table_id": t["id"]})
            add_link(dash_id, t_id, "contains")
            table_index[(dash["workbook_id"], t_name.lower())] = t_id

        cfs = db.query("SELECT * FROM calculated_fields WHERE dashboard_id = ?", (dash["id"],))
        for cf in cfs:
            orig_name = cf["name"]
            canon_name = kpi_map.get(orig_name.lower(), orig_name)

            match = re.search(r"\b(?:by|per)\s+([a-zA-Z0-9_\s]+)", canon_name, re.IGNORECASE)
            if match:
                gran = f"{match.group(1).strip().title()} Level"
                base_kpi = re.sub(
                    r"\b(?:by|per)\s+([a-zA-Z0-9_\s]+)", "", canon_name, flags=re.IGNORECASE
                ).strip()
            else:
                gran = "Overall Level"
                base_kpi = canon_name

            kpi_id = f"kpi_{base_kpi.lower().replace(' ', '_')}"
            add_node(kpi_id, "KPI", base_kpi, {"definition": cf.get("definition") or ""})

            gran_id = f"granularity_{gran.lower().replace(' ', '_')}"
            add_node(gran_id, "Granularity Level", gran)

            add_link(dash_id, kpi_id, "has_kpi", {"granularity": gran})
            add_link(kpi_id, gran_id, "granularity")

            cf_table = (cf.get("table_name") or "").lower()
            if cf_table and (dash["workbook_id"], cf_table) in table_index:
                add_link(kpi_id, table_index[(dash["workbook_id"], cf_table)], "defined_in")

            sources = _parse_json_field(cf.get("ultimate_raw_sources"))
            for src in sources:
                if not src:
                    continue
                src_lower = str(src).lower()
                src_key = (dash["workbook_id"], src_lower)
                target_id = datasource_index.get(src_key) or table_index.get(src_key)
                if not target_id:
                    for (wb_id, name), nid in {**datasource_index, **table_index}.items():
                        if wb_id == dash["workbook_id"] and (name in src_lower or src_lower in name):
                            target_id = nid
                            break
                if target_id:
                    add_link(kpi_id, target_id, "sources_from")

    # Second pass: inter-table relationships after full table index is built
    for dash in matched_dashboards:
        if dash.get("sheet_type") == "raw_data":
            continue
        tables = db.query("SELECT * FROM worksheets WHERE dashboard_id = ?", (dash["id"],))
        for t in tables:
            t_id = f"table_{t['id']}"
            relationships = _parse_json_field(t.get("inter_table_relationships"))
            for rel in relationships:
                if not rel or not isinstance(rel, str):
                    continue
                rel_lower = rel.lower()
                for (wb_id, other_name), other_tid in table_index.items():
                    if wb_id != dash["workbook_id"]:
                        continue
                    if other_name in rel_lower and other_tid != t_id:
                        add_link(t_id, other_tid, "relates_to")

    return nodes, links, matched_dashboards


def build_rationalization_graph(workbook_ids: Optional[List[int]] = None):
    """
    Workbook-centric graph for rationalization: pairwise overlap edges,
    shared KPI/datasource bridge nodes, and recommendation actions.
    """
    db = get_database()

    if workbook_ids:
        placeholders = ",".join("?" * len(workbook_ids))
        workbooks = db.query(
            f"SELECT id, name, purpose FROM workbooks WHERE id IN ({placeholders}) ORDER BY name",
            tuple(workbook_ids),
        )
    else:
        workbooks = db.query("SELECT id, name, purpose FROM workbooks ORDER BY name")

    if len(workbooks) < 2:
        return [], [], workbooks

    wb_id_list = [w["id"] for w in workbooks]
    pairwise = compute_pairwise_overlaps(db, workbook_ids=wb_id_list)

    rec_rows = db.query("""
        SELECT gr.workbook_id, gr.action, gr.merge_with_name, gr.reasons,
               gr.kpi_overlap_score, gr.datasource_overlap_score
        FROM governance_recommendations gr
    """)
    rec_map = {r["workbook_id"]: r for r in rec_rows}

    nodes: list = []
    links: list = []
    node_ids: Set[str] = set()
    link_keys: Set[Tuple[str, str, str]] = set()

    def add_node(nid: str, group: str, label: str, extra: dict = None):
        if nid not in node_ids:
            nodes.append({"id": nid, "group": group, "label": label, **(extra or {})})
            node_ids.add(nid)

    def add_link(source: str, target: str, label: str = "", extra: dict = None):
        key = (source, target, label)
        if key in link_keys:
            return
        link_keys.add(key)
        links.append({"source": source, "target": target, "label": label, **(extra or {})})

    for wb in workbooks:
        rec = rec_map.get(wb["id"], {})
        reasons = rec.get("reasons") or []
        if isinstance(reasons, str):
            try:
                reasons = json.loads(reasons)
            except Exception:
                reasons = [reasons]
        add_node(
            f"wb_{wb['id']}",
            "Workbook",
            wb["name"],
            {
                "workbook_id": wb["id"],
                "action": rec.get("action", "keep"),
                "merge_with_name": rec.get("merge_with_name"),
                "definition": reasons[0] if reasons else (wb.get("purpose") or ""),
                "kpi_overlap_score": rec.get("kpi_overlap_score"),
                "datasource_overlap_score": rec.get("datasource_overlap_score"),
            },
        )

    for (id_a, id_b), ov in pairwise.items():
        kpi_ov = ov.get("kpi_overlap", 0)
        ds_ov = ov.get("ds_overlap", 0)
        if kpi_ov < 0.05 and ds_ov < 0.05:
            continue
        combined = ov.get("combined_score", 0)
        label = f"KPI {kpi_ov:.0%} · DS {ds_ov:.0%}"
        add_link(
            f"wb_{id_a}",
            f"wb_{id_b}",
            label,
            {
                "kpi_overlap": kpi_ov,
                "ds_overlap": ds_ov,
                "fingerprint_ratio": ov.get("fingerprint_ratio", 0),
                "overlap_class": ov.get("overlap_class", ""),
                "stroke_width": 1.5 + combined * 5,
            },
        )

    kpi_to_wbs: dict = {}
    ds_to_wbs: dict = {}
    for (id_a, id_b), ov in pairwise.items():
        for kpi in ov.get("common_kpis", []):
            kpi_to_wbs.setdefault(kpi, set()).update([id_a, id_b])
        for ds in ov.get("common_datasources", []):
            ds_to_wbs.setdefault(ds, set()).update([id_a, id_b])

    for kpi, wb_set in kpi_to_wbs.items():
        if len(wb_set) < 2:
            continue
        safe = re.sub(r"[^a-z0-9_]+", "_", kpi.lower())[:48]
        kid = f"shared_kpi_{safe}"
        add_node(kid, "Shared KPI", kpi)
        for wid in wb_set:
            add_link(f"wb_{wid}", kid, "shares_kpi")

    for ds, wb_set in ds_to_wbs.items():
        if len(wb_set) < 2:
            continue
        safe = re.sub(r"[^a-z0-9_]+", "_", str(ds).lower())[:48]
        did = f"shared_ds_{safe}"
        add_node(did, "Shared Datasource", str(ds))
        for wid in wb_set:
            add_link(f"wb_{wid}", did, "shares_source")

    return nodes, links, workbooks


@router.get("/data")
async def get_kpi_graph_data(
    dashboards: Optional[str] = Query(None, description="Comma separated list of dashboard names"),
    workbook_id: Optional[int] = Query(None, description="Filter to a single workbook ID"),
    workbook_ids: Optional[str] = Query(None, description="Comma-separated workbook IDs"),
    view: str = Query("landscape", description="landscape | rationalization"),
):
    """Retrieve nodes and links for D3 network graph visualization."""
    cleaned_dashboards = []
    if dashboards:
        cleaned = dashboards.replace("|||", ",")
        cleaned_dashboards = [d.strip().lower() for d in cleaned.split(",") if d.strip()]

    wb_ids = _parse_workbook_ids(workbook_ids)

    if view == "rationalization":
        nodes, links, _ = build_rationalization_graph(workbook_ids=wb_ids)
    else:
        nodes, links, _ = build_graph_data(
            cleaned_dashboards,
            workbook_id=workbook_id,
            workbook_ids=wb_ids,
        )
    return {"nodes": nodes, "links": links, "view": view}

