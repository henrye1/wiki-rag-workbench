import { Component, effect, inject, input, signal } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api } from '../../core/api';

@Component({
  selector: 'app-wiki-layout',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, MatTabsModule, MatIconModule],
  template: `
    <div class="page">
      <div class="row">
        <h1 class="grow">{{ info()?.name ?? w() }}</h1>
        <a [href]="'/view/' + w()" target="_blank" class="muted" title="Server-rendered read-only viewer">Public viewer ↗</a>
      </div>
      <nav mat-tab-nav-bar [tabPanel]="panel">
        @for (t of tabs; track t.path) {
          <a mat-tab-link [routerLink]="t.path" routerLinkActive #rla="routerLinkActive" [active]="rla.isActive">
            <mat-icon class="tab-icon">{{ t.icon }}</mat-icon>{{ t.label }}
          </a>
        }
      </nav>
      <mat-tab-nav-panel #panel><div class="body"><router-outlet /></div></mat-tab-nav-panel>
    </div>
  `,
  styles: `.tab-icon { margin-right: 6px; font-size: 18px; width: 18px; height: 18px; } .body { padding-top: 16px; }`,
})
export class WikiLayout {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly info = signal<any>(null);
  readonly tabs = [
    { path: 'pages', label: 'Pages', icon: 'article' },
    { path: 'sources', label: 'Sources & ingest', icon: 'upload_file' },
    { path: 'jobs', label: 'Jobs', icon: 'pending_actions' },
    { path: 'changesets', label: 'Changesets', icon: 'difference' },
    { path: 'lint', label: 'Lint', icon: 'rule' },
    { path: 'graph', label: 'Graph', icon: 'hub' },
    { path: 'settings', label: 'Schema & export', icon: 'settings' },
  ];

  constructor() {
    effect(() => { void this.api.wiki(this.w()).then((i) => this.info.set(i)); });
  }
}
