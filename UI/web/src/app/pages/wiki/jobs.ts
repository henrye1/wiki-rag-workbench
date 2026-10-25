import { DatePipe, JsonPipe } from '@angular/common';
import { Component, effect, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { RouterLink } from '@angular/router';
import { Api, enc } from '../../core/api';
import { poller } from '../../shared/poll';

@Component({
  selector: 'app-wiki-jobs',
  imports: [DatePipe, JsonPipe, RouterLink, MatButtonModule, MatProgressBarModule],
  template: `
    <p class="muted">Ingest and LLM lint run as background jobs (one at a time per wiki). This list refreshes while jobs are active.</p>
    <table class="simple">
      <thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Started</th><th>Result</th></tr></thead>
      <tbody>
        @for (j of jobs(); track j.id) {
          <tr>
            <td><b>{{ j.kind }}</b><div class="muted mono">{{ j.params?.source ?? '' }} {{ j.params?.mode ?? '' }}</div></td>
            <td><span class="pill" [class.ok]="j.status === 'succeeded'" [class.bad]="j.status === 'failed'" [class.warn]="j.status === 'running' || j.status === 'queued'">{{ j.status }}</span></td>
            <td class="prog">
              @if (j.status === 'running' || j.status === 'queued') { <mat-progress-bar mode="indeterminate" /> }
              <span class="muted">{{ stage(j) }}</span>
              @if (j.progress?.failed_sections?.length) { <div class="error">{{ j.progress.failed_sections.length }} section(s) failed</div> }
              @if (j.progress?.failed_pages?.length) { <div class="error" [title]="j.progress.failed_pages[0].error">{{ j.progress.failed_pages.length }} page(s) skipped: @for (f of j.progress.failed_pages; track f.slug) { {{ f.slug }} } </div> }
              @for (c of j.progress?.citations?.corrected ?? []; track c.page) {
                <div class="muted" [title]="c.labels.join(', ')">Citations corrected on {{ c.page }}: @for (m of c.moves; track m.from) { {{ m.count }} from {{ m.from }} to {{ m.to }} }</div>
              }
              @for (f of j.progress?.citations?.flagged ?? []; track $index) {
                <div class="error">Citation to check on {{ f.page }}: {{ f.source }} | {{ f.label }} ({{ f.reason }}){{ f.count > 1 ? ' ×' + f.count : '' }}</div>
              }
              @for (f of j.progress?.saved_answers_to_check ?? []; track f.slug) {
                <div class="error">Saved answer needs checking: {{ f.slug }} ({{ f.paragraphs.join(', ') }} rewritten on {{ f.pages.join(', ') }})</div>
              }
              @for (m of j.progress?.missed_paragraphs ?? []; track m.page) {
                <div class="error" [title]="m.reason">Not written up on {{ m.page }}: {{ m.paragraphs.join(', ') }} ({{ m.reason }})</div>
              }
            </td>
            <td>{{ j.created_at | date: 'short' }}</td>
            <td>
              @if (j.error) { <span class="error">{{ j.error }}</span> }
              @if (j.status === 'succeeded') { <button mat-button (click)="toggle(j.id)">{{ open() === j.id ? 'Hide' : 'Show' }}</button> }
            </td>
          </tr>
          @if (open() === j.id && detail(); as d) {
            <tr><td colspan="5">
              @if (d.result?.changeset_id && d.result?.status === 'pending') {
                <p>Pending changeset: <a [routerLink]="['..', 'changesets', d.result.changeset_id]">review {{ d.result.ops?.length }} change(s) →</a></p>
              }
              @if (d.result?.applied) { <p>Applied {{ d.result.applied.length }} change(s); {{ d.result.conflicts?.length ?? 0 }} conflict(s).</p> }
              @if (d.result?.pages) {
                <p>@for (p of d.result.pages; track p.slug) {
                  @if (d.result.status === 'applied') { <a class="pill" [routerLink]="['..', 'pages', p.slug]">{{ p.op }} {{ p.slug }}</a> }
                  @else { <span class="pill">{{ p.op }} {{ p.slug }}</span> }
                }</p>
              }
              <details><summary class="muted">Raw result</summary><pre class="mono">{{ d.result | json }}</pre></details>
            </td></tr>
          }
        } @empty { <tr><td colspan="5" class="muted empty">No jobs yet.</td></tr> }
      </tbody>
    </table>
  `,
  styles: `.prog { min-width: 180px; } pre { white-space: pre-wrap; max-height: 300px; overflow: auto; }`,
})
export class WikiJobs {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly jobs = signal<any[]>([]);
  readonly open = signal<string | null>(null);
  readonly detail = signal<any>(null);
  private poll = poller(async () => {
    this.jobs.set(await this.api.get(`/api/wiki/wikis/${enc(this.w())}/jobs`));
    return this.jobs().some((j) => j.status === 'running' || j.status === 'queued');
  }, 3000);

  constructor() { effect(() => { this.w(); this.poll.start(); }); }

  stage(j: any) {
    const p = j.progress ?? {};
    return [p.stage, p.sections ? `${p.sections} sections` : '', p.pages ? `${p.pages} pages` : '', p.batches ? `${p.batches} batches` : '']
      .filter(Boolean).join(' · ');
  }

  async toggle(id: string) {
    if (this.open() === id) return this.open.set(null);
    this.open.set(id);
    this.detail.set(await this.api.job(id));
  }
}
