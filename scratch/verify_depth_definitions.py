import json
import os
import sys

def verify():
    json_path = "data/output/Test_3Sheet_Lineage.json"
    if not os.path.exists(json_path):
        print(f"Error: Output JSON file {json_path} does not exist. Make sure the parser runs first.")
        sys.exit(1)

    print(f"Loading {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("\n--- Verifying Workbook Metadata ---")
    print(f"File Name: {data.get('file_name')}")
    print(f"Purpose: {data.get('purpose')}")

    sheets = data.get("sheets", [])
    print(f"Found {len(sheets)} sheets in JSON.")

    all_ok = True

    for sheet in sheets:
        sheet_name = sheet.get("sheet_name")
        sheet_type = sheet.get("sheet_type")
        tables = sheet.get("tables", [])
        print(f"\nSheet: {sheet_name} ({sheet_type}), contains {len(tables)} tables")

        for table in tables:
            t_name = table.get("table_name")
            print(f"  Table: {t_name}")
            
            # Check table-level fields
            table_keys = ["business_purpose", "grain", "measures", "dimensions"]
            missing_table_keys = [k for k in table_keys if k not in table]
            if missing_table_keys:
                print(f"    [FAIL] Table is missing metadata keys: {missing_table_keys}")
                all_ok = False
            else:
                print(f"    [PASS] Table metadata keys present: {table_keys}")
                print(f"      Business Purpose: {table.get('business_purpose')}")
                print(f"      Grain: {table.get('grain')}")
                print(f"      Measures: {table.get('measures')}")
                print(f"      Dimensions: {table.get('dimensions')}")

            # Check column-level fields
            columns = table.get("columns", [])
            print(f"    Contains {len(columns)} columns:")
            for col in columns:
                c_name = col.get("column_name")
                c_type = col.get("type")
                
                col_keys = ["nesting_depth", "function_chain", "definition"]
                missing_col_keys = [k for k in col_keys if k not in col]
                if missing_col_keys:
                    print(f"      [FAIL] Column '{c_name}' missing keys: {missing_col_keys}")
                    all_ok = False
                else:
                    depth = col.get("nesting_depth")
                    chain = col.get("function_chain")
                    defn = col.get("definition")
                    formula = col.get("formula", "")
                    
                    print(f"      Column: {c_name} ({c_type})")
                    print(f"        Formula: {formula if formula else '<none>'}")
                    print(f"        Nesting Depth: {depth} (Expected >0 for formulas)")
                    print(f"        Function Chain: {chain}")
                    print(f"        Definition: {defn}")
                    
                    # Basic assertion checks
                    if formula and depth == 0 and ("SUM" in formula or "IF" in formula or "COUNT" in formula):
                        print(f"        [FAIL] Column '{c_name}' has formula '{formula}' but nesting_depth is 0!")
                        all_ok = False
                    if not formula and depth != 0:
                        print(f"        [FAIL] Column '{c_name}' has no formula but nesting_depth is {depth} (expected 0)!")
                        all_ok = False

    if all_ok:
        print("\n[SUCCESS] All checks passed! Nesting depth and semantic definitions metadata are correctly structured.")
        sys.exit(0)
    else:
        print("\n[FAIL] Some verification checks failed.")
        sys.exit(1)

if __name__ == "__main__":
    verify()
