import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';

type SortKey = 'number' | 'gap' | 'rag' | 'wiki';

@Component({
  selector: 'app-bench-run',
  imports: [FormsModule, RouterLink, DecimalPipe, MatButtonToggleModule],
  template: `
    <div class="page">
      <a routerLink="/benchmark" class="muted">← Runs</a>
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (data(); as d) {
        <h1>Run {{ id() }}</h1>
        @if (d.compared; as c) {
          <p class="compared"><b>{{ c.rag_collection || '—' }}</b> <span class="muted">vs</span> <b>{{ c.wiki || '—' }}</b> ·
            Sources: <span class="pill">{{ c.sources === 'standard' ? 'Standard only' : c.sources === 'all' ? 'All' : '—' }}</span>
            <span class="muted small">(the same for both systems)</span></p>
        }
        <p class="muted">Judge {{ d.config.judge_model }} ({{ d.config.judge_effort }}) · {{ d.config.runs }} run(s) per topic ·
          RAG: {{ ragDocs(d) }} · Wiki: {{ d.config.systems?.wiki?.wiki?.pages ?? '?' }} pages · commit {{ d.config.git_commit ?? '—' }}</p>
        <p class="muted small">Rubric: {{ rubricLabel(d) }}</p>

        @if (d.summary; as s) {
          <div class="cards">
            @for (sys of systems; track sys) {
              <div class="card">
                <h3>{{ sys === 'rag' ? 'RAG' : 'Wiki' }}</h3>
                <div class="stat">{{ s.by_system[sys].similarity.mean }}<span class="muted unit">/10</span></div>
                <div class="muted">similarity (± {{ s.by_system[sys].similarity.sd }})</div>
                <div class="kv"><span>Coverage</span><b>{{ s.by_system[sys].coverage.mean }}%</b></div>
                <div class="kv"><span>Standard-only coverage</span><b>{{ s.by_system[sys].coverage_standard.mean }}%</b></div>
                <div class="kv"><span>Wins</span><b>{{ s.wins_by_run[sys] }}</b></div>
              </div>
            }
            <div class="card">
              <h3>By section (similarity)</h3>
              @for (sec of sections(s); track sec.name) {
                <div class="secrow">
                  <span class="secname" [title]="sec.name">{{ short(sec.name) }}</span>
                  <span class="bars">
                    <i class="bar rag" [style.width.%]="sec.rag * 10"></i>
                    <i class="bar wiki" [style.width.%]="sec.wiki * 10"></i>
                  </span>
                </div>
              }
              <div class="muted small"><i class="sw rag"></i> RAG <i class="sw wiki"></i> Wiki</div>
            </div>
          </div>
        } @else { <p class="muted">Run not finished — summary appears when it completes.</p> }

        <div class="row head">
          <h3 class="grow">Topics</h3>
          <mat-button-toggle-group [ngModel]="sort()" (ngModelChange)="sort.set($event)">
            <mat-button-toggle value="number">#</mat-button-toggle>
            <mat-button-toggle value="gap">Gap</mat-button-toggle>
            <mat-button-toggle value="rag">RAG</mat-button-toggle>
            <mat-button-toggle value="wiki">Wiki</mat-button-toggle>
          </mat-button-toggle-group>
        </div>
        <div class="scroll-x">
          <table class="simple">
            <thead><tr><th>#</th><th>Topic</th><th>Points (std)</th><th>RAG sim</th><th>RAG cov</th><th>Wiki sim</th><th>Wiki cov</th><th>Gap</th><th>Wins r/w/t</th></tr></thead>
            <tbody>
              @for (t of topics(); track t.number) {
                <tr>
                  <td>{{ t.number }}</td>
                  <td><a [routerLink]="['topic', t.number]">{{ t.title }}</a><div class="muted small">{{ t.code }} · {{ t.section }}</div></td>
                  <td>{{ t.points }} ({{ t.std }})</td>
                  <td><b>{{ t.rag | number: '1.1-1' }}</b></td><td>{{ t.ragCov | number: '1.0-0' }}%</td>
                  <td><b>{{ t.wiki | number: '1.1-1' }}</b></td><td>{{ t.wikiCov | number: '1.0-0' }}%</td>
                  <td [class.pos]="t.gap > 0" [class.neg]="t.gap < 0">{{ t.gap > 0 ? '+' : '' }}{{ t.gap | number: '1.1-1' }}</td>
                  <td>{{ t.wins.rag }} / {{ t.wins.wiki }} / {{ t.wins.tie }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </div>
  `,
  styles: `
    .unit { font-size: 16px; } .small { font-size: 12px; } .head { margin-top: 20px; }
    .kv { display: flex; justify-content: space-between; margin-top: 6px; }
    .secrow { display: grid; grid-template-columns: 110px 1fr; gap: 8px; align-items: center; margin: 4px 0; }
    .secname { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .bars { display: flex; flex-direction: column; gap: 2px; }
    .bar { display: block; height: 6px; border-radius: 3px; min-width: 2px; }
    .rag { background: #1565c0; } .wiki { background: #ef6c00; }
    .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-left: 8px; }
    .pos { color: #1565c0; font-weight: 500; } .neg { color: #ef6c00; font-weight: 500; }
  `,
})
export class BenchRun {
  private api = inject(Api);
  readonly id = input.required<string>();
  readonly data = signal<any>(null);
  readonly error = signal('');
  readonly sort = signal<SortKey>('number');
  readonly systems = ['rag', 'wiki'];

  readonly topics = computed(() => {
    const d = this.data();
    if (!d) return [];
    const rows = Object.values<any>(d.topics).map((t) => {
      const a = t.aggregate ?? {};
      const rag = a.rag?.similarity?.mean ?? null;
      const wiki = a.wiki?.similarity?.mean ?? null;
      return {
        number: t.number, code: t.code, title: t.title, section: t.section,
        points: t.key_points?.length ?? 0, std: (t.key_points ?? []).filter((p: any) => p.kind === 'standard').length,
        rag, wiki, ragCov: a.rag?.coverage?.mean, wikiCov: a.wiki?.coverage?.mean,
        gap: rag !== null && wiki !== null ? rag - wiki : 0, wins: a.wins ?? { rag: 0, wiki: 0, tie: 0 },
      };
    });
    const key = this.sort();
    const by: Record<SortKey, (r: any) => number> = { number: (r) => r.number, gap: (r) => -Math.abs(r.gap), rag: (r) => -(r.rag ?? 0), wiki: (r) => -(r.wiki ?? 0) };
    return rows.sort((x, y) => by[key](x) - by[key](y));
  });

  constructor() {
    effect(() => { this.api.get(`/api/bench/runs/${enc(this.id())}`).then((d) => this.data.set(d)).catch((e) => this.error.set(errMsg(e))); });
  }

  rubricLabel(d: any) {
    const built = [...new Set(Object.values(d.topics ?? {}).map((t: any) => t.rubric?.built_in).filter(Boolean))];
    if (!built.length) return 'built in this run (before rubrics were saved)';
    return `saved rubric for ${d.config.reference ?? 'this reference'}, built in ${built.join(', ')}`;
  }

  ragDocs(d: any) {
    const docs = d.config.systems?.rag?.documents ?? [];
    return docs.length ? `${docs.reduce((a: number, x: any) => a + x.chunks, 0)} chunks` : '?';
  }
  sections(s: any) {
    return Object.entries<any>(s.by_section_similarity ?? {}).map(([name, v]) => ({ name, rag: v.rag ?? 0, wiki: v.wiki ?? 0 }));
  }
  short(name: string) { return name.replace('Modelling Approach – ', '').replace('Significant Increase in Credit Risk', 'SICR'); }
}
