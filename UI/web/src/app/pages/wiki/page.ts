import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { Diff } from '../../shared/diff';
import { Markdown } from '../../shared/markdown';

@Component({
  selector: 'app-wiki-page',
  imports: [RouterLink, DatePipe, MatButtonModule, MatIconModule, Markdown, Diff],
  template: `
    <a routerLink=".." class="muted">← All pages</a>
    @if (error()) { <p class="error">{{ error() }}</p> }
    @if (page(); as p) {
      <div class="layout">
        <article>
          <h2>{{ p.title }}</h2>
          <div class="muted meta"><span class="pill">{{ p.type }}</span>@for (t of p.tags; track t) { <span class="pill">{{ t }}</span> }
            v{{ p.version }} · updated {{ p.updated_at | date: 'medium' }}</div>
          @if (p.saved_answer) { <p class="muted small">Saved answer: read when answering in addition to the wiki's pages, never as a source.</p> }
          @if (p.needs_checking; as f) {
            @if (f.kind === 'citation_problems') {
              <div class="error flag">
                <b>Needs checking</b> (since {{ f.since | date: 'medium' }}): {{ f.why }}. Ask and the benchmark do not read it
                until it is saved again with no citation problems.
                <ul>@for (x of f.problems ?? []; track $index) { <li>{{ x.kind }}: <code>{{ x.link }}</code> — {{ x.detail }}</li> }</ul>
              </div>
            }
            @let changed = f.kind === 'needs_checking' ? f : f.also;
            @if (changed) {
              <div class="error flag">
                <b>Needs checking</b> (since {{ changed.since | date: 'medium' }}): what the wiki says about
                {{ changed.paragraphs.join(', ') }} changed in {{ changed.pages.join(', ') }} ({{ changed.why }}).
                <button mat-stroked-button (click)="markChecked()">Mark as checked</button>
              </div>
            }
          }
          @if (p.summary) { <p class="muted"><em>{{ p.summary }}</em></p> }
          <app-md [text]="p.content_md" [wiki]="w()" [existing]="existing()" wikiLinks="navigate" [cites]="false" />
          @if (map()?.contents; as c) {
            <div class="card contents">
              <h3>Contents map</h3>
              <p class="muted small">Each section of this document, in its own order, with the pages it informs (sentences citing it).</p>
              @for (x of c.sections; track x.section) {
                <div class="sec"><b>{{ x.section }}</b>
                  <div>@for (g of x.pages; track g.slug) { <a [routerLink]="['..', g.slug]">{{ g.title }}</a> <span class="muted">({{ g.sentences }})</span>@if (!$last) { · } }</div>
                </div>
              }
              <h4>Not used on any page ({{ c.unused.length }})</h4>
              @for (u of c.unused; track u) { <div class="sec">{{ u }}</div> }
              @empty { <div class="muted">None: every section informs at least one page.</div> }
              @if (c.not_in_source.length) {
                <h4>Cited, but not a location in this document ({{ c.not_in_source.length }})</h4>
                @for (x of c.not_in_source; track x.label) {
                  <div class="sec">{{ x.label }} — @for (g of x.pages; track g.slug) { <a [routerLink]="['..', g.slug]">{{ g.title }}</a>@if (!$last) { · } }</div>
                }
              }
            </div>
          }
        </article>
        <aside>
          <div class="card">
            <h3>Linked from ({{ p.backlinks.length }})</h3>
            @for (b of p.backlinks; track b.slug) { <div><a [routerLink]="['..', b.slug]">{{ b.title }}</a></div> }
            @empty { <div class="muted empty">No backlinks</div> }
          </div>
          <div class="card">
            <h3>Sources</h3>
            @for (s of docs(); track s.slug) {
              <div class="doc">
                @if (s.sections.length) {
                  <button class="tog" (click)="toggle(s.slug)" [attr.aria-expanded]="open().has(s.slug)" [title]="open().has(s.slug) ? 'Hide sections' : 'Show the sections this page draws on'">{{ open().has(s.slug) ? '▾' : '▸' }}</button>
                } @else { <span class="tog"></span> }
                <a [routerLink]="['..', s.slug]">{{ s.title }}</a>
                @if (s.kind) { <span class="pill">{{ s.kind }}</span> }
              </div>
              @if (open().has(s.slug)) {
                <ul class="secs">
                  @for (x of s.sections; track x.section) { <li>{{ x.section }} <span class="muted">({{ x.sentences }})</span></li> }
                  @for (x of s.not_in_source; track x.label) { <li class="error">{{ x.label }} <span class="muted">(cited, not in this source)</span></li> }
                </ul>
              }
            }
            @empty { <div class="muted empty">None recorded</div> }
            @if (docs().length) { <div class="muted small">▸ the document's sections this page cites (sentences citing each).</div> }
          </div>
          <div class="card">
            <h3>History</h3>
            @for (v of versions(); track v.version) {
              <div class="ver" [class.sel]="v.version === selected()?.version">
                <button mat-button (click)="showVersion(v.version)">v{{ v.version }}</button>
                <span class="muted small">{{ v.created_at | date: 'short' }} · {{ v.change_note }}</span>
              </div>
            }
          </div>
        </aside>
      </div>
      @if (selected(); as v) {
        <div class="card hist">
          <div class="row">
            <h3 class="grow">Changes from v{{ v.version }} → current (v{{ p.version }})</h3>
            @if (v.version !== p.version) {
              <button mat-stroked-button (click)="revert(v.version)"><mat-icon>history</mat-icon> Revert to v{{ v.version }}</button>
            }
            <button mat-icon-button (click)="selected.set(null)"><mat-icon>close</mat-icon></button>
          </div>
          <app-diff [text]="diff()" />
        </div>
      }
    }
  `,
  styles: `
    .flag { margin: 8px 0; padding: 8px 12px; border: 1px solid var(--mat-sys-error); border-radius: 8px; } .small { font-size: 12px; }
    .layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 24px; }
    @media (max-width: 1000px) { .layout { grid-template-columns: 1fr; } }
    h2 { font: var(--mat-sys-headline-small); margin: 12px 0 4px; }
    aside { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
    .ver { display: flex; align-items: center; gap: 4px; } .ver.sel { background: var(--mat-sys-secondary-container); border-radius: 8px; }
    .small { font-size: 12px; } .hist { margin-top: 16px; }
    .doc { display: flex; align-items: baseline; gap: 4px; } .tog { width: 18px; flex: none; border: 0; background: none; padding: 0; cursor: pointer; color: inherit; }
    .secs { margin: 2px 0 8px 22px; padding-left: 12px; font-size: 13px; } .secs li { margin: 2px 0; }
    .contents { margin-top: 24px; } .contents h4 { margin: 16px 0 4px; } .sec { margin: 6px 0; font-size: 14px; }
  `,
})
export class WikiPage {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly slug = input.required<string>();
  readonly page = signal<any>(null);
  readonly existing = signal<Set<string>>(new Set());
  readonly versions = signal<any[]>([]);
  readonly selected = signal<any>(null);
  readonly diff = signal('');
  readonly error = signal('');
  readonly map = signal<any>(null); // the page's source map (read only): sections cited per document, and a document's contents map
  readonly open = signal<Set<string>>(new Set());

  /** The page's documents: those recorded for it, with the sections it cites; then any it cites that are not recorded. */
  docs() {
    const p = this.page(), m = this.map()?.sources ?? [];
    const of = new Map(m.map((s: any) => [s.slug, s]));
    const rec = (p?.sources ?? []).map((s: any) => ({ ...s, sections: [], not_in_source: [], ...(of.get(s.slug) ?? {}) }));
    return [...rec, ...m.filter((s: any) => !rec.some((r: any) => r.slug === s.slug))];
  }

  toggle(slug: string) {
    const s = new Set(this.open());
    s.has(slug) ? s.delete(slug) : s.add(slug);
    this.open.set(s);
  }

  constructor() {
    effect(() => { void this.load(this.w(), this.slug()); });
  }

  async load(w: string, slug: string) {
    this.error.set('');
    this.selected.set(null);
    try {
      const [p, pages, versions] = await Promise.all([
        this.api.page(w, slug), this.api.pages(w), this.api.get<any[]>(`/api/wiki/wikis/${enc(w)}/pages/${enc(slug)}/versions`),
      ]);
      this.page.set(p);
      this.existing.set(new Set(pages.map((x: any) => x.slug)));
      this.versions.set(versions);
      this.map.set(null);
      this.open.set(new Set());
      this.api.get<any>(`/api/wiki/wikis/${enc(w)}/pages/${enc(slug)}/source-map`).then((m) => this.map.set(m), () => this.map.set(null));
    } catch (e: any) {
      this.page.set(null);
      this.error.set(e?.status === 404 ? `Page “${slug}” does not exist yet (lint with fix can create it).` : errMsg(e));
    }
  }

  async showVersion(v: number) {
    const old = await this.api.get(`/api/wiki/wikis/${enc(this.w())}/pages/${enc(this.slug())}/versions/${v}`);
    this.selected.set(old);
    this.diff.set(unifiedDiff(old.content_md, this.page().content_md));
  }

  async markChecked() {
    try {
      await this.api.delete(`/api/wiki/wikis/${enc(this.w())}/pages/${enc(this.slug())}/needs-checking`);
      await this.load(this.w(), this.slug());
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async revert(v: number) {
    try {
      await this.api.post(`/api/wiki/wikis/${enc(this.w())}/pages/${enc(this.slug())}/revert/${v}`);
      await this.load(this.w(), this.slug());
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }
}

/** Minimal line diff (LCS) rendered in unified style for version comparison. */
export function unifiedDiff(a: string, b: string): string {
  const x = (a ?? '').split('\n');
  const y = (b ?? '').split('\n');
  const n = x.length, m = y.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: string[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { out.push(' ' + x[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push('-' + x[i++]);
    else out.push('+' + y[j++]);
  }
  while (i < n) out.push('-' + x[i++]);
  while (j < m) out.push('+' + y[j++]);
  return out.some((l) => l[0] !== ' ') ? out.join('\n') : '';
}
