"""
KPI Clusters Routes — GET /api/kpi-clusters

Lists all canonical KPI groups with their original names.
"""
import json
import logging
from typing import List

from fastapi import APIRouter

from src.server.models.database import get_database
from src.server.models.schemas import KpiCluster

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["KPI Clusters"])


@router.get("/kpi-clusters", response_model=List[KpiCluster])
async def list_kpi_clusters():
    """List all canonical KPI groups with their original names."""
    db = get_database()

    # Group by canonical_name
    rows = db.query("""
        SELECT canonical_name, cluster_method,
               GROUP_CONCAT(original_name, '||') AS original_names_concat
        FROM kpi_cluster_cache
        GROUP BY canonical_name
        ORDER BY canonical_name
    """)

    results = []
    for r in rows:
        original_names = r.get("original_names_concat", "").split("||") if r.get("original_names_concat") else []

        # Count unique workbooks that use these KPIs
        workbook_count = 0
        if original_names:
            placeholders = ",".join(["?" for _ in original_names])
            count_row = db.query_one(
                f"""SELECT COUNT(DISTINCT workbook_id) as cnt
                    FROM calculated_fields
                    WHERE name IN ({placeholders})""",
                tuple(original_names)
            )
            workbook_count = count_row["cnt"] if count_row else 0

        results.append(KpiCluster(
            canonical_name=r["canonical_name"],
            original_names=original_names,
            workbook_count=workbook_count,
            cluster_method=r.get("cluster_method"),
        ))

    return results
