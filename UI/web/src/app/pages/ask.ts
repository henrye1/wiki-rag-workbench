import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../core/api';
import { postSse } from '../core/sse';
import { CitationService } from '../shared/citation-service';
import { Markdown } from '../shared/markdown';

interface Pane {
  text: string;
  running: boolean;
  error: string;
  sources: any[];
  ms: number | null;
  saved?: any;
}

const emptyPane = (): Pane => ({ text: '', running: false, error: '', sources: [], ms: null });

@Component({
  selector: 'app-ask',
  imports: [FormsModule, RouterLink, MatFormFieldModule, MatInputModule, MatButtonModule, MatCheckboxModule, MatSelectModule,
    MatIconModule, MatProgressBarModule, Markdown],
  template: `
    <div class="page">
      <h1>Ask</h1>
      <mat-form-field class="full" appearance="outline">
        <mat-label>Question</mat-label>
        <textarea matInput rows="3" [(ngModel)]="question" (keydown.control.enter)="ask()"
                  placeholder="e.g. When must lifetime expected credit losses be recognised?"></textarea>
        <mat-hint>Ctrl+Enter to ask</mat-hint>
      </mat-form-field>
      <div class="row">
        <mat-checkbox [(ngModel)]="useRag">RAG</mat-checkbox>
        <mat-checkbox [(ngModel)]="useWiki">Wiki</mat-checkbox>
        <mat-form-field appearance="outline" class="wiki-select" subscriptSizing="dynamic">
          <mat-label>Wiki</mat-label>
          <mat-select [(ngModel)]="wiki" [disabled]="!useWiki">
            @for (w of wikis(); track w.slug) { <mat-option [value]="w.slug">{{ w.name }}</mat-option> }
          </mat-select>
        </mat-form-field>
        <span class="grow"></span>
        @if (rag().running || wikiPane().running) { <button mat-stroked-button (click)="stop()"><mat-icon>stop</mat-icon> Stop</button> }
        <button mat-flat-button (click)="ask()" [disabled]="!question.trim() || (!useRag && !useWiki)"><mat-icon>send</mat-icon> Ask</button>
      </div>

      <div class="panes" [class.single]="!(shownRag && shownWiki)">
        @if (shownRag) {
          <section class="pane card">
            <header class="row"><h3 class="grow">RAG</h3>@if (rag().ms) { <span class="muted">{{ rag().ms! / 1000 }} s</span> }</header>
            @if (rag().running) { <mat-progress-bar mode="indeterminate" /> }
            @if (rag().error) { <p class="error">{{ rag().error }}</p> }
            <app-md [text]="rag().text" />
            @if (rag().sources.length) {
              <div class="sources"><span class="muted">Sources:</span>
                @for (c of rag().sources; track c.chunk_id) {
                  <button class="chip" (click)="cites.openRag(c.para_ref ?? c.chunk_id)" [title]="c.snippet">{{ c.para_ref ?? c.chunk_id }}</button>
                }
              </div>
            }
          </section>
        }
        @if (shownWiki) {
          <section class="pane card">
            <header class="row"><h3 class="grow">Wiki · {{ askedWiki }}</h3>@if (wikiPane().ms) { <span class="muted">{{ wikiPane().ms! / 1000 }} s</span> }</header>
            @if (wikiPane().running) { <mat-progress-bar mode="indeterminate" /> }
            @if (wikiPane().error) { <p class="error">{{ wikiPane().error }}</p> }
            <app-md [text]="wikiPane().text" [wiki]="askedWiki" [titles]="titles()" [cites]="false" />
            @if (wikiPane().sources.length) {
              <div class="sources"><span class="muted">Pages read:</span>
                @for (p of wikiPane().sources; track p.slug) {
                  <button class="chip" [class.dim]="!p.cited" (click)="cites.openWiki(askedWiki, p.slug)">{{ p.title }}</button>
                }
              </div>
            }
            @if (!wikiPane().running && wikiPane().text && !wikiPane().error) {
              <div class="row save">
                @if (wikiPane().saved; as s) {
                  <span class="muted">Saved as <a [routerLink]="['/wiki', askedWiki, s.status === 'applied' ? 'pages' : 'changesets', s.status === 'applied' ? s.slug : s.changeset_id]">{{ s.slug }}</a> ({{ s.status }})</span>
                } @else {
                  <button mat-stroked-button (click)="save()" [disabled]="saving()"><mat-icon>bookmark_add</mat-icon> Save answer as wiki page</button>
                  <span class="muted small">re-answers with save=true, then files a synthesis page</span>
                }
              </div>
            }
          </section>
        }
      </div>
    </div>
  `,
  styles: `
    .wiki-select { width: 220px; }
    .panes { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }
    .panes.single { grid-template-columns: 1fr; }
    @media (max-width: 1000px) { .panes { grid-template-columns: 1fr; } }
    .pane h3 { margin: 0; }
    .sources { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .chip { border: 1px solid var(--mat-sys-outline-variant); background: var(--mat-sys-surface-container); color: inherit;
            border-radius: 12px; padding: 2px 10px; cursor: pointer; font-size: 12.5px; }
    .chip.dim { opacity: .6; }
    .save { margin-top: 12px; }
    .small { font-size: 12px; }
  `,
})
export class Ask {
  private api = inject(Api);
  readonly cites = inject(CitationService);
  question = '';
  useRag = true;
  useWiki = true;
  wiki = '';
  askedWiki = '';
  shownRag = false;
  shownWiki = false;
  readonly wikis = signal<any[]>([]);
  readonly rag = signal<Pane>(emptyPane());
  readonly wikiPane = signal<Pane>(emptyPane());
  readonly saving = signal(false);
  readonly titles = computed(() => new Map<string, string>(this.wikiPane().sources.map((p: any) => [p.slug, p.title])));
  private abort?: AbortController;

  constructor() {
    this.api.wikis().then((w) => {
      this.wikis.set(w);
      this.wiki ||= w[0]?.slug ?? '';
    });
  }

  ask() {
    const q = this.question.trim();
    if (!q) return;
    this.stop();
    this.abort = new AbortController();
    this.shownRag = this.useRag;
    this.shownWiki = this.useWiki && !!this.wiki;
    this.askedWiki = this.wiki;
    if (this.shownRag) void this.stream('/api/rag/query/stream', this.rag, 'citations', q);
    if (this.shownWiki) void this.stream(`/api/wiki/wikis/${enc(this.wiki)}/query/stream`, this.wikiPane, 'pages', q);
  }

  stop() { this.abort?.abort(); }

  private async stream(url: string, pane: ReturnType<typeof signal<Pane>>, sourcesEvent: string, q: string) {
    const t0 = performance.now();
    pane.set({ ...emptyPane(), running: true });
    try {
      for await (const ev of postSse(url, { question: q }, this.abort!.signal)) {
        if (ev.event === 'token') pane.update((p) => ({ ...p, text: p.text + JSON.parse(ev.data) }));
        else if (ev.event === sourcesEvent) pane.update((p) => ({ ...p, sources: JSON.parse(ev.data) }));
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') pane.update((p) => ({ ...p, error: errMsg(e) }));
    } finally {
      pane.update((p) => ({ ...p, running: false, ms: Math.round(performance.now() - t0) }));
    }
  }

  async save() {
    this.saving.set(true);
    try {
      const r = await this.api.post(`/api/wiki/wikis/${enc(this.askedWiki)}/query`, { question: this.question.trim(), save: true, mode: 'auto' });
      this.wikiPane.update((p) => ({ ...p, saved: r.saved }));
    } catch (e) {
      this.wikiPane.update((p) => ({ ...p, error: errMsg(e) }));
    } finally {
      this.saving.set(false);
    }
  }
}
