import { Compass, Sparkles, GitCompare, Layers, FileSearch } from 'lucide-react';
import PortfolioView from '../views/PortfolioView';
import KpiExplorerView from '../views/KpiExplorerView';
import LandscapeView from '../views/LandscapeView';
import RationalizationView from '../views/RationalizationView';
import OverlapAnalysisView from '../views/OverlapAnalysisView';
import ExcelReviewView from '../views/ExcelReviewView';

export const agents = [
  {
    id: 'discovery',
    path: '/discovery',
    label: 'BI Discovery',
    icon: Compass,
    description: 'Database structure, LOB catalog, dataset metadata',
    routes: ['/discovery', '/workbooks', '/excel-review'],
    tabs: [
      { id: 'portfolio', label: 'Portfolio', path: '/discovery', Component: PortfolioView },
      { id: 'excel-review', label: 'Excel Review', path: '/excel-review', Component: ExcelReviewView, icon: FileSearch },
    ],
    metrics: (m) => [
      { label: 'Reports', value: m.workbookCount },
      { label: 'Sheets', value: m.sheetCount },
      { label: 'Datasources', value: m.datasourceCount },
      { label: 'Excel Findings', value: m.excelReviewCount },
    ],
  },
  {
    id: 'intelligence',
    path: '/intelligence',
    label: 'BI Intelligence',
    icon: Sparkles,
    description: 'Shared business metrics and KPI groups across reports',
    routes: ['/intelligence'],
    tabs: [
      { id: 'metrics', label: 'Shared Metrics', path: '/intelligence', Component: KpiExplorerView },
      { id: 'landscape', label: 'Landscape', path: '/intelligence/landscape', Component: LandscapeView },
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
    description: 'Portfolio merge / keep / decommission / governance review',
    routes: ['/rationalization', '/overlap-analysis'],
    tabs: [
      { id: 'results', label: 'Rationalization', path: '/rationalization', Component: RationalizationView },
      { id: 'overlap', label: 'Overlap Analysis', path: '/overlap-analysis', Component: OverlapAnalysisView, icon: Layers },
    ],
    metrics: (m) => [
      { label: 'Keep', value: m.keepCount },
      { label: 'Merge', value: m.mergeCount },
      { label: 'Decommission', value: m.decommissionCount },
      { label: 'Gov. Review', value: m.reviewCount },
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
      if (route === '/excel-review') {
        return pathname === '/excel-review' || pathname.startsWith('/excel-review/');
      }
      return pathname === route || pathname.startsWith(route + '/');
    })
  );
}
