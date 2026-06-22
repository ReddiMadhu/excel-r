"""Test the decommission architecture end-to-end."""
import urllib.request
import json
import sys

BASE = "http://localhost:8000"

def get(endpoint):
    try:
        resp = urllib.request.urlopen(f"{BASE}{endpoint}")
        return json.loads(resp.read())
    except Exception as e:
        print(f"  ERROR: {endpoint} -> {e}")
        return None

def main():
    print("=" * 70)
    print("DECOMMISSION ARCHITECTURE TEST")
    print("=" * 70)

    # 1. Health check
    health = get("/api/health")
    if not health:
        print("FAIL: Server not reachable")
        sys.exit(1)
    print(f"1. Health: {health.get('status', 'unknown')}")

    # 2. Workbooks
    workbooks = get("/api/workbooks")
    print(f"\n2. Workbooks in DB: {len(workbooks)}")
    for wb in workbooks:
        print(f"   - [{wb['id']}] {wb['name']} "
              f"(sheets={wb.get('sheet_count',0)}, "
              f"calcFields={wb.get('calculated_field_count',0)}, "
              f"complexity={wb.get('extraction_complexity','?')})")

    # 3. KPI Clusters
    clusters = get("/api/kpi-clusters")
    print(f"\n3. KPI Clusters: {len(clusters)}")
    multi_wb = [c for c in clusters if c.get("workbook_count", 0) > 1]
    print(f"   Clusters spanning >1 workbook: {len(multi_wb)}")
    for c in clusters[:10]:
        print(f"   - [{c.get('cluster_method','?')}] \"{c['canonical_name']}\" "
              f"({len(c.get('original_names',[]))} members, "
              f"{c.get('workbook_count',0)} workbooks)")

    # 4. Governance Recommendations
    recs = get("/api/governance/recommendations")
    print(f"\n4. Governance Recommendations: {len(recs)}")
    actions = {}
    for r in recs:
        a = r["action"]
        actions[a] = actions.get(a, 0) + 1
    for action, count in sorted(actions.items()):
        print(f"   {action}: {count} workbook(s)")

    # 5. Decommission details
    decom = [r for r in recs if r["action"] == "decommission"]
    print(f"\n5. DECOMMISSION Details ({len(decom)} workbooks):")
    for r in decom:
        print(f"   - \"{r.get('workbook_name','?')}\"")
        print(f"     Merge target: \"{r.get('merge_with_name','N/A')}\"")
        print(f"     KPI overlap: {r.get('kpi_overlap_score',0):.0%}")
        print(f"     DS overlap:  {r.get('datasource_overlap_score',0):.0%}")
        print(f"     Uniqueness:  {r.get('uniqueness_score',0):.2f}")
        if r.get("common_kpis"):
            print(f"     Common KPIs: {r['common_kpis'][:5]}")
        if r.get("matching_fingerprints"):
            fps = r["matching_fingerprints"]
            print(f"     Fingerprint matches: {len(fps)}")
        if r.get("reasons"):
            for reason in r["reasons"]:
                print(f"     -> {reason}")
        if r.get("llm_justification"):
            print(f"     LLM: {r['llm_justification'][:120]}...")
        print()

    # 6. Merge details
    merges = [r for r in recs if r["action"] == "merge"]
    print(f"6. MERGE Details ({len(merges)} workbooks):")
    for r in merges:
        print(f"   - \"{r.get('workbook_name','?')}\" -> merge with \"{r.get('merge_with_name','N/A')}\"")
        print(f"     KPI overlap: {r.get('kpi_overlap_score',0):.0%}")
        if r.get("reasons"):
            for reason in r["reasons"]:
                print(f"     -> {reason}")
        print()

    # 7. Keep details
    keeps = [r for r in recs if r["action"] == "keep"]
    print(f"7. KEEP Details ({len(keeps)} workbooks):")
    for r in keeps:
        print(f"   - \"{r.get('workbook_name','?')}\" uniqueness={r.get('uniqueness_score',0):.2f}")

    # 8. Risks
    risks = get("/api/governance/risks")
    print(f"\n8. Governance Risks: {len(risks)}")
    for risk in risks[:5]:
        print(f"   - [{risk.get('severity','?')}] {risk.get('risk_type','?')}: "
              f"{risk.get('description','')[:80]}")

    # 9. KPI Graph Data
    graph = get("/api/kpi-graph/data")
    if graph:
        nodes = graph.get("nodes", [])
        links = graph.get("links", [])
        node_types = {}
        for n in nodes:
            t = n.get("type", "?")
            node_types[t] = node_types.get(t, 0) + 1
        print(f"\n9. KPI Graph: {len(nodes)} nodes, {len(links)} links")
        for t, c in sorted(node_types.items()):
            print(f"   {t}: {c}")

    # 10. Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Workbooks:         {len(workbooks)}")
    print(f"  KPI Clusters:      {len(clusters)}")
    print(f"  Recommendations:   {len(recs)}")
    print(f"    - keep:          {actions.get('keep', 0)}")
    print(f"    - merge:         {actions.get('merge', 0)}")
    print(f"    - decommission:  {actions.get('decommission', 0)}")
    print(f"  Risks:             {len(risks)}")

    # Validation checks
    print("\nVALIDATION:")
    checks = []

    # Check: recommendations exist
    if len(recs) > 0:
        checks.append(("Recommendations generated", "PASS"))
    else:
        checks.append(("Recommendations generated", "FAIL"))

    # Check: decommission decisions have merge targets
    bad_decom = [r for r in decom if not r.get("merge_with_name")]
    if len(bad_decom) == 0:
        checks.append(("All decommissions have merge targets", "PASS"))
    else:
        checks.append(("All decommissions have merge targets", f"FAIL ({len(bad_decom)} missing)"))

    # Check: decommission decisions have reasons
    no_reason = [r for r in decom if not r.get("reasons")]
    if len(no_reason) == 0:
        checks.append(("All decommissions have reasons", "PASS"))
    else:
        checks.append(("All decommissions have reasons", f"FAIL ({len(no_reason)} missing)"))

    # Check: decommission decisions have overlap scores
    no_score = [r for r in decom if r.get("kpi_overlap_score", 0) == 0 and r.get("datasource_overlap_score", 0) == 0]
    if len(no_score) == 0:
        checks.append(("All decommissions have overlap scores", "PASS"))
    else:
        checks.append(("All decommissions have overlap scores", f"FAIL ({len(no_score)} missing)"))

    # Check: fingerprint detection
    has_fp = [r for r in decom if r.get("matching_fingerprints")]
    checks.append((f"Fingerprint detection ({len(has_fp)}/{len(decom)} decommissions)", "PASS" if has_fp else "WARN"))

    # Check: LLM justifications
    has_llm = [r for r in recs if r.get("llm_justification")]
    checks.append((f"LLM justifications ({len(has_llm)}/{len(recs)} recommendations)", "PASS" if has_llm else "WARN"))

    # Check: common KPIs populated
    has_kpis = [r for r in decom if r.get("common_kpis")]
    checks.append((f"Common KPIs populated ({len(has_kpis)}/{len(decom)} decommissions)", "PASS" if has_kpis else "WARN"))

    # Check: graph data available
    if graph and len(graph.get("nodes", [])) > 0:
        checks.append(("Graph data available", "PASS"))
    else:
        checks.append(("Graph data available", "FAIL"))

    for check, result in checks:
        icon = "PASS" if result == "PASS" else ("WARN" if result == "WARN" else "FAIL")
        print(f"  [{icon}] {check}")

    failed = [c for c in checks if "FAIL" in c[1]]
    if failed:
        print(f"\n  {len(failed)} check(s) FAILED!")
        sys.exit(1)
    else:
        print(f"\n  All {len(checks)} checks passed!")


if __name__ == "__main__":
    main()
