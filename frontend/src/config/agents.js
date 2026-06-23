import { Search, Brain, GitCompare } from 'lucide-react';
import PortfolioView from '../views/PortfolioView';
import KpiExplorerView from '../views/KpiExplorerView';
import LandscapeView from '../views/LandscapeView';
import TableCatalogView from '../views/TableCatalogView';
import RationalizationView from '../views/RationalizationView';
import RiskDashboardView from '../views/RiskDashboardView';

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
    path: '/intelligence/kpi',
    label: 'BI Intelligence',
    icon: Brain,
    description: 'KPI insights, dataset relationships, formula analysis',
    routes: ['/intelligence'],
    tabs: [
      { id: 'kpi', label: 'KPI Explorer', path: '/intelligence/kpi', Component: KpiExplorerView },
      { id: 'tables', label: 'Table Catalog', path: '/intelligence/tables', Component: TableCatalogView },
      { id: 'landscape', label: 'Landscape Graph', path: '/intelligence/landscape', Component: LandscapeView },
    ],
    metrics: (m) => [
      { label: 'KPI Clusters', value: m.kpiClusterCount },
      { label: 'Calc Fields', value: m.calcFieldCount },
      { label: 'Shared KPIs', value: m.sharedKpiCount },
      { label: 'AI Summaries', value: m.aiSummaryCount },
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
      { id: 'risks', label: 'Risk Dashboard', path: '/rationalization/risks', Component: RiskDashboardView },
    ],
    metrics: (m) => [
      { label: 'Keep', value: m.keepCount },
      { label: 'Merge', value: m.mergeCount },
      { label: 'Decommission', value: m.decommissionCount },
      { label: 'Risks', value: m.riskCount },
    ],
  },
];

export function getAgent(agentId) {
  return agents.find(a => a.id === agentId);
}

export function getAgentByPath(pathname) {
  return agents.find(a =>
    a.routes.some(route => {
      if (route === '/discovery') return pathname === '/discovery' || pathname.startsWith('/workbooks');
      return pathname === route || pathname.startsWith(route + '/');
    })
  );
}
