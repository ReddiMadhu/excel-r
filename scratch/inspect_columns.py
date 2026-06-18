import json

with open("data/output/LNBAR 2024 EB Reserve Deatils.json", "r", encoding="utf-8") as f:
    data = json.load(f)

sheets = data.get("sheets", [])
for sheet in sheets:
    if sheet.get("sheet_name") == "Summary":
        tables = sheet.get("tables", [])
        print("Total tables:", len(tables))
        for i, t in enumerate(tables):
            print(f"Table {i}: Name={t.get('table_name')}, Range={t.get('table_range')}, Columns={list(t.keys())}")
            if "columns" in t:
                cols = t["columns"]
                print(f"  Columns ({len(cols)}): {[c.get('column_name') for c in cols]}")
            else:
                print("  No columns key!")
