import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', loadComponent: () => import('./pages/home').then((m) => m.Home), title: 'Workbench' },
  { path: 'ask', loadComponent: () => import('./pages/ask').then((m) => m.Ask), title: 'Ask' },
  { path: 'documents', loadComponent: () => import('./pages/documents').then((m) => m.Documents), title: 'RAG documents' },
  { path: 'bulk', loadComponent: () => import('./pages/bulk').then((m) => m.Bulk), title: 'Bulk requirements' },
  { path: 'wiki', loadComponent: () => import('./pages/wiki/wiki-select').then((m) => m.WikiSelect), title: 'Wiki' },
  {
    path: 'wiki/:w',
    loadComponent: () => import('./pages/wiki/wiki-layout').then((m) => m.WikiLayout),
    children: [
      { path: '', redirectTo: 'pages', pathMatch: 'full' },
      { path: 'pages', loadComponent: () => import('./pages/wiki/pages').then((m) => m.WikiPages) },
      { path: 'pages/:slug', loadComponent: () => import('./pages/wiki/page').then((m) => m.WikiPage) },
      { path: 'sources', loadComponent: () => import('./pages/wiki/sources').then((m) => m.WikiSources) },
      { path: 'jobs', loadComponent: () => import('./pages/wiki/jobs').then((m) => m.WikiJobs) },
      { path: 'changesets', loadComponent: () => import('./pages/wiki/changesets').then((m) => m.WikiChangesets) },
      { path: 'changesets/:id', loadComponent: () => import('./pages/wiki/changeset').then((m) => m.WikiChangeset) },
      { path: 'lint', loadComponent: () => import('./pages/wiki/lint').then((m) => m.WikiLint) },
      { path: 'graph', loadComponent: () => import('./pages/wiki/graph').then((m) => m.WikiGraph) },
      { path: 'settings', loadComponent: () => import('./pages/wiki/settings').then((m) => m.WikiSettings) },
    ],
  },
  { path: 'benchmark', loadComponent: () => import('./pages/benchmark/runs').then((m) => m.BenchRuns), title: 'Benchmark' },
  { path: 'benchmark/rubric', loadComponent: () => import('./pages/benchmark/rubric').then((m) => m.BenchRubric), title: 'Rubric review' },
  { path: 'benchmark/compare', loadComponent: () => import('./pages/benchmark/compare').then((m) => m.BenchCompare) },
  { path: 'benchmark/:id', loadComponent: () => import('./pages/benchmark/run').then((m) => m.BenchRun) },
  { path: 'benchmark/:id/topic/:n', loadComponent: () => import('./pages/benchmark/topic').then((m) => m.BenchTopic) },
  { path: '**', redirectTo: '' },
];
