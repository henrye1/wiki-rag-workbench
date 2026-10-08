import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { poller } from '../../shared/poll';

@Component({
  selector: 'app-wiki-lint',
  imports: [FormsModule, RouterLink, MatButtonModule, MatButtonToggleModule, MatIconModule, MatProgressBarModule],
  template: `
    <div class="card">
      <div class="row">
        <button mat-flat-button (click)="structural()" [disabled]="busy()"><mat-icon>rule</mat-icon> Structural check (instant)</button>
        <button mat-stroked-button (click)="job(false)" [disabled]="busy()"><mat-icon>psychology</mat-icon> + LLM health check</button>
        <button mat-stroked-button (click)="job(true)" [disabled]="busy()"><mat-icon>auto_fix_high</mat-icon> LLM check + fix</button>
        <mat-button-toggle-group [(ngModel)]="mode">
          <mat-button-toggle value="review">Fixes need review</mat-button-toggle>
          <mat-button-toggle value="auto">Apply fixes</mat-button-toggle>
        </mat-button-toggle-group>
      </div>
      @if (busy()) { <mat-progress-bar mode="indeterminate" /><p class="muted">{{ status() }}</p> }
      @if (error()) { <p class="error">{{ error() }}</p> }
    </div>

    @if (report(); as r) {
      <div class="cards summary">
        @for (k of keys; track k.key) {
          <div class="card"><div class="stat" [class.error]="r[k.key]?.length">{{ r[k.key]?.length ?? 0 }}</div><div class="muted">{{ k.label }}</div></div>
        }
      </div>
      @if (r.broken_links?.length) {
        <h3>Broken links (page doesn’t exist yet)</h3>
        <table class="simple"><tbody>
          @for (b of r.broken_links; track b.slug) {
            <tr><td class="mono">{{ b.slug }}</td><td>linked from @for (s of b.linked_from; track s) { <a [routerLink]="['..', 'pages', s]">{{ s }}</a>{{ $last ? '' : ', ' }} }</td></tr>
          }
        </tbody></table>
      }
      @for (sec of lists; track sec.key) {
        @if (r[sec.key]?.length) {
          <h3>{{ sec.label }}</h3>
          <ul>@for (x of r[sec.key]; track $index) { <li><a [routerLink]="['..', 'pages', x.slug ?? x]">{{ x.slug ?? x }}</a> {{ x.title ? '— ' + x.title : '' }}</li> }</ul>
        }
      }
      @if (r.possible_duplicates?.length) {
        <h3>Possible duplicates</h3>
        <ul>@for (d of r.possible_duplicates; track $index) { <li>{{ d.join(' · ') }}</li> }</ul>
      }
    }

    @if (llm(); as l) {
      <h2>LLM health check</h2>
      @if (l.contradictions.length) {
        <h3>Contradictions</h3>
        <ul>@for (c of l.contradictions; track $index) { <li>{{ c.description }} <span class="muted">({{ c.pages.join(', ') }})</span></li> }</ul>
      }
      @if (l.stale_claims.length) {
        <h3>Stale claims</h3>
        <ul>@for (c of l.stale_claims; track $index) { <li><a [routerLink]="['..', 'pages', c.slug]">{{ c.slug }}</a>: {{ c.description }}</li> }</ul>
      }
      <h3>Missing pages ({{ l.missing_pages.length }})</h3>
      <ul>@for (m of l.missing_pages.slice(0, 40); track m.slug) { <li><b>{{ m.title }}</b> — {{ m.reason }}</li> }</ul>
      <h3>Questions to investigate</h3>
      <ul>@for (q of l.questions; track $index) { <li>{{ q }}</li> }</ul>
      <h3>Sources to find</h3>
      <ul>@for (q of l.sources_to_find; track $index) { <li>{{ q }}</li> }</ul>
    }
    @if (fix(); as f) {
      <div class="card">
        <b>Fixes:</b> {{ f.status }}
        @if (f.changeset_id && f.status === 'pending') { — <a [routerLink]="['..', 'changesets', f.changeset_id]">review {{ f.ops?.length }} change(s) →</a> }
        @if (f.applied) { — applied {{ f.applied.length }} }
      </div>
    }
  `,
  styles: `.summary { margin: 16px 0; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }`,
})
export class WikiLint {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly report = signal<any>(null);
  readonly llm = signal<any>(null);
  readonly fix = signal<any>(null);
  readonly busy = signal(false);
  readonly status = signal('');
  readonly error = signal('');
  mode: 'auto' | 'review' = 'review';
  private jobId = '';
  readonly keys = [
    { key: 'broken_links', label: 'broken links' }, { key: 'orphans', label: 'orphan pages' },
    { key: 'thin_pages', label: 'thin pages' }, { key: 'unsourced_pages', label: 'unsourced pages' },
    { key: 'missing_metadata', label: 'missing summary/tags' }, { key: 'possible_duplicates', label: 'possible duplicates' },
  ];
  readonly lists = [
    { key: 'orphans', label: 'Orphan pages (nothing links to them)' }, { key: 'thin_pages', label: 'Thin pages' },
    { key: 'unsourced_pages', label: 'Unsourced pages' }, { key: 'missing_metadata', label: 'Missing summary or tags' },
  ];
  private poll = poller(async () => {
    const j = await this.api.job(this.jobId);
    this.status.set(`Job ${j.status}${j.progress?.stage ? ' · ' + j.progress.stage : ''}`);
    if (j.status === 'succeeded') {
      this.report.set(j.result.structural);
      this.llm.set(j.result.llm);
      this.fix.set(j.result.fix ?? null);
    }
    if (j.status === 'failed') this.error.set(j.error);
    const running = j.status === 'running' || j.status === 'queued';
    this.busy.set(running);
    return running;
  }, 3000);

  async structural() {
    this.error.set('');
    try {
      const r = await this.api.post(`/api/wiki/wikis/${enc(this.w())}/lint`, {});
      this.report.set(r.structural);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async job(fix: boolean) {
    this.error.set('');
    this.llm.set(null);
    this.fix.set(null);
    try {
      const r = await this.api.post(`/api/wiki/wikis/${enc(this.w())}/lint`, { llm: true, fix, mode: this.mode });
      this.jobId = r.job_id;
      this.busy.set(true);
      this.poll.start();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }
}
