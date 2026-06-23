import { Search, Brain, GitCompare } from 'lucide-react';
import PortfolioView from '../views/PortfolioView';
import WorkbookInsightsView from '../views/WorkbookInsightsView';
import KpiExplorerView from '../views/KpiExplorerView';
import RationalizationView from '../views/RationalizationView';

export const agents = [
  {
    id: 'discovery',
    path: '/discovery',
    label: 'BI Discovery',
    icon: Search,
    description: 'Database structure, LOB catalog, dataset metadata',
    routes: ['/discovery', '/workbooks'],
    tabs: [
      { id: 'portfolio', label: 'Portfolio', path: '/discovery', Component: PortfolioView },
    ],
    metrics: (m) => [
      { label: 'Workbooks', value: m.workbookCount },
      { label: 'Sheets', value: m.sheetCount },
      { label: 'Datasources', value: m.datasourceCount },
      { label: 'LOBs', value: m.lobCount },
    ],
  },
  {
    id: 'intelligence',
    path: '/intelligence',
    label: 'BI Intelligence',
    icon: Brain,
    description: 'Business summaries, shared metrics, and sheet context',
    routes: ['/intelligence'],
    tabs: [
      { id: 'insights', label: 'Workbook Guide', path: '/intelligence', Component: WorkbookInsightsView },
      { id: 'metrics', label: 'Shared Metrics', path: '/intelligence/metrics', Component: KpiExplorerView },
    ],
    metrics: (m) => [
      { label: 'Summaries', value: m.aiSummaryCount },
      { label: 'Metric Groups', value: m.kpiClusterCount },
      { label: 'Shared Metrics', value: m.sharedKpiCount },
      { label: 'Columns', value: m.calcFieldCount },
    ],
  },
  {
    id: 'rationalization',
    path: '/rationalization',
    label: 'BI Rationalization',
    icon: GitCompare,
    description: 'Asset evaluation, merge/retain/discard recommendations',
    routes: ['/rationalization'],
    tabs: [
      { id: 'results', label: 'Rationalization', path: '/rationalization', Component: RationalizationView },
    ],
    metrics: (m) => [
      { label: 'Keep', value: m.keepCount },
      { label: 'Merge', value: m.mergeCount },
      { label: 'Decommission', value: m.decommissionCount },
      { label: 'Review', value: m.reviewCount },
    ],
  },
];

export function getAgent(agentId) {
  return agents.find(a => a.id === agentId);
}

export function getAgentByPath(pathname) {
  return agents.find(a =>
    a.routes.some(route => {
      if (route === '/discovery') {
        return pathname === '/discovery'
          || pathname.startsWith('/discovery/')
          || pathname.startsWith('/workbooks');
      }
      return pathname === route || pathname.startsWith(route + '/');
    })
  );
}
