import { Component, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { Api, enc, errMsg } from '../../core/api';
import { WikiNames } from '../../core/wiki-names';
import { LABEL } from './systems';

/** A new seed for the topic split and the A/B order (shown, so the same files can be made again). */
function newSeed(): number { return Math.floor(100000 + Math.random() * 900000); }

/** The Expert review (Excel) panel: choose a run, the RAG column the wiki is checked against, the repetition, the
 * number of reviewers and of shared topics; see how the topics are shared out; download the reviewer files and the KEY file in one zip. */
@Component({
  selector: 'app-expert-review',
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatSelectModule],
  template: `
    <div class="card panel">
      <div class="row head">
        <h3 class="grow">Expert review (Excel)</h3>
        <button mat-icon-button type="button" (click)="closed.emit()" aria-label="Close"><mat-icon>close</mat-icon></button>
      </div>
      <p class="muted small">Files for experts to grade the judge's key points themselves, blind: they see only "Answer A" and
        "Answer B", in a random order per topic. The shared topics go to every reviewer, exactly the same in each file; every
        other topic goes to one reviewer. The KEY file says which answer is which:
        keep it yourself and send each reviewer only their own file.</p>
      <div class="row choices">
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="run"><mat-label>Run</mat-label>
          <mat-select [ngModel]="chosen()" (ngModelChange)="pick($event)">
            @for (r of runs(); track r.id) { <mat-option [value]="r.id">{{ r.id }} · {{ names.name(r.wiki) || '—' }}</mat-option> }
          </mat-select></mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Wiki against</mat-label>
          <mat-select [ngModel]="pair()" (ngModelChange)="pair.set($event); fitRep()">
            @for (p of options()?.pairs ?? []; track p) { <mat-option [value]="p">{{ label(p) }}</mat-option> }
          </mat-select></mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="small-field"><mat-label>Repetition</mat-label>
          <mat-select [ngModel]="rep()" (ngModelChange)="rep.set($event)">
            @for (n of options()?.repetitions?.[pair()] ?? []; track n) { <mat-option [value]="n">{{ n }}</mat-option> }
          </mat-select></mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="small-field"><mat-label>Reviewers</mat-label>
          <mat-select [ngModel]="reviewers()" (ngModelChange)="reviewers.set($event)">
            @for (n of [1, 2, 3, 4]; track n) { <mat-option [value]="n">{{ n }}</mat-option> }
          </mat-select></mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="small-field"
                        title="Topics every reviewer gets, the same in each file, to compare the reviewers with each other"><mat-label>Shared topics</mat-label>
          <mat-select [ngModel]="shared()" (ngModelChange)="shared.set($event)">
            @for (n of [0, 1, 2, 3, 4]; track n) { <mat-option [value]="n">{{ n }}</mat-option> }
          </mat-select></mat-form-field>
      </div>
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (plan(); as p) {
        <h4>Topic split</h4>
        <p class="muted small">Seed {{ p.seed }} · shared topics (every reviewer): {{ p.shared.length ? p.shared.join(', ') : 'none' }} ·
          the other topics each to one reviewer, shared out evenly within topics {{ groupText(p) }}, at random.
          <button mat-button type="button" (click)="seed.set(newSeed())"><mat-icon>casino</mat-icon> New seed</button></p>
        <table class="simple split">
          <thead><tr><th>Reviewer</th><th class="n">Topics</th>@for (g of p.groups; track $index) { <th class="n">{{ g[0] }}–{{ g[1] }}</th> }<th class="n">Shared</th><th>Topic numbers</th></tr></thead>
          <tbody>
            @for (r of p.reviewers; track r.n) {
              <tr><td>Reviewer {{ r.n }}</td><td class="n">{{ r.topics.length }}</td>
                @for (c of r.by_group; track $index) { <td class="n">{{ c }}</td> }
                <td class="n">{{ r.topics.length - r.own.length }}</td>
                <td>@for (n of r.topics; track n; let last = $last) { <span [class.shared]="p.shared.includes(n)">{{ n }}</span>{{ last ? '' : ', ' }} }</td></tr>
            }
          </tbody>
        </table>
        @if (p.left_out.length) { <p class="muted small">Left out (repetition {{ p.repetition }} not judged): {{ p.left_out.join(', ') }}</p> }
        <div class="row dl">
          <a mat-flat-button [href]="downloadUrl()" download><mat-icon>download</mat-icon> Download</a>
          <span class="muted small">One zip: {{ files(p) }}</span>
        </div>
      }
    </div>
  `,
  styles: `
    .panel { margin: 0 0 16px; } .head { align-items: center; } .head h3 { margin: 0; }
    .choices { gap: 8px; flex-wrap: wrap; align-items: center; } .run { min-width: 280px; } .small-field { width: 120px; }
    .small { font-size: 12px; } h4 { margin: 14px 0 4px; } .split td.n, .split th.n { text-align: right; }
    .shared { font-weight: 600; text-decoration: underline; }
    .dl { gap: 12px; align-items: center; margin-top: 12px; flex-wrap: wrap; }
  `,
})
export class ExpertReview {
  private api = inject(Api);
  readonly names = inject(WikiNames);
  /** The run on screen: the panel starts on it. */
  readonly run = input.required<string>();
  /** The panel's close button. */
  readonly closed = output<void>();
  readonly runs = signal<any[]>([]);
  readonly chosen = signal('');
  readonly options = signal<any>(null);
  readonly pair = signal('rag_q');
  readonly rep = signal(1);
  readonly reviewers = signal(2);
  readonly shared = signal(4);
  readonly seed = signal(newSeed());
  readonly plan = signal<any>(null);
  readonly error = signal('');
  readonly newSeed = newSeed;

  constructor() {
    this.api.get<any[]>('/api/bench/runs').then((r) => this.runs.set(r)).catch(() => {});
    effect(() => { const id = this.run(); untracked(() => this.pick(id)); });
    effect(() => {
      const id = this.chosen(), opt = this.options();
      const q = { seed: this.seed(), pair: this.pair(), rep: this.rep(), reviewers: this.reviewers(), shared: this.shared() };
      if (!id || !opt || !opt.pairs.includes(q.pair)) return;
      this.api.get(`/api/bench/runs/${enc(id)}/expert-review/plan`, q)
        .then((p) => { this.plan.set(p); this.error.set(''); })
        .catch((e) => { this.plan.set(null); this.error.set(errMsg(e)); });
    });
  }

  /** Choose a run: read what it offers, keeping the choices it has (else its first). */
  async pick(id: string) {
    this.chosen.set(id);
    this.options.set(null);
    this.plan.set(null);
    try {
      const opt = await this.api.get(`/api/bench/runs/${enc(id)}/expert-review/options`);
      if (this.chosen() !== id) return;
      if (!opt.pairs.length) { this.error.set('This run has no judged answers to review.'); return; }
      if (!opt.pairs.includes(this.pair())) this.pair.set(opt.pairs[0]);
      this.options.set(opt);
      this.fitRep();
      this.error.set('');
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  fitRep() {
    const reps: number[] = this.options()?.repetitions?.[this.pair()] ?? [];
    if (reps.length && !reps.includes(this.rep())) this.rep.set(reps[0]);
  }

  label(p: string) { return LABEL[p] ?? p; }
  groupText(p: any) { return p.groups.map((g: number[]) => `${g[0]}–${g[1]}`).join(' and '); }
  files(p: any) {
    const id = this.chosen();
    return [...p.reviewers.map((r: any) => `Expert_Review_${id}_Reviewer${r.n}.xlsx`), `Expert_Review_${id}_KEY.xlsx`].join(', ');
  }
  downloadUrl() {
    const q = new URLSearchParams({ seed: String(this.seed()), pair: this.pair(), rep: String(this.rep()), reviewers: String(this.reviewers()),
                                    shared: String(this.shared()) });
    return `/api/bench/runs/${enc(this.chosen())}/expert-review.zip?${q}`;
  }
}
