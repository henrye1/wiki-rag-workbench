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
          <p class="compared"><b>{{ c.rag_collection || '—' }}</b><span class="muted">&nbsp;vs&nbsp;</span><b>{{ c.wiki || '—' }}</b> ·
            Sources: <span class="pill">{{ c.sources === 'standard' ? 'Standard only' : c.sources === 'all' ? 'All' : '—' }}</span>
            · Saved answers: <span class="pill">{{ c.use_saved === true ? 'On' : c.use_saved === false ? 'Off' : 'not recorded' }}</span>
            <span class="muted small">(the same for both systems)</span></p>
        }
        <p class="muted">Judge {{ d.config.judge_model }} ({{ d.config.judge_effort }}{{ d.config.judge_backend ? ', ' + d.config.judge_backend : '' }}) · {{ d.config.runs }} run(s) per topic ·
          RAG: {{ ragDocs(d) }} · Wiki: {{ d.config.systems?.wiki?.wiki?.pages ?? '?' }} pages · commit {{ d.config.git_commit ?? '—' }}</p>
        <p class="muted small">Rubric: {{ rubricLabel(d) }}</p>
        <div class="card gaps">
          <h3>Scorecard</h3>
          <table class="simple">
            <thead><tr><th>Test</th><th class="n">RAG</th><th class="n">Wiki</th><th class="n">Wiki − RAG</th><th class="n">95% confidence interval</th><th>Result</th></tr></thead>
            <tbody>
              @for (k of gapOrder; track k) {
                @let r = score(d, 'rag', k);
                @let w = score(d, 'wiki', k);
                @let e = d.summary?.gaps?.[k];
                <tr>
                  <td>{{ gapLabel[k] }}</td>
                  <td class="n" [class.muted]="!r.ok" [title]="r.reason">{{ r.text }}</td>
                  <td class="n" [class.muted]="!w.ok" [title]="w.reason">{{ w.text }}</td>
                  @if (e && r.ok && w.ok) {
                    <td class="n">{{ fmtGap(k, e.diff) }}</td>
                    <td class="n">{{ e.ci ? fmtGap(k, e.ci[0]) + ' to ' + fmtGap(k, e.ci[1]) : '—' }}</td>
                    <td>@if (e.leader) { <span class="pill" [class.rag]="e.leader === 'rag'" [class.wiki]="e.leader === 'wiki'">{{ e.verdict }}</span> }
                        @else { <span class="muted">{{ e.verdict }}</span> }</td>
                  } @else {
                    <td class="n muted">—</td><td class="n muted">—</td>
                    <td class="muted small">{{ !r.ok ? r.reason : !w.ok ? w.reason : '' }}</td>
                  }
                </tr>
              }
            </tbody>
          </table>
          <p class="muted small">Hover a score for how many answers it covers. A test with no score says why.</p>
        </div>

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
            <thead><tr><th>#</th><th>Topic</th><th title="Key points: Standard / Supporting / Beyond standard">Points (S / Sup / B)</th><th>RAG sim</th><th>RAG cov</th><th>Wiki sim</th><th>Wiki cov</th><th>Gap</th><th>Wins r/w/t</th><th>Saved answers read (wiki)</th></tr></thead>
            <tbody>
              @for (t of topics(); track t.number) {
                <tr>
                  <td>{{ t.number }}</td>
                  <td><a [routerLink]="['topic', t.number]">{{ t.title }}</a><div class="muted small">{{ t.code }} · {{ t.section }}</div></td>
                  <td>{{ t.points }} <span class="muted small">({{ t.std }} / {{ t.sup }} / {{ t.beyond }})</span></td>
                  <td><b>{{ t.rag | number: '1.1-1' }}</b></td><td>{{ t.ragCov | number: '1.0-0' }}%</td>
                  <td><b>{{ t.wiki | number: '1.1-1' }}</b></td><td>{{ t.wikiCov | number: '1.0-0' }}%</td>
                  <td [class.pos]="t.gap > 0" [class.neg]="t.gap < 0">{{ t.gap > 0 ? '+' : '' }}{{ t.gap | number: '1.1-1' }}</td>
                  <td>{{ t.wins.rag }} / {{ t.wins.wiki }} / {{ t.wins.tie }}</td>
                  <td class="small">@for (s of t.saved; track s) { <div>{{ s }}</div> } @empty { <span class="muted">none</span> }</td>
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
    .gaps { margin: 12px 0 16px; } .gaps h3 { margin: 0 0 6px; } .gaps td.n, .gaps th.n { text-align: right; white-space: nowrap; }
    .pill.rag, .pill.wiki { color: #fff; }
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
        sup: (t.key_points ?? []).filter((p: any) => p.kind === 'supporting').length,
        beyond: (t.key_points ?? []).filter((p: any) => p.kind !== 'standard' && p.kind !== 'supporting').length,
        rag, wiki, ragCov: a.rag?.coverage?.mean, wikiCov: a.wiki?.coverage?.mean,
        gap: rag !== null && wiki !== null ? rag - wiki : 0, wins: a.wins ?? { rag: 0, wiki: 0, tie: 0 },
        saved: [...new Set(Object.values<any>(t.runs ?? {}).flatMap((r) => r.systems?.wiki?.saved_answers_read ?? []))],
      };
    });
    const key = this.sort();
    const by: Record<SortKey, (r: any) => number> = { number: (r) => r.number, gap: (r) => -Math.abs(r.gap), rag: (r) => -(r.rag ?? 0), wiki: (r) => -(r.wiki ?? 0) };
    return rows.sort((x, y) => by[key](x) - by[key](y));
  });

  constructor() {
    effect(() => { this.api.get(`/api/bench/runs/${enc(this.id())}`).then((d) => this.data.set(d)).catch((e) => this.error.set(errMsg(e))); });
  }

  readonly gapOrder = ['similarity', 'coverage', 'coverage_standard', 'coverage_std_supp', 'wins', 'completeness', 'exact_match',
                       'exact_match_standard', 'citation_accuracy', 'faithfulness', 'context_recall', 'context_recall_standard', 'latency_s', 'cost_usd'];
  readonly gapLabel: Record<string, string> = {
    similarity: 'Similarity (0–10)', coverage: 'Coverage', coverage_standard: 'Standard-only coverage',
    coverage_std_supp: 'Standard + Supporting coverage', exact_match_standard: 'Standard-only exact match', wins: 'Wins (gap: share of answers)',
    exact_match: 'Exact match', faithfulness: 'Faithfulness', citation_accuracy: 'Citation accuracy', context_recall: 'Context recall', context_recall_standard: 'Standard-only context recall',
    completeness: 'Completeness', latency_s: 'Latency (s, lower is better)', cost_usd: 'Cost per query (lower is better)',
  };

  /** One system's score on one test, or "Not run yet" with the reason. */
  score(d: any, sys: string, k: string): { ok: boolean; text: string; reason: string } {
    const no = (reason: string) => ({ ok: false, text: 'Not run yet', reason });
    const added = 'this run was made before this test was added';
    if (!d.summary) return no('the run has not finished');
    if (k === 'wins') return { ok: true, text: String(d.summary.wins_by_run?.[sys] ?? 0), reason: 'answers won (both grading orders agreeing)' };
    if (this.judged.includes(k)) {
      const v = d.summary.by_system?.[sys]?.[k];
      if (v?.mean != null) return { ok: true, text: k === 'similarity' ? `${v.mean}/10` : `${v.mean}%`, reason: `${v.n} topic(s)` };
      if (k === 'coverage_std_supp' && d.config?.sources === 'standard') return no('this run used Standard only (Part A), so Supporting points were not in play');
      return no(v ? 'no graded answers' : added);
    }
    const m = d.metrics?.by_system?.[sys]?.[k];
    if (!m) return no(added);
    if (m.status !== 'measured' || m.mean == null) return no(m.reason ?? 'not measured');
    return { ok: true, text: this.fmtMetric(k, m.mean), reason: `${m.n} answer(s)${m.not_measured_in ? '; some not measured' : ''}` };
  }

  readonly judged = ['similarity', 'coverage', 'coverage_standard', 'coverage_std_supp'];

  fmtMetric(k: string, v: number) {
    if (k === 'cost_usd') return `$${v.toFixed(4)}`;
    if (k === 'latency_s') return `${v.toFixed(1)} s`;
    return `${v.toFixed(1)}%`;
  }

  fmtGap(k: string, v: number) {
    const sign = v > 0 ? '+' : v < 0 ? '−' : '';
    const a = Math.abs(v);
    if (k === 'cost_usd') return `${sign}$${a.toFixed(4)}`;
    if (k === 'latency_s') return `${sign}${a.toFixed(1)} s`;
    if (k === 'similarity') return `${sign}${a.toFixed(2)}`;
    if (k === 'wins') return `${sign}${(a * 100).toFixed(0)} pts`;
    return `${sign}${a.toFixed(1)} pts`;
  }

  rubricLabel(d: any) {
    const used = Object.values<any>(d.topics ?? {}).map((t) => t.rubric).filter(Boolean);
    const built = [...new Set(used.map((r) => r.built_in).filter(Boolean))];
    if (!built.length) return 'built in this run (before rubrics were saved)';
    const versions = used.filter((r) => r.version);
    const approved = used.filter((r) => r.approved).length;
    return `saved rubric for ${d.reference_label ?? 'this reference memo'}, built in ${built.join(', ')}`
      + (versions.length ? ` · versions ${[...new Set(versions.map((r) => r.version))].sort((a, b) => a - b).join(', ')} · ${approved} of ${used.length} topics approved`
                         : ' · recorded before rubric review');
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
