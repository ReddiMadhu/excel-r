"""Test script: upload a single file via POST /api/scans and verify DB population."""
import urllib.request
import json
import os
import time
import sys

BASE_URL = "http://localhost:8000"

def upload_file(file_path):
    """Upload a file via multipart form data."""
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return None

    with open(file_path, "rb") as f:
        file_data = f.read()

    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="files"; filename="{os.path.basename(file_path)}"\r\n'.encode()
    body += b"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
    body += file_data
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{BASE_URL}/api/scans",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST"
    )

    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def poll_scan(scan_id, timeout=120):
    """Poll scan progress until complete or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        resp = urllib.request.urlopen(f"{BASE_URL}/api/scans/{scan_id}")
        progress = json.loads(resp.read())
        status = progress["status"]
        phase = progress.get("phase", "")
        pct = progress.get("progress_percent", 0)
        current = progress.get("current_file", "")
        print(f"  [{status}] phase={phase} progress={pct}% file={current}")

        if status in ("completed", "failed"):
            return progress

        time.sleep(3)

    print("TIMEOUT waiting for scan")
    return None


def check_endpoints():
    """Verify all data endpoints return data."""
    endpoints = [
        "/api/workbooks",
        "/api/dashboards",
        "/api/datasources",
        "/api/calculated-fields",
        "/api/kpi-clusters",
        "/api/governance/recommendations",
        "/api/governance/risks",
    ]

    for ep in endpoints:
        resp = urllib.request.urlopen(f"{BASE_URL}{ep}")
        data = json.loads(resp.read())
        count = len(data) if isinstance(data, list) else "N/A"
        print(f"  {ep}: {count} items")


def main():
    file_path = os.path.join("data", "input", "LNBAR Worksite A Reserve Details.xlsx")

    print("=" * 60)
    print("Test: Upload file and verify end-to-end pipeline")
    print("=" * 60)

    # 1. Upload
    print("\n1. Uploading file...")
    result = upload_file(file_path)
    if not result:
        print("Upload failed!")
        sys.exit(1)
    print(f"   Scan created: {result['scan_id']}")
    scan_id = result["scan_id"]

    # 2. Poll
    print("\n2. Polling progress...")
    final = poll_scan(scan_id)
    if final:
        print(f"   Final status: {final['status']}")
        if final.get("errors"):
            print(f"   Errors: {final['errors']}")

    # 3. Verify endpoints
    print("\n3. Checking data endpoints...")
    check_endpoints()

    # 4. Check specific workbook details
    print("\n4. Checking workbook detail...")
    resp = urllib.request.urlopen(f"{BASE_URL}/api/workbooks")
    workbooks = json.loads(resp.read())
    if workbooks:
        wb = workbooks[0]
        print(f"   Workbook: {wb['name']}")
        print(f"   Sheets: {wb.get('sheet_count')}")
        print(f"   Dashboards: {wb.get('dashboard_count')}")
        print(f"   Calculated fields: {wb.get('calculated_field_count')}")
        print(f"   Datasources: {wb.get('datasource_count')}")
        print(f"   Complexity: {wb.get('extraction_complexity')}")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
