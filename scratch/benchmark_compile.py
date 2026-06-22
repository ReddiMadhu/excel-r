"""Benchmark scoped formula compile on four test workbooks."""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
from src.parsers import formula_parser, summary_table_detector

NAMES = [
    "GVUL Exb 5 Reserve Details.xlsx",
    "LNBAR 2024 EB Reserve Deatils.xlsx",
    "LNBAR 2024 EB Reserve Details_without tax reserves.xlsx",
    "LNBAR Worksite A Reserve Details.xlsx",
]


def find_workbooks():
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "scans")
    found = {}
    for path in glob.glob(os.path.join(root, "**", "*.xlsx"), recursive=True):
        base = os.path.basename(path)
        if base in NAMES and base not in found:
            found[base] = path
    return [found[n] for n in NAMES if n in found]


def main():
    paths = find_workbooks()
    total = 0.0
    for path in paths:
        name = os.path.basename(path)
        wb_v = openpyxl.load_workbook(path, data_only=True)
        wb_f = openpyxl.load_workbook(path, data_only=False)
        tables = summary_table_detector.extract_tables_from_sheet(
            wb_v["Summary"], wb_f["Summary"], None, wb_v
        )
        t0 = time.perf_counter()
        model = formula_parser.compile_workbook_scoped(
            path, {"Summary": "summary_report"}, tables
        )
        elapsed = time.perf_counter() - t0
        total += elapsed
        print(f"{name}: {elapsed:.2f}s model={'yes' if model else 'skip'}")
    print(f"COMPILE_TOTAL: {total:.2f}s across {len(paths)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
