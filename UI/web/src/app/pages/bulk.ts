import { Clipboard } from '@angular/cdk/clipboard';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Api, enc, errMsg } from '../core/api';
import { CitationService } from '../shared/citation-service';
import { FileDrop } from '../shared/file-drop';
import { Markdown } from '../shared/markdown';
import { poller } from '../shared/poll';

@Component({
  selector: 'app-bulk',
  imports: [FormsModule, MatButtonModule, MatCheckboxModule, MatExpansionModule, MatFormFieldModule, MatIconModule, MatInputModule,
    MatProgressBarModule, FileDrop, Markdown],
  template: `
    <div class="page">
      <h1>Bulk requirement run (RAG)</h1>
      <div class="card">
        <p class="muted">Runs a query-set file (TOPIC n of N blocks) through the RAG bulk pipeline: retrieval per question, the run rules,
          a self-check revision pass and rule checks. Leave the file empty to use the IFRS 9 query set. About 30–60 s per topic.</p>
        <app-file-drop accept=".txt,.md" label="Optional: drop a query-set file (default: IFRS9_Requirement_Query_Set_BULK_5.txt)" (picked)="file.set($event)" />
        <div class="row opts">
          <mat-form-field appearance="outline" subscriptSizing="dynamic">
            <mat-label>Topics</mat-label>
            <input matInput [(ngModel)]="topics" placeholder="e.g. 1,3,5-7 (empty = all)" />
          </mat-form-field>
          <mat-checkbox [(ngModel)]="revise">Self-check revision pass</mat-checkbox>
          <span class="grow"></span>
          <button mat-flat-button (click)="start()" [disabled]="running()"><mat-icon>play_arrow</mat-icon> Run</button>
        </div>
        @if (error()) { <p class="error">{{ error() }}</p> }
      </div>

      @if (run(); as r) {
        <div class="row head">
          <h3 class="grow">Run {{ r.id }} · {{ r.file }} · topics {{ r.topics.length ? r.topics.join(', ') : 'all' }}</h3>
          <span class="pill" [class.ok]="r.status === 'succeeded'" [class.bad]="r.status === 'failed'">{{ r.status }}</span>
        </div>
        @if (r.status === 'running') { <mat-progress-bar mode="indeterminate" /><p class="muted">Started {{ r.started }}. Results appear when the whole run finishes.</p> }
        @if (r.error) { <p class="error">{{ r.error }}</p> }
        @if (r.result?.topics; as topics) {
          <mat-accordion multi>
            @for (t of topics; track t.topic_no) {
              <mat-expansion-panel>
                <mat-expansion-panel-header>
                  <mat-panel-title>{{ t.topic_no }}. {{ t.title }}</mat-panel-title>
                  <mat-panel-description>
                    @if (t.error) { <span class="pill bad">error</span> }
                    @else {
                      {{ t.word_count }} / ~{{ t.word_guide }} words ·
                      <span class="pill" [class.ok]="!t.issues?.length" [class.warn]="t.issues?.length">{{ t.issues?.length ? t.issues.length + ' issue(s)' : 'checks pass' }}</span>
                    }
                  </mat-panel-description>
                </mat-expansion-panel-header>
                @if (t.error) { <p class="error">{{ t.error }}</p> } @else {
                  @for (i of t.issues; track i) { <p class="warn-line">⚠ {{ i }}</p> }
                  <div class="row"><span class="grow"></span>
                    <button mat-button (click)="copy(t.answer_markdown)"><mat-icon>content_copy</mat-icon> Copy markdown</button></div>
                  <app-md [text]="t.answer_markdown" [cites]="false" />
                  <div class="sources"><span class="muted">Cited paragraphs:</span>
                    @for (c of t.citations; track c.chunk_id) { <button class="chip" (click)="cites.openRag(c.para_ref ?? c.chunk_id)">{{ c.para_ref ?? c.chunk_id }}</button> }
                  </div>
                }
              </mat-expansion-panel>
            }
          </mat-accordion>
        }
      }

      @if (history().length > 1) {
        <h3>Earlier runs (this session)</h3>
        @for (h of history(); track h.id) {
          <button mat-button (click)="open(h.id)">{{ h.id }} · {{ h.status }} · {{ h.started }}</button>
        }
      }
    </div>
  `,
  styles: `
    .opts { margin-top: 12px; }
    .head { margin-top: 20px; }
    .warn-line { color: #a15c00; margin: 4px 0; }
    .sources { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .chip { border: 1px solid var(--mat-sys-outline-variant); background: var(--mat-sys-surface-container); color: inherit;
            border-radius: 12px; padding: 2px 10px; cursor: pointer; font-size: 12.5px; }
  `,
})
export class Bulk {
  private api = inject(Api);
  private clipboard = inject(Clipboard);
  readonly cites = inject(CitationService);
  topics = '1';
  revise = true;
  readonly file = signal<File | null>(null);
  readonly run = signal<any>(null);
  readonly history = signal<any[]>([]);
  readonly running = signal(false);
  readonly error = signal('');
  private poll = poller(async () => {
    const r = await this.api.get(`/api/bulk/${enc(this.run().id)}`);
    this.run.set(r);
    this.running.set(r.status === 'running');
    if (!this.running()) this.history.set(await this.api.get('/api/bulk'));
    return this.running();
  }, 4000);

  constructor() {
    this.api.get<any[]>('/api/bulk').then((h) => {
      this.history.set(h);
      if (h[0]) void this.open(h[0].id);
    });
  }

  async start() {
    this.error.set('');
    try {
      const fields = { topics: this.topics, revise: String(this.revise) };
      const r = this.file()
        ? await this.api.upload('/api/bulk', this.file()!, undefined, fields)
        : await this.api.post('/api/bulk', toForm(fields));
      this.running.set(true);
      await this.open(r.id);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async open(id: string) {
    this.run.set(await this.api.get(`/api/bulk/${enc(id)}`));
    this.running.set(this.run().status === 'running');
    if (this.running()) this.poll.start();
  }

  copy(md: string) { this.clipboard.copy(md); }
}

function toForm(fields: Record<string, string>) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  return fd;
}
