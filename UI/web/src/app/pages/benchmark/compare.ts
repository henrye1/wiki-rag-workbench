import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { LABEL } from './systems';

/** The columns compared: each RAG column, and the wiki as graded in each RAG column's pair (the judge compares two
 *  answers at a time, so the wiki has a score per pair). Each reads a topic's aggregate as the run stored it. */
const COLUMNS = [
  { key: 'rag', label: LABEL['rag'], sim: (t: any) => t?.aggregate?.rag?.similarity?.mean },
  { key: 'wiki', label: `${LABEL['wiki']} (vs ${LABEL['rag']})`, sim: (t: any) => t?.aggregate?.wiki?.similarity?.mean },
  { key: 'rag_q', label: LABEL['rag_q'], sim: (t: any) => t?.aggregate?.rag_q?.similarity?.mean },
  { key: 'wiki_q', label: `${LABEL['wiki']} (vs ${LABEL['rag_q']})`, sim: (t: any) => t?.aggregate?.pairs?.rag_q?.wiki?.similarity?.mean },
];

@Component({
  selector: 'app-bench-compare',
  imports: [RouterLink, DecimalPipe],
  template: `
    <div class="page">
      <a routerLink="/benchmark" class="muted">← Runs</a>
      <h1>Compare {{ a() }} → {{ b() }}</h1>
      @if (runA()?.compared && runB()?.compared) {
        <p>A: <b>{{ runA().compared.rag_collection || '—' }}</b> vs <b>{{ runA().compared.wiki || '—' }}</b>, Sources <span class="pill">{{ label(runA().compared.sources) }}</span>
          · B: <b>{{ runB().compared.rag_collection || '—' }}</b> vs <b>{{ runB().compared.wiki || '—' }}</b>, Sources <span class="pill">{{ label(runB().compared.sources) }}</span></p>
        @if (runA().compared.sources !== runB().compared.sources) {
          <p class="warn"><b>Different sources:</b> run A used {{ label(runA().compared.sources) }}, run B {{ label(runB().compared.sources) }}. Differences may come from the setting, not the systems.</p>
        }
      }
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (rows().length) {
        <div class="cards">
          @for (s of totals(); track s.key) {
            <div class="card"><h3>{{ s.label }} similarity</h3>
              <div class="stat">{{ s.a ?? '—' }} → {{ s.b ?? '—' }}</div>
              <div [class.pos]="s.delta > 0" [class.neg]="s.delta < 0">{{ s.delta > 0 ? '+' : '' }}{{ s.delta | number: '1.2-2' }}</div></div>
          }
        </div>
        <p class="muted">Topics present in both runs. Δ = run B − run A (mean similarity /10).</p>
        <div class="scroll-x">
          <table class="simple">
            <thead><tr><th>#</th><th>Topic</th>
              @for (c of columns; track c.key) { <th>{{ c.label }} A</th><th>B</th><th>Δ</th> }
            </tr></thead>
            <tbody>
              @for (r of rows(); track r.n) {
                <tr>
                  <td>{{ r.n }}</td><td>{{ r.title }}</td>
                  @for (v of r.cells; track v.key) {
                    <td>{{ v.a | number: '1.1-1' }}</td><td>{{ v.b | number: '1.1-1' }}</td>
                    <td [class.pos]="(v.d ?? 0) > 0" [class.neg]="(v.d ?? 0) < 0">{{ v.d === null ? '—' : (v.d > 0 ? '+' : '') }}{{ v.d | number: '1.1-1' }}</td>
                  }
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else if (loaded()) { <p class="muted">No topics in common.</p> }
    </div>
  `,
  styles: `.pos { color: #2e7d32; font-weight: 500; } .neg { color: #c62828; font-weight: 500; }`,
})
export class BenchCompare {
  private api = inject(Api);
  readonly a = input.required<string>();
  readonly b = input.required<string>();
  readonly runA = signal<any>(null);
  readonly runB = signal<any>(null);
  readonly loaded = signal(false);
  readonly error = signal('');
  label(s: string | null) { return s === 'standard' ? 'Standard only' : s === 'all' ? 'All' : '—'; }

  readonly columns = COLUMNS;

  readonly rows = computed(() => {
    const A = this.runA(), B = this.runB();
    if (!A || !B) return [];
    return Object.keys(A.topics).filter((n) => B.topics[n]?.aggregate && A.topics[n]?.aggregate).sort((x, y) => +x - +y).map((n) => {
      const ta = A.topics[n], tb = B.topics[n];
      const cells = COLUMNS.map((c) => {
        const a = c.sim(ta) ?? null, b = c.sim(tb) ?? null;
        return { key: c.key, a, b, d: a !== null && b !== null ? b - a : null };
      });
      return { n, title: ta.title, cells };
    });
  });
  /** Each column's mean over the topics both runs scored it on. */
  readonly totals = computed(() =>
    COLUMNS.map((c, i) => {
      const both = this.rows().map((r) => r.cells[i]).filter((v) => v.a !== null && v.b !== null);
      const avg = (k: 'a' | 'b') => (both.length ? +(both.reduce((s, v) => s + (v[k] as number), 0) / both.length).toFixed(2) : null);
      const a = avg('a'), b = avg('b');
      return { key: c.key, label: c.label, a, b, delta: a !== null && b !== null ? b - a : 0 };
    }),
  );

  constructor() {
    effect(() => {
      Promise.all([this.api.get(`/api/bench/runs/${enc(this.a())}`), this.api.get(`/api/bench/runs/${enc(this.b())}`)])
        .then(([x, y]) => { this.runA.set(x); this.runB.set(y); })
        .catch((e) => this.error.set(errMsg(e)))
        .finally(() => this.loaded.set(true));
    });
  }
}
