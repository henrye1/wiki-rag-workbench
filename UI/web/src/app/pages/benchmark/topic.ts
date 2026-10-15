import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { Markdown } from '../../shared/markdown';

const SYMBOL: Record<string, string> = { full: '✅', partial: '⚠️', missing: '❌' };

@Component({
  selector: 'app-bench-topic',
  imports: [FormsModule, RouterLink, MatButtonToggleModule, Markdown],
  template: `
    <div class="page">
      <a [routerLink]="['/benchmark', id()]" class="muted">← Run {{ id() }}</a>
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (t(); as t) {
        <h1>{{ t.number }}. {{ t.title }}</h1>
        <div class="muted">{{ t.code }} · {{ t.section }}</div>

        <div class="two">
          <div class="card"><h3>Question asked</h3><pre class="q">{{ t.question }}</pre></div>
          <div class="card"><h3>Human reference <span class="muted">({{ t.reference_label }})</span></h3><p class="ref">{{ t.reference }}</p></div>
        </div>

        <h3>Key points × grades</h3>
        <div class="scroll-x">
          <table class="simple grid">
            <thead>
              <tr><th>Key point</th>
                @for (r of runIds(); track r) { <th class="c">RAG r{{ r }}</th> }
                @for (r of runIds(); track r) { <th class="c">Wiki r{{ r }}</th> }
              </tr>
            </thead>
            <tbody>
              @for (p of t.key_points; track p.id) {
                <tr>
                  <td><b>{{ p.id }}</b> <span class="pill" [class.warn]="p.kind !== 'standard'">{{ p.kind === 'standard' ? 'standard' : 'beyond' }}</span> {{ p.point }}</td>
                  @for (r of runIds(); track r) { <td class="c" [title]="note(r, p.id)">{{ sym(r, 'rag', p.id) }}</td> }
                  @for (r of runIds(); track r) { <td class="c" [title]="note(r, p.id)">{{ sym(r, 'wiki', p.id) }}</td> }
                </tr>
              }
              <tr class="tot"><td>Similarity /10</td>
                @for (r of runIds(); track r) { <td class="c">{{ t.runs[r].systems.rag.similarity }}</td> }
                @for (r of runIds(); track r) { <td class="c">{{ t.runs[r].systems.wiki.similarity }}</td> }
              </tr>
            </tbody>
          </table>
        </div>
        <p class="muted small">✅ full · ⚠️ partial · ❌ missing. Hover a cell for the judge's note.</p>

        <div class="row">
          <h3 class="grow">Answers</h3>
          <mat-button-toggle-group [ngModel]="run()" (ngModelChange)="run.set($event)">
            @for (r of runIds(); track r) { <mat-button-toggle [value]="r">Run {{ r }}</mat-button-toggle> }
          </mat-button-toggle-group>
        </div>
        @if (t.runs[run()]; as r) {
          <div class="card verdict">
            <b>Winner: {{ r.winner }}</b> <span class="muted">(blind labels: A = {{ r.blind_labels.A }}, B = {{ r.blind_labels.B }})</span>
            <p>{{ r.rationale }}</p>
          </div>
          <div class="two">
            @for (sys of ['rag', 'wiki']; track sys) {
              <div class="card">
                <div class="row"><h3 class="grow">{{ sys === 'rag' ? 'RAG' : 'Wiki' }}</h3>
                  <span class="pill">{{ r.systems[sys].similarity }}/10</span><span class="pill">{{ r.systems[sys].coverage }}%</span>
                  <span class="muted small">{{ r.systems[sys].latency_s }} s</span></div>
                @if (r.systems[sys].contradictions.length) {
                  <div class="contra"><b>Contradicts reference:</b><ul>@for (c of r.systems[sys].contradictions; track $index) { <li>{{ c }}</li> }</ul></div>
                }
                <app-md [text]="r.systems[sys].answer" [cites]="sys === 'rag'" />
                <div class="muted small">Sources: {{ r.systems[sys].sources.join(', ') || '—' }}</div>
                @if (sys === 'wiki') { <div class="muted small">Saved answers read: {{ (r.systems[sys].saved_answers_read ?? []).join(', ') || 'none' }}</div> }
              </div>
            }
          </div>
        }
      }
    </div>
  `,
  styles: `
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 16px 0; }
    @media (max-width: 1000px) { .two { grid-template-columns: 1fr; } }
    .q { white-space: pre-wrap; font-family: inherit; margin: 0; } .ref { white-space: pre-wrap; line-height: 1.55; }
    .grid .c { text-align: center; width: 64px; } .tot td { font-weight: 500; }
    .small { font-size: 12px; } .verdict p { margin: 6px 0 0; }
    .contra { background: color-mix(in srgb, #d64545 10%, transparent); border-radius: 8px; padding: 6px 10px; margin-bottom: 8px; }
  `,
})
export class BenchTopic {
  private api = inject(Api);
  readonly id = input.required<string>();
  readonly n = input.required<string>();
  readonly data = signal<any>(null);
  readonly error = signal('');
  readonly run = signal('1');
  readonly t = computed(() => this.data()?.topics?.[this.n()]);
  readonly runIds = computed(() => Object.keys(this.t()?.runs ?? {}).filter((r) => this.t().runs[r].judgement).sort());

  constructor() {
    effect(() => { this.api.get(`/api/bench/runs/${enc(this.id())}`).then((d) => this.data.set(d)).catch((e) => this.error.set(errMsg(e))); });
  }

  sym(run: string, sys: string, pid: string) { return SYMBOL[this.t().runs[run].systems[sys].grades[pid] ?? 'missing']; }
  note(run: string, pid: string) { return this.t().runs[run].point_notes?.[pid] ?? ''; }
}
