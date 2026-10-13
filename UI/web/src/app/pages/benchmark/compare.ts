import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';

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
          @for (s of totals(); track s.sys) {
            <div class="card"><h3>{{ s.sys === 'rag' ? 'RAG' : 'Wiki' }} similarity</h3>
              <div class="stat">{{ s.a ?? '—' }} → {{ s.b ?? '—' }}</div>
              <div [class.pos]="s.delta > 0" [class.neg]="s.delta < 0">{{ s.delta > 0 ? '+' : '' }}{{ s.delta | number: '1.2-2' }}</div></div>
          }
        </div>
        <p class="muted">Topics present in both runs. Δ = run B − run A (mean similarity /10).</p>
        <table class="simple">
          <thead><tr><th>#</th><th>Topic</th><th>RAG A</th><th>RAG B</th><th>Δ RAG</th><th>Wiki A</th><th>Wiki B</th><th>Δ Wiki</th></tr></thead>
          <tbody>
            @for (r of rows(); track r.n) {
              <tr>
                <td>{{ r.n }}</td><td>{{ r.title }}</td>
                <td>{{ r.ra | number: '1.1-1' }}</td><td>{{ r.rb | number: '1.1-1' }}</td>
                <td [class.pos]="r.rd > 0" [class.neg]="r.rd < 0">{{ r.rd > 0 ? '+' : '' }}{{ r.rd | number: '1.1-1' }}</td>
                <td>{{ r.wa | number: '1.1-1' }}</td><td>{{ r.wb | number: '1.1-1' }}</td>
                <td [class.pos]="r.wd > 0" [class.neg]="r.wd < 0">{{ r.wd > 0 ? '+' : '' }}{{ r.wd | number: '1.1-1' }}</td>
              </tr>
            }
          </tbody>
        </table>
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

  readonly rows = computed(() => {
    const A = this.runA(), B = this.runB();
    if (!A || !B) return [];
    const sim = (t: any, s: string) => t?.aggregate?.[s]?.similarity?.mean ?? null;
    return Object.keys(A.topics).filter((n) => B.topics[n]?.aggregate && A.topics[n]?.aggregate).sort((x, y) => +x - +y).map((n) => {
      const ta = A.topics[n], tb = B.topics[n];
      const ra = sim(ta, 'rag'), rb = sim(tb, 'rag'), wa = sim(ta, 'wiki'), wb = sim(tb, 'wiki');
      return { n, title: ta.title, ra, rb, rd: rb - ra, wa, wb, wd: wb - wa };
    });
  });
  readonly totals = computed(() =>
    (['rag', 'wiki'] as const).map((sys) => {
      const rows = this.rows();
      const k = sys === 'rag' ? ['ra', 'rb'] : ['wa', 'wb'];
      const avg = (key: string) => (rows.length ? +(rows.reduce((s, r: any) => s + r[key], 0) / rows.length).toFixed(2) : null);
      const a = avg(k[0]), b = avg(k[1]);
      return { sys, a, b, delta: a !== null && b !== null ? b - a : 0 };
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
