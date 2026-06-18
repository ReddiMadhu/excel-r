import json
import glob
import os

output_dir = r"c:\Users\madhu\Desktop\excelrationlization\input files\data\output"
json_files = glob.glob(os.path.join(output_dir, "*.json"))

print(f"Scanning files in output directory: {output_dir}")

diagnostics = []
by_fingerprint = {}

for fp in json_files:
    fn = os.path.basename(fp)
    if fn in ["validation_report.json"]:
        continue
        
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    for sheet in data.get("sheets", []):
        s_name = sheet.get("sheet_name", "")
        for table in sheet.get("tables", []):
            t_name = table.get("table_name", "")
            for col in table.get("columns", []):
                col_name = col.get("column_name", "")
                col_type = col.get("type", "")
                formula = col.get("formula", "")
                pattern = col.get("formula_pattern", "")
                
                # Check calculated columns
                if col_type in ("formula_based", "total", "check", "pivot_value") or formula:
                    lineage = col.get("formula_lineage")
                    
                    has_lineage = lineage is not None
                    has_fp = has_lineage and bool(lineage.get("fingerprint"))
                    has_sources = has_lineage and len(lineage.get("ultimate_raw_sources", [])) > 0
                    
                    # Verify lineage matches formula archetype
                    comp_type = lineage.get("computation_type", "UNKNOWN") if has_lineage else "NONE"
                    archetype_ok = True
                    formula_upper = str(formula).upper()
                    
                    if "SUMIFS(" in formula_upper:
                        if comp_type not in ("SUMIFS", "MULTI_AGG"):
                            archetype_ok = False
                    elif "COUNTIFS(" in formula_upper:
                        if comp_type != "COUNTIFS":
                            archetype_ok = False
                    elif "SUM(" in formula_upper and not "SUMIFS(" in formula_upper:
                        if comp_type not in ("SUM_RANGE", "MULTI_AGG"):
                            archetype_ok = False
                    
                    diagnostics.append({
                        "file": fn,
                        "sheet": s_name,
                        "table": t_name,
                        "column": col_name,
                        "type": col_type,
                        "formula": formula,
                        "pattern": pattern,
                        "has_lineage": has_lineage,
                        "has_fingerprint": has_fp,
                        "fingerprint": lineage.get("fingerprint") if has_lineage else None,
                        "has_sources": has_sources,
                        "raw_sources": lineage.get("ultimate_raw_sources", []) if has_lineage else [],
                        "comp_type": comp_type,
                        "archetype_ok": archetype_ok
                    })
                    
                    if has_fp:
                        fingerprint = lineage.get("fingerprint")
                        if fingerprint not in by_fingerprint:
                            by_fingerprint[fingerprint] = []
                        by_fingerprint[fingerprint].append({
                            "file": fn,
                            "sheet": s_name,
                            "table": t_name,
                            "column": col_name,
                            "formula": formula
                        })

# Generate Verification Report
print("\n" + "="*80)
print("LINEAGE & FORMULA DIAGNOSTIC RESULTS")
print("="*80)

failures = 0
failed_columns_details = []

for d in diagnostics:
    status = "OK"
    issues = []
    if not d["has_lineage"]:
        status = "FAILED"
        issues.append("Missing formula_lineage object")
    else:
        if not d["has_fingerprint"]:
            status = "FAILED"
            issues.append("Missing or empty fingerprint")
        if not d["has_sources"]:
            status = "FAILED"
            issues.append("No ultimate_raw_sources resolved")
        if not d["archetype_ok"]:
            status = "WARNING"
            issues.append(f"Lineage archetype mismatch (Formula has keyword, but comp_type is '{d['comp_type']}')")
            
    if status != "OK":
        failures += 1
        failed_columns_details.append((status, d, issues))
        print(f"[{status}] File: {d['file']} | Table: {d['table']} | Column: {d['column']}")
        print(f"  Formula    : {d['formula']}")
        print(f"  Pattern    : {d['pattern']}")
        print(f"  Issues     : {', '.join(issues)}")
        print("-" * 50)

print(f"\nTotal Calculated Columns Inspected: {len(diagnostics)}")
print(f"Columns with structural lineage issues/warnings: {failures}")
if failures == 0:
    print("SUCCESS: All columns passed lineage diagnostics!")

# Print Duplicate Logic Groupings (Rationalization insights)
print("\n" + "="*80)
print("LOGIC RATIONALIZATION INSIGHTS (DUPLICATE FORMULA FINGERPRINTS)")
print("="*80)

duplicate_groups = {fp: items for fp, items in by_fingerprint.items() if len(items) > 1}
print(f"Found {len(duplicate_groups)} logical categories shared across different columns or workbooks:")

for idx, (fp, items) in enumerate(duplicate_groups.items(), 1):
    print(f"\nGroup #{idx}: Logic Fingerprint: `{fp}`")
    for item in items:
        print(f"  - Workbook: {item['file']} | Table: {item['table']} | Column: {item['column']}")
        print(f"    Formula : {item['formula']}")

# Write to Markdown Artifact
md_path = r"C:\Users\madhu\.gemini\antigravity-ide\brain\1273dc2e-a0df-496e-82a9-f84ad6085103\lineage_comparison_report.md"
with open(md_path, "w", encoding="utf-8") as md:
    md.write("# Lineage & Formula Comparative Diagnostic Report\n\n")
    md.write("This report validates the extracted logic, formula patterns, and computational lineages for all calculated columns across the output JSON files.\n\n")
    
    md.write("## 1. Summary of Diagnostics\n\n")
    md.write(f"- **Total calculated/formula columns inspected:** {len(diagnostics)}\n")
    md.write(f"- **Status:** {'🟢 PASS' if failures == 0 else '⚠️ WARNINGS/FAILURES'}\n")
    md.write(f"- **Columns with issues/warnings:** {failures}\n\n")
    
    if failed_columns_details:
        md.write("### ⚠️ Columns Requiring Attention\n\n")
        md.write("| Status | Workbook | Table | Column | Formula | Detected Issues |\n")
        md.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for status, d, issues in failed_columns_details:
            md.write(f"| `{status}` | `{d['file']}` | `{d['table']}` | `{d['column']}` | `{d['formula'][:50]}` | {', '.join(issues)} |\n")
        md.write("\n")
    else:
        md.write("> [!NOTE]\n")
        md.write("> All calculated and pivot-table columns successfully resolved their formula lineages, generated unique logic fingerprints, and mapped to raw data sources with 100% logic alignment.\n\n")
        
    md.write("## 2. Logic Rationalization & Decommissioning Insights\n\n")
    md.write("The lineage system generates unique logic **fingerprints** (canonical representations of aggregate columns based on sum ranges, group fields, and filters). Columns with identical fingerprints share identical business calculation rules and can be merged or decommissioned.\n\n")
    
    md.write(f"We detected **{len(duplicate_groups)} logic classes** shared across different columns or workbooks:\n\n")
    
    for idx, (fp, items) in enumerate(duplicate_groups.items(), 1):
        md.write(f"### Logic Category {idx}: `{fp}`\n\n")
        md.write("| Workbook | Table | Column | Extracted Excel/Pivot Formula |\n")
        md.write("| :--- | :--- | :--- | :--- |\n")
        for item in items:
            md.write(f"| `{item['file']}` | `{item['table']}` | `{item['column']}` | `{item['formula']}` |\n")
        md.write("\n---\n\n")

print(f"Saved markdown lineage comparison report to: {md_path}")


