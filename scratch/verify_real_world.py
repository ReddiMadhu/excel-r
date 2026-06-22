"""
Real-world verification script.

- Uploads all .xlsx files in data/input to the running API
- Polls scan completion
- Prints summary of recommendations, review queue, and risks

Usage:
  py scratch/verify_real_world.py --base http://127.0.0.1:8001
"""
import argparse
import glob
import json
import os
import time
import urllib.request


def upload_files(base_url: str, file_paths):
    boundary = "----WebKitFormBoundaryRealWorld"
    body = b""
    for fp in file_paths:
        fname = os.path.basename(fp)
        with open(fp, "rb") as f:
            data = f.read()
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="files"; filename="{fname}"\r\n'.encode()
        body += b"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{base_url}/api/scans",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req).read())


def get_json(url: str):
    return json.loads(urllib.request.urlopen(url).read())


def poll_scan(base_url: str, scan_id: str, timeout=1200):
    start = time.time()
    while time.time() - start < timeout:
        p = get_json(f"{base_url}/api/scans/{scan_id}")
        print(
            f"  [{p.get('status')}] {p.get('phase')} "
            f"{p.get('processed_files')}/{p.get('total_files')} "
            f"({p.get('progress_percent')}%) file={p.get('current_file')}"
        )
        if p.get("status") in ("completed", "failed"):
            return p
        time.sleep(5)
    raise TimeoutError("scan polling timed out")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--input_dir", default=os.path.join("data", "input"))
    args = ap.parse_args()

    base = args.base.rstrip("/")
    files = sorted(glob.glob(os.path.join(args.input_dir, "*.xlsx")))
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    print(f"Found {len(files)} .xlsx files")
    if not files:
        return 1

    health = get_json(f"{base}/api/health")
    print("Health:", health.get("status"), "DB:", health.get("database"))

    scan = upload_files(base, files)
    scan_id = scan.get("scan_id")
    print("scan_id:", scan_id)
    poll_scan(base, scan_id)

    recs = get_json(f"{base}/api/governance/recommendations")
    actions = {}
    for r in recs:
        actions[r["action"]] = actions.get(r["action"], 0) + 1
    print("Recommendations:", actions)
    print("Review queue:", len([r for r in recs if r["action"] == "review"]))

    risks = get_json(f"{base}/api/governance/risks")
    sev = {}
    for r in risks:
        sev[r.get("severity", "unknown")] = sev.get(r.get("severity", "unknown"), 0) + 1
    print("Risks:", sev)

    pairwise = get_json(f"{base}/api/governance/pairwise")
    print("Pairwise workbooks:", len(pairwise.get("workbooks", [])), "pairs:", len(pairwise.get("pairs", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

