import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Api, enc, errMsg } from '../../core/api';
import { Markdown } from '../../shared/markdown';

/** Checking a client statement (the watchdog): one verdict from the schema's list, each clause cited and quoted, recorded
 * as a finding that only a named reviewer closes. Nothing here changes a page. */
@Component({
  selector: 'app-wiki-statements',
  imports: [DatePipe, FormsModule, MatButtonModule, MatButtonToggleModule, MatFormFieldModule, MatIconModule, MatInputModule,
    MatProgressBarModule, Markdown],
  template: `
    <div class="card">
      <mat-form-field class="full" appearance="outline" subscriptSizing="dynamic"><mat-label>Client statement</mat-label>
        <textarea matInput rows="3" [(ngModel)]="statement" placeholder="A statement from a client document, to check against the standard"></textarea>
      </mat-form-field>
      <div class="row">
        <mat-button-toggle-group [(ngModel)]="sources" hideSingleSelectionIndicator>
          <mat-button-toggle value="all">All</mat-button-toggle>
          <mat-button-toggle value="standard" [disabled]="!standardLabel()">{{ standardLabel() || 'Standard only' }}</mat-button-toggle>
        </mat-button-toggle-group>
        <button mat-flat-button (click)="check()" [disabled]="busy() || statement.trim().length < 3"><mat-icon>fact_check</mat-icon> Check statement</button>
      </div>
      @if (busy()) { <mat-progress-bar mode="indeterminate" /> }
      @if (error()) { <p class="error">{{ error() }}</p> }
    </div>

    <h3>Findings</h3>
    @for (f of findings(); track f.id) {
      <div class="card finding">
        <div class="row">
          <span class="pill" [class.warn]="f.status === 'open'" [class.ok]="f.status === 'closed'">{{ f.status }}</span>
          <b class="grow">{{ f.verdict }}</b>
          <span class="muted small">{{ f.created_at | date: 'medium' }}</span>
        </div>
        <p>{{ f.statement }}</p>
        <ul>
          @for (c of f.clauses; track $index) { <li><app-md [text]="c.citation" [wiki]="w()" [cites]="false" /> <q>{{ c.quote }}</q></li> }
        </ul>
        <p class="muted small">{{ f.reasoning }}</p>
        @if (f.check_failures?.length) {
          <p class="warn small">Its checks still find:</p>
          <ul class="small">@for (x of f.check_failures; track $index) { <li>{{ x }}</li> }</ul>
        }
        @if (f.status === 'closed') {
          <p class="small">Closed by <b>{{ f.reviewer }}</b> ({{ f.reviewed_at | date: 'medium' }}): {{ f.decision }}{{ f.note ? ' — ' + f.note : '' }}</p>
        } @else {
          <div class="row">
            <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Reviewer</mat-label><input matInput [(ngModel)]="f._reviewer" /></mat-form-field>
            <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Decision</mat-label><input matInput [(ngModel)]="f._decision" /></mat-form-field>
            <mat-form-field class="grow" appearance="outline" subscriptSizing="dynamic"><mat-label>Note</mat-label><input matInput [(ngModel)]="f._note" /></mat-form-field>
            <button mat-stroked-button (click)="review(f)" [disabled]="busy() || !f._reviewer?.trim() || !f._decision?.trim()">Close</button>
          </div>
        }
      </div>
    } @empty {
      <p class="muted">No client statements checked yet.</p>
    }
  `,
  styles: `.full { width: 100%; } .finding { margin-bottom: 12px; } q { color: var(--mat-sys-on-surface-variant); }`,
})
export class WikiStatements {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly findings = signal<any[]>([]);
  readonly standardLabel = signal<string | null>(null);
  readonly busy = signal(false);
  readonly error = signal('');
  statement = '';
  sources: 'all' | 'standard' = 'all';

  constructor() {
    effect(() => {
      const w = this.w();
      void this.load();
      this.api.wiki(w).then((x) => this.standardLabel.set(x?.answering?.standard_only ?? null));
    });
  }

  private base() { return `/api/wiki/wikis/${enc(this.w())}`; }
  async load() { this.findings.set(await this.api.get(`${this.base()}/findings`)); }

  private async run(fn: () => Promise<any>) {
    this.busy.set(true);
    this.error.set('');
    try {
      await fn();
      await this.load();
    } catch (e) {
      this.error.set(errMsg(e));
    } finally {
      this.busy.set(false);
    }
  }
  check() { return this.run(() => this.api.post(`${this.base()}/statements/check`, { statement: this.statement.trim(), sources: this.sources })); }
  review(f: any) {
    return this.run(() => this.api.post(`${this.base()}/findings/${enc(f.id)}/review`,
      { reviewer: f._reviewer.trim(), decision: f._decision.trim(), note: (f._note ?? '').trim() }));
  }
}
