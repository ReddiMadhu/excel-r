import openpyxl
from src.extractors.formatting_extractor import analyze_row_formatting
from src.parsers.summary_table_detector import classify_table_rows

wb = openpyxl.load_workbook(r"data\input\LNBAR 2024 EB Reserve Deatils.xlsx", data_only=True)
ws = wb["Summary"]

# Column I to K is 9 to 11
col_start = 9
col_end = 11

row_analyses = {}
for r in range(4, 10):
    analysis = analyze_row_formatting(ws, r, col_start, col_end)
    print(f"Row {r}:")
    print(f"  first_value: {analysis.get('first_value')}")
    print(f"  non_empty_count: {analysis.get('non_empty_count')}")
    print(f"  bold_ratio: {analysis.get('bold_ratio')}")
    print(f"  is_total: {analysis.get('is_total')}")
    print(f"  is_section_title: {analysis.get('is_section_title')}")
    print(f"  is_header: {analysis.get('is_header')}")
    print(f"  has_data: {analysis.get('has_data')}")
    print("-" * 30)

classification = classify_table_rows(ws, wb["Summary"], 4, 9, col_start, col_end)
print("Classification result:")
for k, v in classification.items():
    print(f"  {k}: {v}")
