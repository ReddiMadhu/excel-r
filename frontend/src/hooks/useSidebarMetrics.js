import { useState, useEffect, useCallback } from 'react';
import { api } from '../api/client';

const EMPTY_METRICS = {
  workbookCount: null,
  sheetCount: null,
  datasourceCount: null,
  lobCount: null,
  kpiClusterCount: null,
  calcFieldCount: null,
  sharedKpiCount: null,
  aiSummaryCount: null,
  keepCount: null,
  mergeCount: null,
  decommissionCount: null,
  reviewCount: null,
  riskCount: null,
};

function aggregateMetrics(results) {
  const [workbooks, datasources, dashboards, calcFields, kpiClusters, recommendations, risks] = results;

  const metrics = { ...EMPTY_METRICS };

  if (workbooks.status === 'fulfilled' && Array.isArray(workbooks.value)) {
    metrics.workbookCount = workbooks.value.length;
    metrics.sheetCount = workbooks.value.reduce((s, w) => s + (w.sheet_count || 0), 0);
  }

  if (datasources.status === 'fulfilled' && Array.isArray(datasources.value)) {
    metrics.datasourceCount = datasources.value.length;
  }

  if (dashboards.status === 'fulfilled' && Array.isArray(dashboards.value)) {
    const lobs = new Set(
      dashboards.value
        .map(d => d.line_of_business)
        .filter(Boolean)
    );
    metrics.lobCount = lobs.size;
    metrics.aiSummaryCount = dashboards.value.filter(d => d.ai_summary?.trim()).length;
  }

  if (calcFields.status === 'fulfilled' && Array.isArray(calcFields.value)) {
    metrics.calcFieldCount = calcFields.value.length;
  }

  if (kpiClusters.status === 'fulfilled' && Array.isArray(kpiClusters.value)) {
    metrics.kpiClusterCount = kpiClusters.value.length;
    metrics.sharedKpiCount = kpiClusters.value.filter(c => c.workbook_count > 1).length;
  }

  if (recommendations.status === 'fulfilled' && Array.isArray(recommendations.value)) {
    const recs = recommendations.value;
    metrics.keepCount = recs.filter(r => r.action === 'keep').length;
    metrics.mergeCount = recs.filter(r => r.action === 'merge').length;
    metrics.decommissionCount = recs.filter(
      r => r.action === 'decommission' || r.action === 'delete'
    ).length;
    metrics.reviewCount = recs.filter(r => r.action === 'review').length;
  }

  if (risks.status === 'fulfilled' && Array.isArray(risks.value)) {
    metrics.riskCount = risks.value.length;
  }

  return metrics;
}

export function useSidebarMetrics() {
  const [metrics, setMetrics] = useState(EMPTY_METRICS);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    setLoading(true);
    try {
      const results = await Promise.allSettled([
        api.getWorkbooks(),
        api.getDatasources(),
        api.getDashboards(),
        api.getCalculatedFields(),
        api.getKpiClusters(),
        api.getRecommendations(),
        api.getRisks(),
      ]);
      setMetrics(aggregateMetrics(results));
    } catch {
      setMetrics(EMPTY_METRICS);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refetch(); }, [refetch]);

  return { metrics, loading, refetch };
}
