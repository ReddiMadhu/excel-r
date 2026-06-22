"""Analyze real-world extraction + rationalization quality."""
import glob
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.validation import compute_comparison_readiness
from src.server.models.database import get_database


def analyze_json_outputs():
    print("=== JSON comparison readiness ===")
    files = sorted(glob.glob(os.path.join(PROJECT_ROOT, "data", "output", "*.json")))
    files = [f for f in files if not f.endswith("validation_report.json")]
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        r = compute_comparison_readiness(data)
        name = os.path.basename(fp)
        print(
            f"{name}: mode={r['comparison_mode']} quality={r['extraction_quality_score']:.2f} "
            f"comp={r['comparable_columns']} ready={r['ready_columns']} "
            f"degraded={r['degraded_columns']} missing={r['missing_columns']}"
        )


def analyze_db():
    print("\n=== DB rationalization state ===")
    db = get_database()
    wb_count = db.query_one("SELECT COUNT(*) as cnt FROM workbooks")
    print("workbooks:", wb_count["cnt"] if wb_count else 0)

    fp = db.query_one("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN fingerprint IS NOT NULL AND fingerprint != '' THEN 1 ELSE 0 END) as with_fp
        FROM calculated_fields
        WHERE column_type IN ('formula_based', 'pivot_value')
    """)
    if fp and fp["total"]:
        cov = fp["with_fp"] / fp["total"]
        print(f"fingerprint coverage: {fp['with_fp']}/{fp['total']} ({cov:.0%})")

    quality = db.query("""
        SELECT name, extraction_quality_score, comparison_mode
        FROM workbooks
        ORDER BY id DESC LIMIT 10
    """)
    print("\nLatest workbooks:")
    for w in quality:
        print(f"  {w['name']}: quality={w.get('extraction_quality_score')} mode={w.get('comparison_mode')}")

    recs = db.query("SELECT action, COUNT(*) as cnt FROM governance_recommendations GROUP BY action")
    print("\nRecommendations:", {r["action"]: r["cnt"] for r in recs})

    risks = db.query("SELECT severity, COUNT(*) as cnt FROM governance_risks GROUP BY severity")
    print("Risks:", {r["severity"]: r["cnt"] for r in risks})

    # LNBAR pair overlap sample
    lnbar = db.query("SELECT id, name FROM workbooks WHERE name LIKE 'LNBAR%' ORDER BY id")
    if len(lnbar) >= 2:
        from src.rationalization.overlap_scorer import compute_pairwise_overlaps
        ids = [w["id"] for w in lnbar[:4]]
        pairwise = compute_pairwise_overlaps(db, workbook_ids=ids)
        print(f"\nLNBAR pairwise overlaps ({len(pairwise)} pairs):")
        for (a, b), o in list(pairwise.items())[:5]:
            print(
                f"  {o.get('name_a')} vs {o.get('name_b')}: "
                f"kpi={o['kpi_overlap']:.0%} ds={o['ds_overlap']:.0%} "
                f"class={o.get('overlap_class')}"
            )


if __name__ == "__main__":
    analyze_json_outputs()
    analyze_db()
