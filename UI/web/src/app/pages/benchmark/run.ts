import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { LABEL } from './systems';

type SortKey = 'number' | 'gap' | 'rag' | 'wiki' | 'rag_q';

@Component({
  selector: 'app-bench-run',
  imports: [FormsModule, RouterLink, DecimalPipe, MatButtonModule, MatButtonToggleModule, MatIconModule],
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
            <span class="muted small">(the same for every system)</span>
            · RAG editorial text: <span class="pill">{{ c.rag_editorial === true ? 'On' : c.rag_editorial === false ? 'Off' : 'not recorded' }}</span></p>
        }
        <p class="muted">Judge {{ d.config.judge_model }} ({{ d.config.judge_effort }}) · {{ d.config.runs }} run(s) per topic ·
          RAG: {{ ragDocs(d) }} · Wiki: {{ d.config.systems?.wiki?.wiki?.pages ?? '?' }} pages · commit {{ d.config.git_commit ?? '—' }}
          @if (d.config.context_checks?.version; as v) { · Context checks {{ v }}{{ d.config.context_checks.rescored ? ' (re-scored ' + d.config.context_checks.rescored.at.slice(0, 10) + ', was ' + d.config.context_checks.rescored.from + ')' : '' }} }</p>
        <p class="muted small">Rubric: {{ rubricLabel(d) }}</p>
        <div class="row downloads">
          <span class="muted small">Download</span>
          @for (f of downloads; track f.kind) {
            <a mat-stroked-button [href]="downloadUrl(f.kind)" download [title]="f.title"><mat-icon>download</mat-icon> {{ f.label }}</a>
          }
        </div>
        @for (p of pairs(d); track p) {
          <div class="card gaps">
            <h3>Scorecard: Wiki vs {{ label(p) }}</h3>
            <table class="simple">
              <thead><tr><th>Test</th><th class="n">{{ label(p) }}</th><th class="n">Wiki</th><th class="n">Wiki − RAG</th><th class="n">95% confidence interval</th><th>Result</th></tr></thead>
              <tbody>
                @for (x of rows(d, p); track x.key) {
                  <tr>
                    <td>{{ x.label }}</td>
                    <td class="n" [class.muted]="!x.rag.ok" [title]="x.rag.reason">{{ x.rag.text }}</td>
                    <td class="n" [class.muted]="!x.wiki.ok" [title]="x.wiki.reason">{{ x.wiki.text }}</td>
                    @if (x.gap; as e) {
                      <td class="n">{{ e.text }}</td>
                      <td class="n">{{ e.ci_text || '—' }}</td>
                      <td>@if (e.leader) { <span class="pill" [class.rag]="e.leader === 'rag'" [class.rag_q]="e.leader === 'rag_q'" [class.wiki]="e.leader === 'wiki'">{{ e.verdict }}</span> }
                          @else { <span class="muted">{{ e.verdict }}</span> }</td>
                    } @else {
                      <td class="n muted">—</td><td class="n muted">—</td>
                      <td class="muted small">{{ x.note }}</td>
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
                @let ss = card(d, sys, 'std_similarity');
                <div class="kv"><span>Standard-only similarity</span><b [class.muted]="!ss.ok" [title]="ss.reason">{{ ss.text }}</b></div>
                <div class="kv"><span>Coverage</span><b>{{ s.by_system[sys].coverage.mean }}%</b></div>
                <div class="kv"><span>Standard-only coverage</span><b>{{ s.by_system[sys].coverage_standard.mean }}%</b></div>
                <div class="kv"><span>Wins</span><b>{{ sys === 'rag_q' ? s.pairs?.rag_q?.wins_by_run?.rag_q : s.wins_by_run[sys] }}</b></div>
                @if (sys === 'wiki' && s.pairs?.rag_q) { <div class="muted small">vs RAG (per topic); wins vs RAG (per question): {{ s.pairs.rag_q.wins_by_run.wiki }}</div> }
                @for (k of ['contradictions', 'no_contradiction']; track k) {
                  @let x = card(d, sys, k);
                  <div class="kv"><span>{{ d.scorecard?.card_label?.[k] ?? k }}</span><b [class.muted]="!x.ok" [title]="x.reason">{{ x.text }}</b></div>
                }
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
    .downloads { gap: 8px; align-items: center; flex-wrap: wrap; margin: 4px 0 12px; }
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
  /** The run as files, read only; the reference memo is named by its label. */
  readonly downloads = [
    { kind: 'scorecard.csv', label: 'Scorecard CSV', title: 'The scorecards above: every test, each system\'s score, the wiki-minus-RAG gap with its 95% interval and the result' },
    { kind: 'results.csv', label: 'Results CSV', title: 'One row per topic, run and system: scores, key point grades, contradictions, winner and metrics' },
    { kind: 'answers.csv', label: 'All answers CSV', title: 'Every answer as each system gave it, with its question, what it read and its latency' },
    { kind: 'review.html', label: 'Side-by-side review', title: 'A page with each topic\'s question, reference text, key point grades and the answers side by side' },
  ];
  downloadUrl(kind: string) { return `/api/bench/runs/${enc(this.id())}/download/${kind}`; }
  /** The systems a run compared, as it recorded them. */
  systems(d: any): string[] { return d?.config?.systems_compared ?? []; }
  /** The RAG columns, each graded against the wiki in its own pair. */
  pairs(d: any): string[] { return this.systems(d).filter((s) => s !== 'wiki'); }
  label(sys: string) { return LABEL[sys] ?? sys; }

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

  /** The scorecard rows of one RAG column against the wiki, as the server builds them (UI/server/app/scorecard.py, the
   *  one place the tests, their order, scores, gaps and formats are set; the Scorecard CSV writes the same rows). */
  rows(d: any, pair: string): any[] { return (d.scorecard?.pairs ?? []).find((x: any) => x.pair === pair)?.rows ?? []; }
  /** A system card's extra figure (standard-only similarity, contradictions), as the server builds it. */
  card(d: any, sys: string, k: string): { ok: boolean; text: string; reason: string } {
    return d.scorecard?.cards?.[sys]?.[k] ?? { ok: false, text: 'not measured', reason: 'not in this run\'s data' };
  }

  rubricLabel(d: any) {
    const used = Object.values<any>(d.topics ?? {}).map((t) => t.rubric).filter(Boolean);
    const built = [...new Set(used.map((r) => r.built_in).filter(Boolean))];
    if (!built.length) return 'not recorded yet';
    const approved = used.filter((r) => r.approved).length;
    return `saved rubric for ${d.reference_label ?? 'this reference memo'}, built in ${built.join(', ')}`
      + ` · versions ${[...new Set(used.map((r) => r.version))].sort((a, b) => a - b).join(', ')} · ${approved} of ${used.length} topics approved`;
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
