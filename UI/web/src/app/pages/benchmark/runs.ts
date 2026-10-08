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
import { poller } from '../../shared/poll';

@Component({
  selector: 'app-bench-runs',
  imports: [FormsModule, RouterLink, DatePipe, MatButtonModule, MatCheckboxModule, MatFormFieldModule, MatIconModule, MatInputModule, MatProgressBarModule],
  template: `
    <div class="page">
      <h1>Benchmark</h1>
      <p class="muted">RAG and Wiki answer each topic of the IFRS 9 query set; Claude grades both blind against a human-written IFRS 9 assessment
        (key-point checklist, 0–10 similarity, winner).</p>
      <div class="card">
        <h3>New run</h3>
        <div class="row">
          <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Topics</mat-label>
            <input matInput [(ngModel)]="topics" placeholder="e.g. 2 or 1-5 (empty = all 26)" /></mat-form-field>
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="runs"><mat-label>Runs</mat-label>
            <input matInput type="number" min="1" max="10" [(ngModel)]="runs" /></mat-form-field>
          <button mat-flat-button (click)="start()" [disabled]="active()"><mat-icon>play_arrow</mat-icon> Start</button>
          <span class="muted small">Full run ≈ 26 × runs × (2 system answers + 1 Claude judgement). Needs RAG and Wiki running.</span>
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
        <thead><tr><th></th><th>Run</th><th>Topics × runs</th><th>RAG sim / cov</th><th>Wiki sim / cov</th><th>Wins (rag / wiki / tie)</th><th>Status</th></tr></thead>
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
                        [class.bad]="r.progress.status === 'failed'">{{ r.progress.status }}</span></td>
            </tr>
          } @empty { <tr><td colspan="7" class="muted">No runs yet.</td></tr> }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    .runs { width: 90px; } .small { font-size: 12px; } .head { margin-top: 20px; }
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
      const r = await this.api.post('/api/bench/runs', { topics: this.topics, runs: this.runs });
      this.active.set({ id: r.id, done: 0, expected: null, log: [], status: 'running' });
      setTimeout(() => this.poll.start(), 1500);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  toggle(id: string) {
    this.selected.update((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id].slice(-2)));
  }

  compare() {
    const [a, b] = [...this.selected()].sort();
    this.router.navigate(['/benchmark/compare'], { queryParams: { a, b } });
  }
}
