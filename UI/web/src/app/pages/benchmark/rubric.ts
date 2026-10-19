import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';

interface Point { id: string; point: string; kind: string }
interface Fact { id: string; fact: string }
interface TopicEdit {
  n: number; title: string; version: number; reviewed_at: string | null; facts_reviewed_at: string | null;
  points: Point[]; facts: Fact[] | null; savedPoints: string; savedFacts: string; busy: boolean; error: string;
}

const TAG_LABEL: Record<string, string> = {
  standard: 'Standard (Part A)', supporting: 'Supporting (Part B/C)', beyond_standard: 'Beyond standard',
};

@Component({
  selector: 'app-bench-rubric',
  imports: [FormsModule, RouterLink, DatePipe, MatButtonModule, MatCheckboxModule, MatFormFieldModule, MatIconModule, MatInputModule, MatSelectModule],
  template: `
    <div class="page">
      <a routerLink="/benchmark" class="muted">← Runs</a>
      <h1>Rubric review</h1>
      <p class="muted">Approved key points and facts are used by every later run, which records the version of each topic's rubric it used.</p>
      <div class="row filters">
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="ref"><mat-label>Reference file</mat-label>
          <mat-select [ngModel]="ref()" (ngModelChange)="load($event)">
            @for (r of refs(); track r.reference_sha256) { <mat-option [value]="r.reference_sha256">{{ r.reference_name }} · {{ r.reference_sha256.slice(0, 10) }}…</mat-option> }
          </mat-select></mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Topic</mat-label>
          <mat-select [(ngModel)]="topicFilter">
            <mat-option [value]="0">All topics</mat-option>
            @for (t of topics(); track t.n) { <mat-option [value]="t.n">{{ t.n }}. {{ t.title }}</mat-option> }
          </mat-select></mat-form-field>
        <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Tag</mat-label>
          <mat-select [(ngModel)]="tagFilter">
            <mat-option value="">All tags</mat-option>
            @for (t of tags; track t) { <mat-option [value]="t">{{ tagLabel[t] }}</mat-option> }
          </mat-select></mat-form-field>
        <mat-checkbox [(ngModel)]="unreviewedOnly">Not yet reviewed</mat-checkbox>
        <span class="grow"></span>
        <span class="muted">{{ approvedCount() }} of {{ topics().length }} topics' key points approved · {{ factsApprovedCount() }} fact lists approved</span>
        @if (makingFacts()) { <span class="pill warn">Making fact lists… {{ factsMade() }} of {{ topics().length }}</span> }
        @else if (factsMissing()) {
          <button mat-stroked-button (click)="makeFacts()" title="The judge takes the short, specific facts (numbers, periods, thresholds, yes/no answers) from each topic's reference answer. You then review and approve them.">
            <mat-icon>fact_check</mat-icon> Make fact lists ({{ factsMissing() }} missing)</button>
        }
        @if (ref()) {
          <a mat-stroked-button [href]="exportUrl()" download
             [title]="anyDirty() ? 'Exports the saved rubric: approve your changes first to include them' : 'The saved rubric as a Word document, with the filters above'">
            <mat-icon>download</mat-icon> Export to Word</a>
        }
      </div>
      @if (anyDirty()) { <p class="muted small">You have unsaved changes; the export contains the saved rubric only.</p> }
      @if (error()) { <p class="error">{{ error() }}</p> }

      @for (t of visible(); track t.n) {
        <section class="card topic">
          <div class="row"><h3 class="grow">{{ t.n }}. {{ t.title }}</h3><span class="muted small">version {{ t.version }}</span></div>

          <div class="row head"><b class="grow">Key points ({{ t.points.length }})</b>
            @if (t.reviewed_at && !dirtyPoints(t)) { <span class="pill ok">approved {{ t.reviewed_at | date: 'd MMM y, HH:mm' }}</span> }
            @else if (dirtyPoints(t)) { <span class="pill warn">changed, not saved</span> }
            @else { <span class="pill">not yet reviewed</span> }
          </div>
          <table class="simple">
            <thead><tr><th class="id">ID</th><th>Key point</th><th class="tag">Tag</th><th></th></tr></thead>
            <tbody>
              @for (p of t.points; track p.id) {
                @if (!tagFilter || p.kind === tagFilter) {
                  <tr>
                    <td class="id mono">{{ p.id }}</td>
                    <td><textarea class="edit" rows="2" [(ngModel)]="p.point"></textarea></td>
                    <td class="tag"><mat-select [(ngModel)]="p.kind" class="tagsel">
                      @for (k of tags; track k) { <mat-option [value]="k">{{ tagLabel[k] }}</mat-option> }
                    </mat-select></td>
                    <td><button mat-icon-button (click)="removePoint(t, p)" title="Delete this key point"><mat-icon>delete</mat-icon></button></td>
                  </tr>
                }
              }
            </tbody>
          </table>
          <div class="row actions">
            <button mat-flat-button (click)="save(t, true, false)" [disabled]="t.busy || !t.points.length">Approve key points</button>
            @if (dirtyPoints(t)) { <button mat-button (click)="undo(t, 'points')">Undo changes</button> }
          </div>

          <div class="row head"><b class="grow">Exact-match facts</b>
            @if (t.facts === null) { <span class="pill">not made yet</span> }
            @else if (t.facts_reviewed_at && !dirtyFacts(t)) { <span class="pill ok">approved {{ t.facts_reviewed_at | date: 'd MMM y, HH:mm' }}</span> }
            @else if (dirtyFacts(t)) { <span class="pill warn">changed, not saved</span> }
            @else { <span class="pill">not yet reviewed</span> }
          </div>
          @if (t.facts === null) {
            <p class="muted small">Not made yet: press "Make fact lists", or it is made on this reference file's next run. You can also add facts yourself.</p>
          } @else if (!t.facts.length && !dirtyFacts(t)) {
            <p class="muted small">The reference answer has no exact-match facts for this topic, so exact match is not measured for it. You can add facts yourself.</p>
          }
          @for (f of t.facts ?? []; track f.id) {
            <div class="row fact"><span class="id mono">{{ f.id }}</span>
              <textarea class="edit grow autosize" rows="1" [(ngModel)]="f.fact"></textarea>
              <button mat-icon-button (click)="removeFact(t, f)" title="Delete this fact"><mat-icon>delete</mat-icon></button></div>
          }
          <div class="row actions">
            <button mat-stroked-button (click)="addFact(t)"><mat-icon>add</mat-icon> Add fact</button>
            <button mat-flat-button (click)="save(t, false, true)" [disabled]="t.busy || !(t.facts ?? []).length">Approve facts</button>
            @if (dirtyFacts(t)) { <button mat-button (click)="undo(t, 'facts')">Undo changes</button> }
          </div>
          @if (t.error) { <p class="error">{{ t.error }}</p> }
        </section>
      } @empty { <p class="muted">No topics match the filters.</p> }
    </div>
  `,
  styles: `
    .filters { flex-wrap: wrap; gap: 12px; align-items: center; margin: 8px 0 16px; } .ref { min-width: 360px; }
    .topic { margin-bottom: 16px; } .topic h3 { margin: 0; } .head { margin: 14px 0 6px; align-items: center; }
    .id { width: 44px; color: var(--mat-sys-on-surface-variant); } .tag { width: 230px; } .tagsel { width: 210px; }
    .mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; }
    .edit { width: 100%; box-sizing: border-box; background: var(--mat-sys-surface-container); color: inherit;
            border: 1px solid var(--mat-sys-outline-variant); border-radius: 6px; padding: 6px 8px; font: inherit; resize: vertical; }
    .fact { display: flex; align-items: center; gap: 8px; margin: 4px 0; } .fact .edit { flex: 1; min-width: 0; } .autosize { field-sizing: content; min-height: 0; } .actions { gap: 8px; margin-top: 8px; } .small { font-size: 12px; }`,
})
export class BenchRubric {
  private api = inject(Api);
  private route = inject(ActivatedRoute);
  readonly tags = ['standard', 'supporting', 'beyond_standard'];
  readonly tagLabel = TAG_LABEL;
  readonly refs = signal<any[]>([]);
  readonly ref = signal('');
  readonly topics = signal<TopicEdit[]>([]);
  readonly error = signal('');
  topicFilter = 0;
  tagFilter = '';
  unreviewedOnly = false;

  exportUrl() {
    const q = new URLSearchParams({ topic: String(this.topicFilter || 0), tag: this.tagFilter, unreviewed: String(this.unreviewedOnly) });
    return `/api/bench/rubrics/${enc(this.ref())}/export.docx?${q}`;
  }

  anyDirty() {
    return this.topics().some((t) => this.dirtyPoints(t) || this.dirtyFacts(t));
  }

  readonly makingFacts = signal(false);
  readonly factsMade = computed(() => this.topics().filter((t) => t.facts !== null).length);
  readonly factsMissing = computed(() => this.topics().filter((t) => t.facts === null).length);
  private factsTimer: ReturnType<typeof setInterval> | null = null;

  async makeFacts() {
    this.error.set('');
    try {
      await this.api.post(`/api/bench/rubrics/${enc(this.ref())}/facts`, {});
      this.makingFacts.set(true);
      this.watchFacts();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  /** While the fact lists are being made, show each one as it arrives (topics you are editing are left alone). */
  private watchFacts() {
    if (this.factsTimer) return;
    this.factsTimer = setInterval(async () => {
      try {
        const d = await this.api.get<any>(`/api/bench/rubrics/${enc(this.ref())}`);
        const fresh = new Map<number, any>(d.topics.map((t: any) => [t.topic_number, t]));
        this.topics.update((ts) => ts.map((t) => {
          const f = fresh.get(t.n);
          return f && t.facts === null && f.facts !== null && !this.dirtyPoints(t) ? this.edit(f) : t;
        }));
        this.makingFacts.set(d.making_facts);
        if (!d.making_facts && this.factsTimer) { clearInterval(this.factsTimer); this.factsTimer = null; }
      } catch { /* try again on the next tick */ }
    }, 4000);
  }

  readonly approvedCount = computed(() => this.topics().filter((t) => t.reviewed_at).length);
  readonly factsApprovedCount = computed(() => this.topics().filter((t) => t.facts_reviewed_at).length);

  constructor() {
    void this.init();
  }

  async init() {
    try {
      this.refs.set(await this.api.get('/api/bench/rubrics'));
      const want = this.route.snapshot.queryParamMap.get('ref') || this.refs()[0]?.reference_sha256;
      if (want) await this.load(want);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async load(sha: string) {
    this.error.set('');
    this.ref.set(sha);
    const d = await this.api.get<any>(`/api/bench/rubrics/${enc(sha)}`);
    this.topics.set(d.topics.map((t: any) => this.edit(t)));
    this.makingFacts.set(d.making_facts);
    if (d.making_facts) this.watchFacts();
  }

  private edit(t: any): TopicEdit {
    const points = structuredClone(t.key_points) as Point[];
    const facts = t.facts === null || t.facts === undefined ? null : (structuredClone(t.facts) as Fact[]);
    return { n: t.topic_number, title: t.topic_title, version: t.version, reviewed_at: t.reviewed_at, facts_reviewed_at: t.facts_reviewed_at,
             points, facts, savedPoints: JSON.stringify(t.key_points), savedFacts: JSON.stringify(t.facts ?? null), busy: false, error: '' };
  }

  visible() {
    return this.topics().filter((t) =>
      (!this.topicFilter || t.n === this.topicFilter)
      && (!this.tagFilter || t.points.some((p) => p.kind === this.tagFilter))
      && (!this.unreviewedOnly || !t.reviewed_at || (t.facts !== null && !t.facts_reviewed_at) || this.dirtyPoints(t) || this.dirtyFacts(t)));
  }

  dirtyPoints(t: TopicEdit) { return JSON.stringify(t.points) !== t.savedPoints; }
  dirtyFacts(t: TopicEdit) { return JSON.stringify(t.facts) !== t.savedFacts; }

  removePoint(t: TopicEdit, p: Point) { t.points = t.points.filter((x) => x !== p); this.topics.update((ts) => [...ts]); }
  removeFact(t: TopicEdit, f: Fact) { t.facts = (t.facts ?? []).filter((x) => x !== f); this.topics.update((ts) => [...ts]); }

  addFact(t: TopicEdit) {
    const used = new Set((t.facts ?? []).map((f) => f.id));
    let i = 1;
    while (used.has(`F${i}`)) i++;
    t.facts = [...(t.facts ?? []), { id: `F${i}`, fact: '' }];
    this.topics.update((ts) => [...ts]);
  }

  undo(t: TopicEdit, what: 'points' | 'facts') {
    if (what === 'points') t.points = JSON.parse(t.savedPoints); else t.facts = JSON.parse(t.savedFacts);
    this.topics.update((ts) => [...ts]);
  }

  /** Approve key points or facts: saves this topic's current key points and facts (a change makes a new version). */
  async save(t: TopicEdit, approvePoints: boolean, approveFacts: boolean) {
    t.busy = true;
    t.error = '';
    try {
      const facts = t.facts === null ? null : t.facts.filter((f) => f.fact.trim());
      const row = await this.api.put<any>(`/api/bench/rubrics/${enc(this.ref())}/topics/${t.n}`, {
        key_points: t.points.map((p) => ({ id: p.id, point: p.point.trim(), kind: p.kind })),
        facts, approve_points: approvePoints, approve_facts: approveFacts,
      });
      const next = this.edit(row);
      next.title = t.title;
      this.topics.update((ts) => ts.map((x) => (x.n === t.n ? next : x)));
    } catch (e) {
      t.error = errMsg(e);
      t.busy = false;
      this.topics.update((ts) => [...ts]);
    }
  }
}
