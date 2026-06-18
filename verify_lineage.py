import json
with open('data/output/LNBAR 2024 EB Reserve Deatils.json', encoding='utf-8') as f:
    data = json.load(f)

found = 0
missing = 0
for sheet in data['sheets']:
    for table in sheet.get('tables', []):
        for col in table.get('columns', []):
            if col.get('type') == 'formula_based':
                if 'formula_lineage' in col:
                    lin = col['formula_lineage']
                    found += 1
                    print(f"\n=== {col['column_name']} ===")
                    print(f"  formula       : {col.get('formula','')[:70]}")
                    print(f"  comp_type     : {lin.get('computation_type')}")
                    print(f"  lineage_depth : {lin.get('lineage_depth')}")
                    print(f"  fingerprint   : {lin.get('fingerprint')}")
                    params = lin.get('computation_params', {})
                    if params.get('group_by'):
                        print(f"  group_by      : {params['group_by']}")
                    if params.get('static_filters'):
                        print(f"  static_filters: {params['static_filters']}")
                    print(f"  raw_sources   : {lin.get('ultimate_raw_sources')}")
                else:
                    missing += 1
                    print(f"  [NO LINEAGE] {col['column_name']} -- {col.get('formula','')[:50]}")

print(f"\n\nSUMMARY: {found} formula columns have lineage, {missing} are missing lineage")
