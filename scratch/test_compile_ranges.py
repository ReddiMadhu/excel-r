"""Quick smoke test for scoped formula compile helpers."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.table_row_limit import (
    compile_range_for_table,
    collect_compile_range_refs,
    count_formulas_in_scoped_tables,
    formulas_range_ref,
)
from src.parsers import formula_parser

TABLE = {
    "sheet_name": "Summary",
    "table_range": "A6:I67",
    "col_start": 1,
    "col_end": 9,
    "row_classification": {
        "data_rows": list(range(10, 60)),
        "header_rows": [8, 9],
        "total_rows": [65],
        "check_rows": [],
        "title_rows": [6],
    },
}


def test_range_ref_format():
    fp = r"c:\test\GVUL Exb 5 Reserve Details.xlsx"
    ref = formulas_range_ref(fp, "Summary", "A6:I16")
    assert ref.startswith("'[")
    assert "]Summary'!A6:I16" in ref
    cr = compile_range_for_table(TABLE)
    refs = collect_compile_range_refs(fp, [TABLE], {"Summary"})
    assert len(refs) == 1
    assert "A6:" in refs[0] or "A" in refs[0]
    print("range_ref_format: ok", ref)


def test_compile_if_workbook(path: str):
    if not os.path.isfile(path):
        print(f"skip compile test — file not found: {path}")
        return
    sheet_types = {"Summary": "summary_report"}
    tables = []
    # minimal: use existing json detection would be better; run full pipeline step
    from src.parsers import summary_table_detector
    import openpyxl

    wb_val = openpyxl.load_workbook(path, data_only=True)
    wb_form = openpyxl.load_workbook(path, data_only=False)
    ws_v, ws_f = wb_val["Summary"], wb_form["Summary"]
    tables = summary_table_detector.extract_tables_from_sheet(ws_v, ws_f, None, wb_val)
    count = count_formulas_in_scoped_tables(path, tables, {"Summary"})
    print(f"scoped formula count: {count}")
    t0 = time.perf_counter()
    model = formula_parser.compile_workbook_scoped(
        path, sheet_types=sheet_types, detected_tables=tables
    )
    elapsed = time.perf_counter() - t0
    print(f"compile_workbook_scoped: {elapsed:.2f}s model={'yes' if model else 'None'}")


if __name__ == "__main__":
    test_range_ref_format()
    candidates = [
        os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data",
            "scans",
        ),
    ]
    for root in candidates:
        for dirpath, _, files in os.walk(root):
            for f in files:
                if f.endswith(".xlsx"):
                    test_compile_if_workbook(os.path.join(dirpath, f))
                    raise SystemExit(0)
    print("no xlsx found for live compile test")
