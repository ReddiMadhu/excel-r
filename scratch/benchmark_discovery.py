"""Benchmark Discovery extraction on the four standard test workbooks."""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.main import process_single_file

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
    if len(paths) < 4:
        print(f"Found {len(paths)}/4 workbooks — skipping full benchmark")
        return 1
    out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "output")
    os.makedirs(out, exist_ok=True)
    total = 0.0
    for path in paths:
        t0 = time.perf_counter()
        process_single_file(path, out)
        elapsed = time.perf_counter() - t0
        total += elapsed
        print(f"{os.path.basename(path)}: {elapsed:.1f}s")
    print(f"DISCOVERY_SIM_TOTAL: {total:.1f}s")
    return 0 if total < 90 else 2


if __name__ == "__main__":
    raise SystemExit(main())
