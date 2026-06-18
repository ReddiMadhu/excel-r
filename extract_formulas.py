import json
import os

import glob

output_dir = r"c:\Users\madhu\Desktop\excelrationlization\input files\data\output"
json_files = glob.glob(os.path.join(output_dir, "*.json"))

formulas = []

def extract_from_table(table, file_name):
    for col in table.get("columns", []):
        if col.get("type") in ["formula_based", "total", "pivot_value"] and col.get("formula"):
            lineage = col.get("formula_lineage", {})
            direct_inputs = lineage.get("direct_inputs", [])
            formulas.append({
                "file": file_name,
                "table": table.get("table_name", "Unknown"),
                "column": col.get("column_name", "Unknown"),
                "type": col.get("type"),
                "formula": col.get("formula"),
                "formula_pattern": col.get("formula_pattern"),
                "direct_inputs": direct_inputs
            })

for file_path in json_files:
    if os.path.basename(file_path) == "validation_report.json":
        continue
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if "sheets" in data:
        for sheet in data["sheets"]:
            for table in sheet.get("tables", []):
                extract_from_table(table, os.path.basename(file_path))

# Create a markdown report
report_path = r"c:\Users\madhu\Desktop\excelrationlization\input files\data\output\formula_patterns_report.md"
with open(report_path, 'w', encoding='utf-8') as f:
    f.write("# Formula Patterns Analysis\n\n")
    for item in formulas:
        f.write(f"### Table: {item['table']} | Column: {item['column']}\n")
        f.write(f"- **Workbook:** `{item['file']}`\n")
        f.write(f"- **Type:** `{item['type']}`\n")
        f.write(f"- **Raw/Synthetic Formula:** `{item['formula']}`\n")
        f.write(f"- **Current Pattern:** `{item['formula_pattern']}`\n")
        sources = ", ".join([f"{s.get('role', 'input')}: {s.get('column', 'Unknown')} ({s.get('table', 'Unknown')})" for s in item['direct_inputs']])
        f.write(f"- **Extracted Sources:** {sources}\n")
        f.write("\n")
print(f"Extracted {len(formulas)} formulas to {report_path}")
