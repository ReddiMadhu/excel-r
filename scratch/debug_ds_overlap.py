import sys, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from src.server.models.database import Database
from src.rationalization.overlap_scorer import _get_raw_sources_for_workbook, jaccard_similarity

db = Database()

id_a, id_b = 1, 2
src_a = _get_raw_sources_for_workbook(db, id_a)
src_b = _get_raw_sources_for_workbook(db, id_b)

common = sorted(src_a & src_b)
only_a = sorted(src_a - src_b)
only_b = sorted(src_b - src_a)

print(f"DS Overlap (Jaccard): {jaccard_similarity(src_a, src_b):.4f}")
print(f"|A|={len(src_a)}, |B|={len(src_b)}, |Common|={len(common)}, |Union|={len(src_a | src_b)}")
print(f"Jaccard = {len(common)} / {len(src_a | src_b)} = {len(common)/len(src_a | src_b):.4f}")

print(f"\nCommon sources ({len(common)}):")
for s in common:
    print(f"  + {s}")

print(f"\nOnly in WB 1 ({len(only_a)}):")
for s in only_a:
    print(f"  - {s}")

print(f"\nOnly in WB 2 ({len(only_b)}):")
for s in only_b:
    print(f"  - {s}")

# Now check: what are the ultimate_raw_sources for each
print("\n\n=== RAW ultimate_raw_sources ===")
for wid in [1, 2]:
    rows = db.query("""
        SELECT name, ultimate_raw_sources
        FROM calculated_fields
        WHERE workbook_id = ?
          AND ultimate_raw_sources IS NOT NULL
          AND ultimate_raw_sources != '[]'
    """, (wid,))
    print(f"\nWB {wid} formula -> raw sources:")
    for r in rows:
        urs = json.loads(r["ultimate_raw_sources"]) if r["ultimate_raw_sources"] else []
        print(f"  {r['name']}: {urs}")
