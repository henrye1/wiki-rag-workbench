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

        <h3>Key points × grades <span class="muted small">{{ tagCounts(t) }}</span></h3>
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
                  <td><b>{{ p.id }}</b> <span class="pill" [class.ok]="p.kind === 'standard'" [class.sup]="p.kind === 'supporting'" [class.warn]="p.kind !== 'standard' && p.kind !== 'supporting'">{{ tagLabel[p.kind] ?? p.kind }}</span>
                    {{ p.point }}@if (p.ref && p.kind !== 'beyond_standard') { <span class="muted small"> · {{ p.ref }}</span> }</td>
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
                @if (r.systems[sys].checks; as ck) {
                  <details class="checks">
                    <summary>Answer checks:
                      @for (k of checkKeys; track k) {
                        <span class="pill" [title]="r.systems[sys].metrics?.[k]?.reason ?? ''">{{ checkLabel[k] }}
                          {{ r.systems[sys].metrics?.[k]?.status === 'measured' ? r.systems[sys].metrics[k].value + '%' : 'not measured' }}</span>
                      }
                    </summary>
                    <h4>Questions</h4>
                    <ul>@for (q of ck.questions; track q.id) { <li><b [class]="'st ' + q.status">{{ q.id }} {{ word[q.status] ?? q.status }}</b> — {{ q.note }}</li> }</ul>
                    <h4>Exact-match facts @if (ck.facts_used?.version) { <span class="muted small">(rubric version {{ ck.facts_used.version }}{{ ck.facts_used.approved ? ', approved' : ', not yet approved' }})</span> }</h4>
                    @if (ck.facts.length) {
                      <ul>@for (f of ck.facts; track f.id) { <li><b [class]="'st ' + f.status">{{ f.id }} {{ word[f.status] ?? f.status }}</b>@if (f.kind) { <span class="pill">{{ tagLabel[f.kind] ?? f.kind }}</span> } — {{ f.fact }} <span class="muted">{{ f.note }}</span></li> }</ul>
                    } @else { <p class="muted small">{{ r.systems[sys].metrics?.exact_match?.reason }}</p> }
                    <h4>Citations <span class="muted small">({{ ck.counts.checked }} checked, {{ ck.counts.not_checkable }} not checkable)</span></h4>
                    <ul>@for (c of ck.citations; track $index) {
                      <li><b [class]="'st ' + c.status">{{ c.label || c.source }} {{ word[c.status] ?? c.status }}</b> — <i>{{ c.statement }}</i>
                        <span class="muted"> {{ c.note || c.reason }}</span></li>
                    }</ul>
                    <div class="muted small">Checked by {{ ck.model }}{{ ck.backend === 'claude-code' ? ' (Claude subscription)' : '' }}</div>
                  </details>
                }
                @if (r.systems[sys].context_checks; as cx) {
                  <details class="checks">
                    <summary>Against what it read:
                      @for (k of ['faithfulness', 'context_recall', 'context_recall_standard']; track k) {
                        <span class="pill" [title]="r.systems[sys].metrics?.[k]?.reason ?? ''">{{ k === 'faithfulness' ? 'Faithfulness' : k === 'context_recall' ? 'Context recall' : 'Standard-only context recall' }}
                          {{ r.systems[sys].metrics?.[k]?.status === 'measured' ? r.systems[sys].metrics[k].value + '%' : 'not measured' }}</span>
                      }
                    </summary>
                    @if (cx.note) { <p class="muted small">{{ cx.note }}</p> }
                    <h4>Claims in the answer</h4>
                    <ul>@for (c of cx.claims; track $index) { <li><b [class]="'st ' + c.status">{{ word[c.status] ?? c.status }}</b> — {{ c.claim }} <span class="muted">{{ c.note }}</span></li> }</ul>
                    <h4>Key points in what it read</h4>
                    <ul>@for (k of cx.key_points; track k.id) { <li><b [class]="'st ' + k.status">{{ k.id }} {{ word[k.status] ?? k.status }}</b> <span class="muted">{{ k.note }}</span></li> }</ul>
                    <div class="muted small">Checked by {{ cx.model }}{{ cx.backend === 'claude-code' ? ' (Claude subscription)' : '' }}</div>
                  </details>
                }
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
    .pill.sup { background: color-mix(in srgb, #1565c0 18%, transparent); }
    .checks { margin-top: 10px; font-size: 13px; } .checks summary { cursor: pointer; } .checks .pill { margin-left: 6px; }
    .checks h4 { margin: 10px 0 4px; } .checks ul { margin: 0; padding-left: 18px; } .checks li { margin: 3px 0; }
    .st.answered, .st.stated, .st.supported, .st.backed, .st.present { color: #2e7d32; } .st.partly { color: #ef6c00; }
    .st.not_answered, .st.not_stated, .st.contradicted, .st.not_supported, .st.not_backed, .st.absent { color: #d64545; } .st.not_checkable { color: var(--mat-sys-on-surface-variant); }
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

  readonly tagLabel: Record<string, string> = { standard: 'Standard', supporting: 'Supporting', beyond_standard: 'Beyond standard' };

  tagCounts(t: any) {
    const ps = t.key_points ?? [];
    const n = (k: string) => ps.filter((p: any) => p.kind === k).length;
    return `${ps.length} points: ${n('standard')} Standard · ${n('supporting')} Supporting · ${n('beyond_standard')} Beyond standard`;
  }

  readonly checkKeys = ['completeness', 'exact_match', 'exact_match_standard', 'citation_accuracy'];
  readonly checkLabel: Record<string, string> = { completeness: 'Completeness', exact_match: 'Exact match', exact_match_standard: 'Standard-only exact match', citation_accuracy: 'Citations' };
  readonly word: Record<string, string> = {
    answered: 'answered', partly: 'partly', backed: 'backed', not_backed: 'not backed', present: 'present', absent: 'absent', not_answered: 'not answered', stated: 'stated', contradicted: 'contradicted',
    not_stated: 'not stated', supported: 'supported', not_supported: 'not supported', not_checkable: 'not checkable',
  };

  sym(run: string, sys: string, pid: string) { return SYMBOL[this.t().runs[run].systems[sys].grades[pid] ?? 'missing']; }
  note(run: string, pid: string) { return this.t().runs[run].point_notes?.[pid] ?? ''; }
}
