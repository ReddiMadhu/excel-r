import json

file_path = r"c:\Users\madhu\Desktop\excelrationlization\input files\data\output\LNBAR 2024 EB Reserve Deatils.json"

with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

formulas = []

def traverse(obj):
    if isinstance(obj, dict):
        if "formula" in obj and "formula_pattern" in obj:
            if obj["type"] in ["formula_based", "total", "pivot_value"]:
                lineage = obj.get("formula_lineage", {})
                direct_inputs = lineage.get("direct_inputs", []) if isinstance(lineage, dict) else []
                formulas.append({
                    "column": obj.get("column_name", "Unknown"),
                    "formula": obj["formula"],
                    "formula_pattern": obj["formula_pattern"],
                    "direct_inputs": direct_inputs
                })
        for k, v in obj.items():
            traverse(v)
    elif isinstance(obj, list):
        for item in obj:
            traverse(item)

traverse(data)

# Create a markdown report
report_path = r"c:\Users\madhu\Desktop\excelrationlization\input files\data\output\formula_patterns_report.md"
with open(report_path, 'w', encoding='utf-8') as f:
    f.write("# Formula Patterns Analysis\n\n")
    for item in formulas:
        f.write(f"### Column: {item['column']}\n")
        f.write(f"- **Raw Formula:** `{item['formula']}`\n")
        f.write(f"- **Current Pattern:** `{item['formula_pattern']}`\n")
        sources = ", ".join([f"{s.get('role', 'input')}: {s.get('column', 'Unknown')}" for s in item['direct_inputs']])
        f.write(f"- **Extracted Sources:** {sources}\n")
        f.write("\n")
print(f"Extracted {len(formulas)} formulas to {report_path}")
