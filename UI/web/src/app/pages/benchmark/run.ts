import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';

type SortKey = 'number' | 'gap' | 'rag' | 'wiki' | 'rag_q';
const LABEL: Record<string, string> = { rag: 'RAG (per topic)', rag_q: 'RAG (per question)', wiki: 'Wiki' };

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
            <span class="muted small">(the same for every system)</span></p>
        }
        <p class="muted">Judge {{ d.config.judge_model }} ({{ d.config.judge_effort }}{{ d.config.judge_backend ? ', ' + d.config.judge_backend : '' }}) · {{ d.config.runs }} run(s) per topic ·
          RAG: {{ ragDocs(d) }} · Wiki: {{ d.config.systems?.wiki?.wiki?.pages ?? '?' }} pages · commit {{ d.config.git_commit ?? '—' }}</p>
        <p class="muted small">Rubric: {{ rubricLabel(d) }}</p>
        @for (p of pairs(d); track p) {
          <div class="card gaps">
            <h3>Scorecard: Wiki vs {{ label(p) }}</h3>
            <table class="simple">
              <thead><tr><th>Test</th><th class="n">{{ label(p) }}</th><th class="n">Wiki</th><th class="n">Wiki − RAG</th><th class="n">95% confidence interval</th><th>Result</th></tr></thead>
              <tbody>
                @for (k of gapOrder; track k) {
                  @let r = score(d, p, k, p);
                  @let w = score(d, 'wiki', k, p);
                  @let e = pairGaps(d, p)?.[k];
                  <tr>
                    <td>{{ gapLabel[k] }}</td>
                    <td class="n" [class.muted]="!r.ok" [title]="r.reason">{{ r.text }}</td>
                    <td class="n" [class.muted]="!w.ok" [title]="w.reason">{{ w.text }}</td>
                    @if (e && r.ok && w.ok) {
                      <td class="n">{{ fmtGap(k, e.diff) }}</td>
                      <td class="n">{{ e.ci ? fmtGap(k, e.ci[0]) + ' to ' + fmtGap(k, e.ci[1]) : '—' }}</td>
                      <td>@if (e.leader) { <span class="pill" [class.rag]="e.leader === 'rag'" [class.rag_q]="e.leader === 'rag_q'" [class.wiki]="e.leader === 'wiki'">{{ e.verdict }}</span> }
                          @else { <span class="muted">{{ e.verdict }}</span> }</td>
                    } @else {
                      <td class="n muted">—</td><td class="n muted">—</td>
                      <td class="muted small">{{ !r.ok ? r.reason : !w.ok ? w.reason : '' }}</td>
                    }
                  </tr>
                }
              </tbody>
            </table>
            <p class="muted small">Hover a score for how many answers it covers. A test with no score says why.
              @if (p !== 'rag') { The judge compares two answers at a time, so the wiki's judged scores here are from this pair; its main scores are from its pair with RAG (per topic). }</p>
          </div>
        }

        @if (d.summary; as s) {
          <div class="cards">
            @for (sys of systems(d); track sys) {
              <div class="card">
                <h3>{{ label(sys) }}</h3>
                <div class="stat">{{ s.by_system[sys].similarity.mean }}<span class="muted unit">/10</span></div>
                <div class="muted">similarity (± {{ s.by_system[sys].similarity.sd }})</div>
                <div class="kv"><span>Coverage</span><b>{{ s.by_system[sys].coverage.mean }}%</b></div>
                <div class="kv"><span>Standard-only coverage</span><b>{{ s.by_system[sys].coverage_standard.mean }}%</b></div>
                <div class="kv"><span>Wins</span><b>{{ sys === 'rag_q' ? s.pairs?.rag_q?.wins_by_run?.rag_q : s.wins_by_run[sys] }}</b></div>
                @if (sys === 'wiki' && s.pairs?.rag_q) { <div class="muted small">vs RAG (per topic); wins vs RAG (per question): {{ s.pairs.rag_q.wins_by_run.wiki }}</div> }
              </div>
            }
            <div class="card">
              <h3>By section (similarity)</h3>
              @for (sec of sections(s); track sec.name) {
                <div class="secrow">
                  <span class="secname" [title]="sec.name">{{ short(sec.name) }}</span>
                  <span class="bars">
                    <i class="bar rag" [style.width.%]="sec.rag * 10"></i>
                    @if (sec.rag_q !== null) { <i class="bar rag_q" [style.width.%]="sec.rag_q * 10"></i> }
                    <i class="bar wiki" [style.width.%]="sec.wiki * 10"></i>
                  </span>
                </div>
              }
              <div class="muted small"><i class="sw rag"></i> {{ label('rag') }} @if (systems(d).includes('rag_q')) { <i class="sw rag_q"></i> {{ label('rag_q') }} } <i class="sw wiki"></i> Wiki</div>
            </div>
          </div>
        } @else { <p class="muted">Run not finished — summary appears when it completes.</p> }

        <div class="row head">
          <h3 class="grow">Topics</h3>
          <mat-button-toggle-group [ngModel]="sort()" (ngModelChange)="sort.set($event)">
            <mat-button-toggle value="number">#</mat-button-toggle>
            <mat-button-toggle value="gap">Gap</mat-button-toggle>
            <mat-button-toggle value="rag">RAG (per topic)</mat-button-toggle>
            @if (systems(d).includes('rag_q')) { <mat-button-toggle value="rag_q">RAG (per question)</mat-button-toggle> }
            <mat-button-toggle value="wiki">Wiki</mat-button-toggle>
          </mat-button-toggle-group>
        </div>
        <div class="scroll-x">
          <table class="simple">
            <thead><tr><th>#</th><th>Topic</th><th title="Key points: Standard / Supporting / Beyond standard">Points (S / Sup / B)</th><th>RAG (per topic) sim</th><th>RAG (per topic) cov</th>@if (systems(d).includes('rag_q')) { <th>RAG (per question) sim</th><th>RAG (per question) cov</th> }<th>Wiki sim</th><th>Wiki cov</th><th title="RAG (per topic) − Wiki similarity">Gap</th><th>Wins r/w/t</th><th>Saved answers read (wiki)</th></tr></thead>
            <tbody>
              @for (t of topics(); track t.number) {
                <tr>
                  <td>{{ t.number }}</td>
                  <td><a [routerLink]="['topic', t.number]">{{ t.title }}</a><div class="muted small">{{ t.code }} · {{ t.section }}</div></td>
                  <td>{{ t.points }} <span class="muted small">({{ t.std }} / {{ t.sup }} / {{ t.beyond }})</span></td>
                  <td><b>{{ t.rag | number: '1.1-1' }}</b></td><td>{{ t.ragCov | number: '1.0-0' }}%</td>
                  @if (systems(d).includes('rag_q')) { <td><b>{{ t.ragQ | number: '1.1-1' }}</b></td><td>{{ t.ragQCov | number: '1.0-0' }}%</td> }
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
    .rag { background: #1565c0; } .rag_q { background: #6a1b9a; } .wiki { background: #ef6c00; }
    .gaps { margin: 12px 0 16px; } .gaps h3 { margin: 0 0 6px; } .gaps td.n, .gaps th.n { text-align: right; white-space: nowrap; }
    .pill.rag, .pill.rag_q, .pill.wiki { color: #fff; }
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
  /** The systems a run compared: runs made before RAG (per question) was added compared RAG (per topic) and the wiki. */
  systems(d: any): string[] { return d?.config?.systems_compared ?? ['rag', 'wiki']; }
  /** The RAG columns, each graded against the wiki in its own pair. */
  pairs(d: any): string[] { return this.systems(d).filter((s) => s !== 'wiki'); }
  label(sys: string) { return LABEL[sys] ?? sys; }
  pairGaps(d: any, p: string) { return p === 'rag' ? d.summary?.gaps : d.summary?.pairs?.[p]?.gaps; }

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
        ragQ: a.rag_q?.similarity?.mean ?? null, ragQCov: a.rag_q?.coverage?.mean,
        gap: rag !== null && wiki !== null ? rag - wiki : 0, wins: a.wins ?? { rag: 0, wiki: 0, tie: 0 },
        saved: [...new Set(Object.values<any>(t.runs ?? {}).flatMap((r) => r.systems?.wiki?.saved_answers_read ?? []))],
      };
    });
    const key = this.sort();
    const by: Record<SortKey, (r: any) => number> = { number: (r) => r.number, gap: (r) => -Math.abs(r.gap), rag: (r) => -(r.rag ?? 0),
                                                      rag_q: (r) => -(r.ragQ ?? 0), wiki: (r) => -(r.wiki ?? 0) };
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

  /** One system's score on one test in one pair, or "Not run yet" with the reason. The judged tests and wins come from
   *  the pair's own grading (the wiki is graded once per RAG column); the other tests are per answer. */
  score(d: any, sys: string, k: string, pair = 'rag'): { ok: boolean; text: string; reason: string } {
    const no = (reason: string) => ({ ok: false, text: 'Not run yet', reason });
    const added = 'this run was made before this test was added';
    if (!d.summary) return no('the run has not finished');
    const other = pair !== 'rag' ? d.summary.pairs?.[pair] : null;
    if (k === 'wins') return { ok: true, text: String((other ? other.wins_by_run : d.summary.wins_by_run)?.[sys] ?? 0),
                               reason: 'answers won (both grading orders agreeing)' };
    if (this.judged.includes(k)) {
      const v = sys === 'wiki' && other ? other.wiki?.[k] : d.summary.by_system?.[sys]?.[k];
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
    return Object.entries<any>(s.by_section_similarity ?? {}).map(([name, v]) => ({ name, rag: v.rag ?? 0, rag_q: v.rag_q ?? null, wiki: v.wiki ?? 0 }));
  }
  short(name: string) { return name.replace('Modelling Approach – ', '').replace('Significant Increase in Credit Risk', 'SICR'); }
}
