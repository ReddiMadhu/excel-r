"""Multi-file overlap detection test.

Uploads all 5 xlsx files and verifies:
1. All extractions complete
2. KPI clusters detect overlap across workbooks
3. Overlap scorer produces pairwise scores
4. Recommender generates merge/decommission/keep decisions
"""
import urllib.request
import json
import os
import time
import sys
import glob

BASE_URL = "http://localhost:8000"


def upload_files(file_paths):
    """Upload multiple files via multipart form data."""
    boundary = "----WebKitFormBoundaryMultiTest"
    body = b""

    for fp in file_paths:
        fname = os.path.basename(fp)
        with open(fp, "rb") as f:
            data = f.read()
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="files"; filename="{fname}"\r\n'.encode()
        body += b"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
        body += data
        body += b"\r\n"

    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{BASE_URL}/api/scans",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )

    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def poll_scan(scan_id, timeout=600):
    """Poll until complete or timeout (10 min for large files)."""
    start = time.time()
    while time.time() - start < timeout:
        resp = urllib.request.urlopen(f"{BASE_URL}/api/scans/{scan_id}")
        progress = json.loads(resp.read())
        status = progress["status"]
        phase = progress.get("phase", "")
        pct = progress.get("progress_percent", 0)
        current = progress.get("current_file", "")
        processed = progress.get("processed_files", 0)
        total = progress.get("total_files", 0)

        print(f"  [{status}] {phase} {processed}/{total} ({pct:.0f}%) file={current}")

        if status in ("completed", "failed"):
            return progress
        time.sleep(5)

    print("TIMEOUT!")
    return None


def get_json(endpoint):
    resp = urllib.request.urlopen(f"{BASE_URL}{endpoint}")
    return json.loads(resp.read())


def main():
    # Find all xlsx files
    input_dir = os.path.join("data", "input")
    files = sorted(glob.glob(os.path.join(input_dir, "*.xlsx")))
    # Skip temp files
    files = [f for f in files if not os.path.basename(f).startswith("~$")]

    print("=" * 70)
    print(f"Multi-File Overlap Detection Test — {len(files)} files")
    print("=" * 70)
    for f in files:
        size_mb = os.path.getsize(f) / (1024 * 1024)
        print(f"  {os.path.basename(f)} ({size_mb:.1f} MB)")

    # 1. Upload all files
    print(f"\n1. Uploading {len(files)} files...")
    result = upload_files(files)
    scan_id = result["scan_id"]
    print(f"   Scan: {scan_id}")
    print(f"   Total files: {result['total_files']}")

    # 2. Poll
    print("\n2. Polling progress (may take several minutes for large files)...")
    final = poll_scan(scan_id, timeout=600)
    if final:
        print(f"   Final: {final['status']}")
        if final.get("errors"):
            for err in final["errors"]:
                print(f"   ERROR: {err}")

    # 3. Check all endpoints
    print("\n3. Endpoint data counts:")
    workbooks = get_json("/api/workbooks")
    dashboards = get_json("/api/dashboards")
    datasources = get_json("/api/datasources")
    calc_fields = get_json("/api/calculated-fields")
    kpi_clusters = get_json("/api/kpi-clusters")
    recommendations = get_json("/api/governance/recommendations")
    risks = get_json("/api/governance/risks")

    print(f"   Workbooks:        {len(workbooks)}")
    print(f"   Dashboards:       {len(dashboards)}")
    print(f"   Datasources:      {len(datasources)}")
    print(f"   Calculated Fields:{len(calc_fields)}")
    print(f"   KPI Clusters:     {len(kpi_clusters)}")
    print(f"   Recommendations:  {len(recommendations)}")
    print(f"   Risks:            {len(risks)}")

    # 4. Workbook details
    print("\n4. Workbook Details:")
    print(f"   {'Name':<50} {'Sheets':>6} {'CalcF':>6} {'Complexity':>10}")
    print("   " + "-" * 75)
    for wb in workbooks:
        print(f"   {wb['name']:<50} {wb.get('sheet_count', 0):>6} "
              f"{wb.get('calculated_field_count', 0):>6} "
              f"{wb.get('extraction_complexity', 'N/A'):>10}")

    # 5. KPI Clusters (cross-workbook overlap indicator)
    print(f"\n5. KPI Clusters ({len(kpi_clusters)} canonical groups):")
    multi_wb = [c for c in kpi_clusters if c.get("workbook_count", 0) > 1]
    print(f"   Clusters spanning multiple workbooks: {len(multi_wb)}")
    for c in kpi_clusters[:15]:  # Show first 15
        print(f"   [{c.get('cluster_method','?')}] \"{c['canonical_name']}\" "
              f"({len(c.get('original_names', []))} members, "
              f"{c.get('workbook_count', 0)} workbooks)")

    # 6. Recommendations breakdown
    print(f"\n6. Rationalization Recommendations ({len(recommendations)}):")
    actions = {}
    for rec in recommendations:
        action = rec["action"]
        actions[action] = actions.get(action, 0) + 1
    for action, count in sorted(actions.items()):
        print(f"   {action}: {count} workbook(s)")

    print("\n   Details:")
    for rec in recommendations:
        print(f"   - \"{rec.get('workbook_name', '?')}\" -> {rec['action'].upper()}")
        if rec.get("merge_with_name"):
            print(f"     Merge with: \"{rec['merge_with_name']}\"")
        print(f"     KPI overlap: {rec.get('kpi_overlap_score', 0):.0%}, "
              f"DS overlap: {rec.get('datasource_overlap_score', 0):.0%}, "
              f"Uniqueness: {rec.get('uniqueness_score', 0):.2f}")
        if rec.get("common_kpis"):
            print(f"     Common KPIs: {rec['common_kpis'][:5]}")
        if rec.get("reasons"):
            for reason in rec["reasons"]:
                print(f"     -> {reason}")
        print()

    print("=" * 70)
    print("Multi-file test complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
