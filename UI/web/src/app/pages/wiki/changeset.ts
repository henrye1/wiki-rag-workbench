import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { FormsModule } from '@angular/forms';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { Diff } from '../../shared/diff';
import { Markdown } from '../../shared/markdown';

@Component({
  selector: 'app-wiki-changeset',
  imports: [DatePipe, FormsModule, RouterLink, MatButtonModule, MatExpansionModule, MatFormFieldModule, MatIconModule, MatInputModule,
    MatProgressBarModule, Diff, Markdown],
  template: `
    <a routerLink=".." class="muted">← Changesets</a>
    @if (cs(); as c) {
      <div class="row head">
        <div class="grow">
          <h2>{{ c.summary || 'Changeset' }}</h2>
          <div class="muted">{{ c.kind }} · {{ c.ops.length }} change(s) · {{ c.created_at | date: 'medium' }} ·
            <span class="pill" [class.warn]="c.status === 'pending'" [class.ok]="c.status === 'applied'">{{ c.status }}</span>
            @if (c.reviewer) { · by {{ c.reviewer }}{{ c.reviewed_at ? ', ' : '' }}{{ c.reviewed_at | date: 'medium' }} }</div>
        </div>
        @if (c.status === 'pending') {
          <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Reviewer</mat-label>
            <input matInput [(ngModel)]="reviewer" [required]="failingPages(c).length > 0" /></mat-form-field>
          <button mat-stroked-button (click)="discard()" [disabled]="busy()"><mat-icon>delete_sweep</mat-icon> Discard</button>
          @if (c.rerun) {
            <button mat-stroked-button (click)="rerun()" [disabled]="busy()"
                    title="Discard this changeset and write the upload again against the wiki as it is now, from the passages saved at upload">
              <mat-icon>replay</mat-icon> Re-run against the current wiki</button>
          }
          <button mat-flat-button (click)="apply(false)" [disabled]="busy() || stale(c).length > 0 || (failingPages(c).length > 0 && !reviewer.trim())"
                  [title]="stale(c).length ? 'Pages it changes have changed since it was written' : failingPages(c).length ? 'A held upload is applied only by a named reviewer' : ''"><mat-icon>done_all</mat-icon> Apply</button>
        }
      </div>
      @if (busy()) { <mat-progress-bar mode="indeterminate" /> }
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (rerunJob(); as j) {
        <div class="card">Re-run queued as job {{ j.job_id.slice(0, 8) }} ({{ j.mode }} mode); this changeset was discarded.
          <a [routerLink]="['..', 'jobs']">Follow it on the Jobs tab →</a></div>
      }
      @if (c.status === 'pending' && stale(c).length) {
        <div class="card">
          <b>Written against an older wiki: {{ stale(c).length }} page(s) it changes have changed since.</b>
          <span class="muted"> Applying it would lose those changes, so Apply is refused.
            @if (c.rerun) { Re-run it against the current wiki instead. } @else { Discard it and upload the file again. }</span>
          <ul>@for (x of stale(c); track x.slug) { <li>{{ x.slug }}: {{ x.reason }}</li> }</ul>
          <button mat-button (click)="applyAnyway(c)" [disabled]="busy() || (failingPages(c).length > 0 && !reviewer.trim())">
            <mat-icon>warning</mat-icon> Apply anyway (overwrite these pages)</button>
        </div>
      }
      @if (failingPages(c).length) {
        <div class="card">
          <b>Held for review: these pages still fail the schema's checks.</b>
          <span class="muted"> Applying keeps each failure as a flag on its page; it is applied only by a named reviewer.</span>
          @for (p of failingPages(c); track p) {
            <p><b>{{ p }}</b></p>
            <ul>@for (f of c.check_failures[p]; track $index) { <li class="small">{{ f }}</li> }</ul>
          }
        </div>
      }
      @if (outcome(); as o) {
        <div class="card">
          <b>Applied {{ o.applied?.length ?? 0 }}</b>
          @if (o.overwritten?.length) {
            <p class="error">Applied anyway: {{ o.overwritten.length }} page(s) changed since it was written were overwritten:</p>
            <ul>@for (x of o.overwritten; track x.slug) { <li>{{ x.slug }}: {{ x.reason }}</li> }</ul>
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
                @if (staleOp(o.slug); as why) { <span class="pill bad" [title]="why">stale: {{ why }}</span> }
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
  failingPages(c: any): string[] { return Object.keys(c?.check_failures ?? {}); }
  stale(c: any): any[] { return c?.stale ?? []; }
  staleOp(slug: string): string { return this.stale(this.cs()).find((x) => x.slug === slug)?.reason ?? ''; }
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly id = input.required<string>();
  readonly cs = signal<any>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly outcome = signal<any>(null);
  readonly rerunJob = signal<any>(null);
  reviewer = '';

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
  apply(force: boolean) { return this.act(() => this.api.post(`${this.url()}/apply`, {}, { force, reviewer: this.reviewer.trim() })); }
  applyAnyway(c: any) {
    const pages = this.stale(c).map((x: any) => x.slug).join('\n');
    if (!confirm(`Apply anyway? These pages changed since this changeset was written; what changed on them will be overwritten:\n\n${pages}`)) return;
    return this.apply(true);
  }
  rerun() {
    return this.act(async () => {
      this.rerunJob.set(await this.api.post(`${this.url()}/rerun`, {}, { reviewer: this.reviewer.trim() }));
      return null;
    });
  }
  discard() { return this.act(() => this.api.post(`${this.url()}/discard`, {}, { reviewer: this.reviewer.trim() })); }
}
