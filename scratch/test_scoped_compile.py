"""Quick benchmark: full vs summary-only formulas compile."""
import glob
import os
import time

import formulas


def find_file():
    for pattern in (
        "data/scans/**/LNBAR Worksite*.xlsx",
        "data/scans/**/*.xlsx",
    ):
        files = glob.glob(pattern, recursive=True)
        if files:
            return files[0]
    return None


def summary_push_only(fp):
    t0 = time.perf_counter()
    m = formulas.ExcelModel()
    book, ctx = m.add_book(fp)
    for ws in book.worksheets:
        if "summary" in ws.title.lower():
            m.push(ws, ctx)
    m.finish(complete=False, assemble=True)
    return time.perf_counter() - t0, len(m.cells)


def full_load(fp):
    t0 = time.perf_counter()
    m = formulas.ExcelModel().loads(fp).finish()
    return time.perf_counter() - t0, len(m.cells)


if __name__ == "__main__":
    fp = find_file()
    if not fp:
        print("no xlsx found")
        raise SystemExit(1)
    print("file:", os.path.basename(fp))
    s, sc = summary_push_only(fp)
    print(f"summary-only: {s:.2f}s cells={sc}")
    # Uncomment to compare full (slow):
    # f, fc = full_load(fp)
    # print(f"full: {f:.2f}s cells={fc}")
