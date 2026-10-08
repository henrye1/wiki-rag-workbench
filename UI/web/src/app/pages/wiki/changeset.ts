import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { Diff } from '../../shared/diff';
import { Markdown } from '../../shared/markdown';

@Component({
  selector: 'app-wiki-changeset',
  imports: [DatePipe, RouterLink, MatButtonModule, MatExpansionModule, MatIconModule, MatProgressBarModule, Diff, Markdown],
  template: `
    <a routerLink=".." class="muted">← Changesets</a>
    @if (cs(); as c) {
      <div class="row head">
        <div class="grow">
          <h2>{{ c.summary || 'Changeset' }}</h2>
          <div class="muted">{{ c.kind }} · {{ c.ops.length }} change(s) · {{ c.created_at | date: 'medium' }} ·
            <span class="pill" [class.warn]="c.status === 'pending'" [class.ok]="c.status === 'applied'">{{ c.status }}</span></div>
        </div>
        @if (c.status === 'pending') {
          <button mat-stroked-button (click)="discard()" [disabled]="busy()"><mat-icon>delete_sweep</mat-icon> Discard</button>
          <button mat-flat-button (click)="apply(false)" [disabled]="busy()"><mat-icon>done_all</mat-icon> Apply</button>
        }
      </div>
      @if (busy()) { <mat-progress-bar mode="indeterminate" /> }
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (outcome(); as o) {
        <div class="card">
          <b>Applied {{ o.applied?.length ?? 0 }}</b>
          @if (o.conflicts?.length) {
            <p class="error">{{ o.conflicts.length }} conflict(s) skipped (page changed since this changeset was written):</p>
            <ul>@for (x of o.conflicts; track x.slug) { <li>{{ x.slug }}: {{ x.reason }}</li> }</ul>
          }
          @if (o.removed_source) { <p>Source {{ o.removed_source }} removed; it can be re-ingested.</p> }
        </div>
      }
      <mat-accordion multi>
        @for (o of c.ops; track o.id) {
          <mat-expansion-panel>
            <mat-expansion-panel-header>
              <mat-panel-title><span class="pill" [class.ok]="o.op === 'create'" [class.bad]="o.op === 'delete'">{{ o.op }}</span> {{ o.title ?? o.slug }}</mat-panel-title>
              <mat-panel-description>
                {{ o.slug }}
                @if (o.op === 'update' && o.base_version !== o.current_version) { <span class="pill bad">stale: page now v{{ o.current_version }}</span> }
              </mat-panel-description>
            </mat-expansion-panel-header>
            <ng-template matExpansionPanelContent>
              <p class="muted">{{ o.change_note }}</p>
              @if (o.op === 'create') { <app-md [text]="o.content_md" [wiki]="w()" [cites]="false" /> }
              @else { <app-diff [text]="o.diff" /> }
            </ng-template>
          </mat-expansion-panel>
        }
      </mat-accordion>
    }
  `,
  styles: `.head { margin: 8px 0 12px; } h2 { margin: 0; font: var(--mat-sys-title-large); }`,
})
export class WikiChangeset {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly id = input.required<string>();
  readonly cs = signal<any>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly outcome = signal<any>(null);

  constructor() { effect(() => { void this.load(); }); }

  private url() { return `/api/wiki/wikis/${enc(this.w())}/changesets/${enc(this.id())}`; }
  async load() { this.cs.set(await this.api.get(this.url())); }

  private async act(fn: () => Promise<any>) {
    this.busy.set(true);
    this.error.set('');
    try {
      this.outcome.set(await fn());
      await this.load();
    } catch (e) {
      this.error.set(errMsg(e));
    } finally {
      this.busy.set(false);
    }
  }
  apply(force: boolean) { return this.act(() => this.api.post(`${this.url()}/apply`, {}, { force })); }
  discard() { return this.act(() => this.api.post(`${this.url()}/discard`)); }
}
