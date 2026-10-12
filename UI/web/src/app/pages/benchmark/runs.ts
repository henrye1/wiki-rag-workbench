import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Router, RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { FileDrop } from '../../shared/file-drop';
import { poller } from '../../shared/poll';

@Component({
  selector: 'app-bench-runs',
  imports: [FormsModule, RouterLink, DatePipe, MatButtonModule, MatCheckboxModule, MatFormFieldModule, MatIconModule, MatInputModule, MatProgressBarModule, FileDrop],
  template: `
    <div class="page">
      <h1>Benchmark</h1>
      <p class="muted">RAG and Wiki answer each topic of the IFRS 9 query set; Claude grades both blind against a human-written IFRS 9 assessment
        (key-point checklist, 0–10 similarity, winner).</p>
      <div class="card">
        <h3>New run</h3>
        <div class="files">
          <app-file-drop accept=".docx" label="Reference assessment (.docx)" (picked)="reference = $event" />
          <app-file-drop accept=".txt" label="Query set (.txt)" (picked)="querySet = $event" />
        </div>
        <p class="muted small">Leave a file empty to reuse the one from the last run. Files are stored with the run in the database.</p>
        <div class="row">
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="wiki"><mat-label>Wiki</mat-label>
            <input matInput [(ngModel)]="wiki" /></mat-form-field>
          <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Topics</mat-label>
            <input matInput [(ngModel)]="topics" placeholder="e.g. 2 or 1-5 (empty = all 26)" /></mat-form-field>
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="runs"><mat-label>Runs</mat-label>
            <input matInput type="number" min="1" max="10" [(ngModel)]="runs" /></mat-form-field>
          <button mat-flat-button (click)="start()" [disabled]="active()"><mat-icon>play_arrow</mat-icon> Start</button>
          <span class="muted small">Full run ≈ 26 × runs × (2 system answers + 1 Claude judgement). Needs RAG and the wiki populated.</span>
        </div>
        @if (active(); as a) {
          <div class="progress">
            <div class="row"><b class="grow">Running {{ a.id }}</b><span>{{ a.done }} / {{ a.expected ?? '?' }} judged</span></div>
            <mat-progress-bar mode="determinate" [value]="a.expected ? (100 * a.done) / a.expected : 0" />
            <pre class="mono log">{{ a.log.join('\n') }}</pre>
          </div>
        }
        @if (error()) { <p class="error">{{ error() }}</p> }
      </div>

      <div class="row head">
        <h3 class="grow">Runs</h3>
        @if (selected().length === 2) { <button mat-stroked-button (click)="compare()"><mat-icon>compare_arrows</mat-icon> Compare selected</button> }
        @else { <span class="muted small">Tick two runs to compare</span> }
      </div>
      <table class="simple">
        <thead><tr><th></th><th>Run</th><th>Topics × runs</th><th>RAG sim / cov</th><th>Wiki sim / cov</th><th>Wins (rag / wiki / tie)</th><th>Status</th><th></th></tr></thead>
        <tbody>
          @for (r of list(); track r.id) {
            <tr>
              <td><mat-checkbox [checked]="selected().includes(r.id)" (change)="toggle(r.id)" /></td>
              <td><a [routerLink]="[r.id]">{{ r.id }}</a><div class="muted small">{{ r.started | date: 'medium' }}</div></td>
              <td>{{ r.topics }} × {{ r.runs }}</td>
              @if (r.summary?.by_system; as b) {
                <td><b>{{ b.rag.similarity.mean }}</b> / {{ b.rag.coverage.mean }}%</td>
                <td><b>{{ b.wiki.similarity.mean }}</b> / {{ b.wiki.coverage.mean }}%</td>
                <td>{{ r.summary.wins_by_run.rag }} / {{ r.summary.wins_by_run.wiki }} / {{ r.summary.wins_by_run.tie }}</td>
              } @else { <td colspan="3" class="muted">—</td> }
              <td><span class="pill" [class.ok]="r.progress.status === 'finished'" [class.warn]="r.progress.status === 'running'"
                        [class.bad]="r.progress.status === 'failed' || r.progress.status === 'interrupted'">{{ r.progress.status }}</span></td>
              <td class="actions">
                @if (r.progress.status === 'interrupted' || r.progress.status === 'failed' || r.progress.status === 'queued') {
                  <button mat-icon-button title="Resume" (click)="resume(r.id)" [disabled]="active()"><mat-icon>replay</mat-icon></button>
                }
                @if (r.progress.status !== 'running') {
                  <button mat-icon-button title="Delete run" (click)="remove(r.id)"><mat-icon>delete</mat-icon></button>
                }
              </td>
            </tr>
          } @empty { <tr><td colspan="8" class="muted">No runs yet.</td></tr> }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    .runs { width: 90px; } .wiki { width: 140px; } .actions { white-space: nowrap; }
    .files { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; } .small { font-size: 12px; } .head { margin-top: 20px; }
    .progress { margin-top: 12px; } .log { max-height: 160px; overflow: auto; white-space: pre-wrap; margin: 8px 0 0; }
  `,
})
export class BenchRuns {
  private api = inject(Api);
  private router = inject(Router);
  readonly list = signal<any[]>([]);
  readonly active = signal<any>(null);
  readonly selected = signal<string[]>([]);
  readonly error = signal('');
  topics = '2';
  runs = 1;
  wiki = 'ifrs9';
  reference: File | null = null;
  querySet: File | null = null;
  private poll = poller(async () => {
    const a = this.active();
    if (!a) return false;
    try {
      this.active.set({ id: a.id, ...(await this.api.get(`/api/bench/runs/${enc(a.id)}/status`)) });
    } catch { /* results file not written yet */ }
    const running = this.active().status === 'running' || this.active().status === undefined;
    if (!running) { this.active.set(null); await this.load(); }
    return running;
  }, 3000);

  constructor() { void this.load(true); }

  async load(resume = false) {
    this.list.set(await this.api.get('/api/bench/runs'));
    const running = this.list().find((r) => r.progress.status === 'running');
    if (resume && running) {
      this.active.set({ id: running.id, done: running.progress.done, expected: running.progress.expected, log: [] });
      this.poll.start();
    }
  }

  async start() {
    this.error.set('');
    try {
      const fd = new FormData();
      if (this.reference) fd.append('reference', this.reference, this.reference.name);
      if (this.querySet) fd.append('query_set', this.querySet, this.querySet.name);
      fd.append('topics', this.topics);
      fd.append('runs', String(this.runs));
      fd.append('wiki', this.wiki);
      const r = await this.api.post('/api/bench/runs', fd);
      this.watch(r.id);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async resume(id: string) {
    this.error.set('');
    try {
      await this.api.post(`/api/bench/runs/${enc(id)}/resume`);
      this.watch(id);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async remove(id: string) {
    if (!confirm(`Delete benchmark run ${id}?`)) return;
    try {
      await this.api.delete(`/api/bench/runs/${enc(id)}`);
      this.selected.update((s) => s.filter((x) => x !== id));
      await this.load();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  private watch(id: string) {
    this.active.set({ id, done: 0, expected: null, log: [], status: 'running' });
    setTimeout(() => this.poll.start(), 1500);
  }

  toggle(id: string) {
    this.selected.update((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id].slice(-2)));
  }

  compare() {
    const [a, b] = [...this.selected()].sort();
    this.router.navigate(['/benchmark/compare'], { queryParams: { a, b } });
  }
}
