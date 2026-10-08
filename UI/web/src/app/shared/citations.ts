import { Component, effect, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { RouterLink } from '@angular/router';
import { Api, errMsg } from '../core/api';
import { CitationService, CitationTarget } from './citation-service';
import { Markdown } from './markdown';

@Component({
  selector: 'app-citation-panel',
  imports: [MatButtonModule, MatIconModule, MatProgressBarModule, RouterLink, Markdown],
  template: `
    @if (svc.target(); as t) {
      <div class="head">
        <div class="grow">
          <div class="muted small">{{ t.kind === 'rag' ? 'Source paragraph (RAG index)' : 'Wiki page' }}</div>
          <h2>{{ t.kind === 'rag' ? t.ref : (page()?.title ?? t.slug) }}</h2>
        </div>
        <button mat-icon-button (click)="svc.close()" aria-label="Close"><mat-icon>close</mat-icon></button>
      </div>
      @if (loading()) { <mat-progress-bar mode="indeterminate" /> }
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (t.kind === 'rag') {
        @for (c of chunks(); track c.id) {
          <div class="chunk">
            <div class="muted small">
              <span class="pill">{{ c.source_type }}</span> page {{ c.page }} · {{ c.heading }}
              @if (c.part) { · part {{ c.part + 1 }} }
            </div>
            <p>{{ c.content }}</p>
            <div class="muted small">{{ c.filename }}</div>
          </div>
        }
      } @else if (page(); as p) {
        <div class="muted small"><span class="pill">{{ p.type }}</span> v{{ p.version }}</div>
        @if (p.summary) { <p class="muted"><em>{{ p.summary }}</em></p> }
        <app-md [text]="p.content_md" [wiki]="t.wiki" [cites]="false" />
        <a mat-stroked-button [routerLink]="['/wiki', t.wiki, 'pages', t.slug]" (click)="svc.close()">Open page</a>
      }
    }
  `,
  styles: `
    :host { display: block; padding: 12px 16px 24px; }
    .head { display: flex; align-items: flex-start; gap: 8px; }
    h2 { margin: 2px 0 8px; font: var(--mat-sys-title-large); }
    .small { font-size: 12px; }
    .chunk { border-top: 1px solid var(--mat-sys-outline-variant); padding: 10px 0; }
    .chunk p { line-height: 1.6; white-space: pre-wrap; }
  `,
})
export class CitationPanel {
  readonly svc = inject(CitationService);
  private api = inject(Api);
  readonly chunks = signal<any[]>([]);
  readonly page = signal<any>(null);
  readonly loading = signal(false);
  readonly error = signal('');

  constructor() {
    effect(() => {
      const t = this.svc.target();
      this.chunks.set([]);
      this.page.set(null);
      this.error.set('');
      if (t) void this.load(t);
    });
  }

  private async load(t: CitationTarget) {
    this.loading.set(true);
    try {
      if (t.kind === 'rag') this.chunks.set(await this.api.ragChunks(t.ref));
      else this.page.set(await this.api.page(t.wiki, t.slug));
    } catch (e: any) {
      this.error.set(e?.status === 404 ? (t.kind === 'rag' ? `No indexed paragraph "${t.ref}".` : 'This page does not exist yet.') : errMsg(e));
    } finally {
      this.loading.set(false);
    }
  }
}
