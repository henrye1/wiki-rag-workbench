import { DecimalPipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';
import { Api, errMsg } from '../core/api';

@Component({
  selector: 'app-home',
  imports: [RouterLink, MatButtonModule, MatIconModule, DecimalPipe],
  template: `
    <div class="page">
      <h1>IFRS Workbench</h1>
      <p class="muted">Ask the RAG index and the LLM wiki side by side, manage their documents and pages, and benchmark both against the human-written assessment.</p>
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (s(); as s) {
        <div class="cards">
          <div class="card">
            <h3><span class="dot" [class.up]="s.rag.ok"></span> RAG</h3>
            <div class="stat">{{ chunks(s) | number }}</div>
            <div class="muted">chunks in {{ s.rag.documents.length }} document(s), {{ s.rag.collections.length }} collection(s)</div>
            <div class="row actions"><a mat-button routerLink="/documents">Documents</a><a mat-button routerLink="/bulk">Bulk run</a></div>
          </div>
          <div class="card">
            <h3><span class="dot" [class.up]="s.wiki.ok"></span> Wiki</h3>
            <div class="stat">{{ pages(s) | number }}</div>
            <div class="muted">pages in {{ s.wiki.wikis.length }} wiki(s)</div>
            <div class="row actions">
              @for (w of s.wiki.wikis; track w.slug) { <a mat-button [routerLink]="['/wiki', w.slug]">{{ w.name }}</a> }
              @empty { <a mat-button routerLink="/wiki">Create a wiki</a> }
            </div>
          </div>
          <div class="card">
            <h3><span class="dot" [class.up]="s.benchmark.ok"></span> Benchmark</h3>
            @if (s.benchmark.latest?.summary?.by_system; as b) {
              <div class="stat">{{ b.rag.similarity.mean }} <span class="muted small">vs</span> {{ b.wiki.similarity.mean }}</div>
              <div class="muted">RAG vs Wiki similarity /10 (latest of {{ s.benchmark.runs }} runs)</div>
            } @else { <div class="muted empty">No completed runs yet.</div> }
            <div class="row actions"><a mat-button routerLink="/benchmark">Open</a></div>
          </div>
          <div class="card">
            <h3>Ask</h3>
            <div class="muted">One question, both systems, streamed side by side with clickable citations.</div>
            <div class="row actions"><a mat-flat-button routerLink="/ask"><mat-icon>forum</mat-icon> Ask a question</a></div>
          </div>
        </div>
        @if (!s.rag.ok || !s.wiki.ok) {
          <p class="error">Service down: {{ !s.rag.ok ? 'RAG (' + s.rag.url + ') ' : '' }}{{ !s.wiki.ok ? 'Wiki (' + s.wiki.url + ')' : '' }}. Start it with its run.py.</p>
        }
      }
    </div>
  `,
  styles: `
    .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--mat-sys-error); margin-right: 4px; }
    .dot.up { background: #2e9e4f; }
    .actions { margin-top: 8px; }
    .small { font-size: 14px; }
  `,
})
export class Home {
  private api = inject(Api);
  readonly s = signal<any>(null);
  readonly error = signal('');
  constructor() {
    this.api.get('/api/status').then((s) => this.s.set(s)).catch((e) => this.error.set(errMsg(e)));
  }
  chunks(s: any) { return s.rag.documents.reduce((a: number, d: any) => a + d.chunks, 0); }
  pages(s: any) { return s.wiki.wikis.reduce((a: number, w: any) => a + w.pages, 0); }
}
