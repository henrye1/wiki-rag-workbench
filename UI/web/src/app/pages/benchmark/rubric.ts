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

interface Point { id: string; point: string; kind: string; ref?: string }
interface Fact { id: string; fact: string; kind?: string; ref?: string }
interface TopicEdit {
  n: number; title: string; version: number; reviewed_at: string | null; facts_reviewed_at: string | null;
  points: Point[]; facts: Fact[] | null; savedPoints: string; savedFacts: string; busy: boolean; error: string;
  suggestions: any; decisions: Record<string, 'accepted' | 'rejected'>; tagSources: any[] | null;
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
        <mat-form-field appearance="outline" subscriptSizing="dynamic" class="ref"><mat-label>Reference memo</mat-label>
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
        @if (suggesting()) { <span class="pill warn">Suggesting changes… {{ suggestedCount() }} of {{ topics().length }}</span> }
        @else if (ref()) {
          <button mat-stroked-button (click)="suggest()" title="For every key point and fact, the judge reads the closest paragraphs of the original source texts and suggests a tag with the paragraph that backs it; it also suggests merging list items and a hard-fact list. Nothing changes until you accept and approve.">
            <mat-icon>auto_fix_high</mat-icon> Suggest changes</button>
        }
        @if (makingFacts()) { <span class="pill warn">Making fact lists… {{ factsMade() }} of {{ topics().length }}</span> }
        @else if (factsMissing()) {
          <button mat-stroked-button (click)="makeFacts()" title="The judge takes the short, specific facts (numbers, periods, thresholds, yes/no answers) from each topic's reference answer. You then review and approve them.">
            <mat-icon>fact_check</mat-icon> Make fact lists ({{ factsMissing() }} missing)</button>
        }
        @if (ref()) {
          <a mat-stroked-button [href]="exportUrl()" download
             [title]="anyDirty() ? 'Exports the saved rubric: approve your changes first to include them' : 'The saved rubric as a Word document, with the filters above'">
            <mat-icon>download</mat-icon> Export to Word</a>
          @if (suggestedCount()) {
            <a mat-stroked-button [href]="exportUrl(true)" download title="The same export with each key point's suggested tag, paragraph and reason, and the suggested merges and hard-fact list">
              <mat-icon>download</mat-icon> Export with suggestions</a>
          }
        }
      </div>
      @if (anyDirty()) { <p class="muted small">You have unsaved changes; the export contains the saved rubric only.</p> }
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (ref()) {
        <div class="card docs">
          <div class="row">
            @if (renaming()) {
              <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Label</mat-label>
                <input matInput [(ngModel)]="newLabel" maxlength="80" (keydown.enter)="rename()" /></mat-form-field>
              <button mat-flat-button (click)="rename()" [disabled]="!newLabel.trim()">Save</button>
              <button mat-button (click)="renaming.set(false)">Cancel</button>
            } @else {
              <h3 class="grow">{{ label() }}</h3>
              <button mat-button (click)="newLabel = label(); renaming.set(true)"><mat-icon>edit</mat-icon> Rename</button>
            }
          </div>
          <div class="muted small">The memo is shown by this label everywhere; its file name is never shown.</div>
          <h4>Documents for the tag check</h4>
          <div class="row wrap">
            @for (d of documents(); track d.slug) {
              <mat-checkbox [checked]="ticks().has(d.slug)" (change)="tick(d.slug, $event.checked)">
                {{ d.name }} <span class="muted small">({{ d.tier === 'standard' ? 'Standard' : d.tier === 'supporting' ? 'Supporting' : 'other' }} · {{ d.title }})</span>
              </mat-checkbox>
            }
          </div>
          <div class="row actions">
            @if (ticksChanged()) {
              <button mat-flat-button (click)="saveTicks()" [disabled]="!ticks().size">Save choice</button>
              <button mat-button (click)="resetTicks()">Undo</button>
            }
            <span class="muted small">Suggest changes reads only the ticked documents. A new choice takes effect when you run Suggest changes
              again and approve; each approved version keeps the documents its tags were checked against.
              {{ savedTicks() === null ? 'Nothing saved yet: all documents are used.' : '' }}</span>
          </div>
        </div>
      }

      @for (t of visible(); track t.n) {
        <section class="card topic">
          <div class="row"><h3 class="grow">{{ t.n }}. {{ t.title }}</h3><span class="muted small">version {{ t.version }}</span></div>
          <div class="muted small">{{ counts(t) }}</div>
          <div class="muted small">Tags checked against: {{ t.tagSources ? docNames(t.tagSources) : 'not recorded (no suggestions accepted yet)' }}
            @if (t.suggestions) { · suggestions made against: {{ t.suggestions.documents ? docNames(t.suggestions.documents) : 'all documents (before document selection)' }} }</div>
          @for (m of t.suggestions?.merges ?? []; track $index; let i = $index) {
            @if (!m.status && !t.decisions['merge:' + i] && hasAll(t, m.ids)) {
              <div class="sug">
                <div><b>Suggested merge:</b> {{ m.ids.join(', ') }} into one point ({{ tagLabel[m.tag] }}): “{{ m.point }}”</div>
                <div class="muted small">{{ m.reason }}</div>
                <div class="row actions"><button mat-flat-button (click)="acceptMerge(t, m, i)">Accept</button>
                  <button mat-button (click)="decide(t, 'merge:' + i, 'rejected')">Reject</button></div>
              </div>
            }
          }

          <div class="row head"><b class="grow">Key points ({{ t.points.length }})</b>
            @if (t.reviewed_at && !dirtyPoints(t) && !pending(t)) { <span class="pill ok">approved {{ t.reviewed_at | date: 'd MMM y, HH:mm' }}</span> }
            @else if (dirtyPoints(t) || pending(t)) { <span class="pill warn">changed, not saved</span> }
            @else { <span class="pill">not yet reviewed</span> }
          </div>
          <table class="simple">
            <thead><tr><th class="id">ID</th><th>Key point</th><th class="tag">Tag</th><th></th></tr></thead>
            <tbody>
              @for (p of t.points; track p.id) {
                @if (!tagFilter || p.kind === tagFilter) {
                  <tr>
                    <td class="id mono">{{ p.id }}</td>
                    <td><textarea class="edit" rows="2" [(ngModel)]="p.point"></textarea>
                      @if (p.ref) { <div class="muted small">Backed by {{ p.ref }}</div> }
                      @if (pointSug(t, p); as s) {
                        <div class="sug small">
                          Suggested: <b>{{ tagLabel[s.tag] }}</b>@if (s.paragraph) { · {{ s.paragraph }} ({{ s.document }}) }
                          @if (!s.found) { <span class="pill warn" title="The judge thinks a Standard may say this, but none of the paragraphs found does: please check">check</span> }
                          @if (s.second_look) { <span class="pill" title="The judge's first reason named these paragraphs, so it was asked again with them">second look: {{ s.second_look.join(', ') }}</span> }
                          <span class="muted"> — {{ s.reason }}</span>
                          <button mat-button (click)="acceptPoint(t, p, s)">Accept</button>
                          <button mat-button (click)="decide(t, 'point:' + p.id, 'rejected')">Reject</button>
                        </div>
                      }
                    </td>
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
          @if (t.suggestions?.facts; as sf) {
            @if (!sf.status && !t.decisions['facts']) {
              <div class="sug">
                <b>Suggested hard-fact list</b> <span class="muted small">(numbers, periods, thresholds, yes/no answers only; replaces the list below)</span>
                @if (sf.items.length) {
                  <ul>@for (f of sf.items; track f.id) {
                    <li><span class="mono">{{ f.id }}</span> {{ f.fact }} <span class="pill">{{ tagLabel[f.tag] ?? '—' }}</span>
                      @if (f.paragraph) { <span class="muted small">{{ f.paragraph }} ({{ f.document }})</span> }</li>
                  }</ul>
                } @else { <p class="muted small">The reference answer has no hard facts for this topic: accepting leaves an empty list, so exact match is not measured for it.</p> }
                <div class="row actions"><button mat-flat-button (click)="acceptFacts(t, sf)">Use this list</button>
                  <button mat-button (click)="decide(t, 'facts', 'rejected')">Keep the current list</button></div>
              </div>
            }
          }
          @for (f of t.facts ?? []; track f.id) {
            <div class="row fact"><span class="id mono">{{ f.id }}</span>
              <textarea class="edit grow autosize" rows="1" [(ngModel)]="f.fact"></textarea>
              <mat-select [(ngModel)]="f.kind" class="tagsel" placeholder="Tag">
                @for (k of tags; track k) { <mat-option [value]="k">{{ tagLabel[k] }}</mat-option> }
              </mat-select>
              <button mat-icon-button (click)="removeFact(t, f)" title="Delete this fact"><mat-icon>delete</mat-icon></button></div>
          }
          <div class="row actions">
            <button mat-stroked-button (click)="addFact(t)"><mat-icon>add</mat-icon> Add fact</button>
            <button mat-flat-button (click)="save(t, false, true)" [disabled]="t.busy || t.facts === null" title="An empty list can be approved: the topic then has no exact-match facts">Approve facts</button>
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
    .fact { display: flex; align-items: center; gap: 8px; margin: 4px 0; } .fact .edit { flex: 1; min-width: 0; } .autosize { field-sizing: content; min-height: 0; } .actions { gap: 8px; margin-top: 8px; } .small { font-size: 12px; }
    .docs { margin-bottom: 16px; } .docs h3, .docs h4 { margin: 4px 0; } .wrap { flex-wrap: wrap; gap: 4px 16px; }
    .sug { margin: 6px 0; padding: 6px 10px; border-left: 3px solid #1565c0; background: color-mix(in srgb, #1565c0 8%, transparent); border-radius: 4px; }
    .sug ul { margin: 4px 0; padding-left: 18px; }`,
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

  exportUrl(suggestions = false) {
    const q = new URLSearchParams({ topic: String(this.topicFilter || 0), tag: this.tagFilter, unreviewed: String(this.unreviewedOnly),
                                    suggestions: String(suggestions) });
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
    this.label.set(d.label ?? d.reference_name);
    this.documents.set(d.documents ?? []);
    this.savedTicks.set(d.tag_sources ?? null);
    this.resetTicks();
    this.suggesting.set(d.suggesting);
    if (d.suggesting) this.watchSuggestions();
  }

  private edit(t: any): TopicEdit {
    const points = structuredClone(t.key_points) as Point[];
    const facts = t.facts === null || t.facts === undefined ? null : (structuredClone(t.facts) as Fact[]);
    return { n: t.topic_number, title: t.topic_title, version: t.version, reviewed_at: t.reviewed_at, facts_reviewed_at: t.facts_reviewed_at,
             points, facts, savedPoints: JSON.stringify(t.key_points), savedFacts: JSON.stringify(t.facts ?? null), busy: false, error: '',
             suggestions: t.suggestions ?? null, decisions: {}, tagSources: t.tag_sources ?? null };
  }

  visible() {
    return this.topics().filter((t) =>
      (!this.topicFilter || t.n === this.topicFilter)
      && (!this.tagFilter || t.points.some((p) => p.kind === this.tagFilter))
      && (!this.unreviewedOnly || !t.reviewed_at || (t.facts !== null && !t.facts_reviewed_at) || this.dirtyPoints(t) || this.dirtyFacts(t)));
  }

  pending(t: TopicEdit) { return Object.keys(t.decisions).length > 0; }

  counts(t: TopicEdit) {
    const n = (k: string) => t.points.filter((p) => p.kind === k).length;
    const f = t.facts ?? [];
    return `${t.points.length} key points: ${n('standard')} Standard · ${n('supporting')} Supporting · ${n('beyond_standard')} Beyond standard`
      + (t.facts === null ? '' : ` · ${f.length} facts (${f.filter((x) => x.kind === 'standard').length} Standard)`);
  }

  hasAll(t: TopicEdit, ids: string[]) { return ids.every((i) => t.points.some((p) => p.id === i)); }

  /** A pending tag suggestion for this point, when it would change something. */
  pointSug(t: TopicEdit, p: Point) {
    const s = t.suggestions?.points?.[p.id];
    if (!s || s.status || t.decisions['point:' + p.id]) return null;
    const ref = s.paragraph ? `${s.paragraph} (${s.document})` : undefined;
    return s.tag !== p.kind || (ref && ref !== p.ref) ? s : null;
  }

  decide(t: TopicEdit, key: string, d: 'accepted' | 'rejected') {
    t.decisions = { ...t.decisions, [key]: d };
    this.topics.update((ts) => [...ts]);
  }

  acceptPoint(t: TopicEdit, p: Point, s: any) {
    p.kind = s.tag;
    p.ref = s.paragraph ? `${s.paragraph} (${s.document})` : undefined;
    if (!p.ref) delete p.ref;
    this.decide(t, 'point:' + p.id, 'accepted');
  }

  acceptMerge(t: TopicEdit, m: any, i: number) {
    const at = t.points.findIndex((p) => m.ids.includes(p.id));
    const merged: Point = { id: m.ids[0], point: m.point, kind: m.tag };
    t.points = t.points.filter((p) => !m.ids.includes(p.id));
    t.points.splice(at, 0, merged);
    for (const id of m.ids) this.decide(t, 'point:' + id, 'rejected');  // their own tag suggestions no longer apply
    this.decide(t, 'merge:' + i, 'accepted');
  }

  acceptFacts(t: TopicEdit, sf: any) {
    t.facts = sf.items.map((f: any) => ({ id: f.id, fact: f.fact, ...(f.tag ? { kind: f.tag } : {}),
                                          ...(f.paragraph ? { ref: `${f.paragraph} (${f.document})` } : {}) }));
    this.decide(t, 'facts', 'accepted');
  }

  readonly label = signal('');
  readonly renaming = signal(false);
  newLabel = '';
  readonly documents = signal<any[]>([]);
  readonly savedTicks = signal<string[] | null>(null);
  readonly ticks = signal<Set<string>>(new Set());

  docNames(docs: any[]) { return docs.map((d) => (typeof d === 'string' ? d : d.name)).join(', '); }

  tick(slug: string, on: boolean) {
    const s = new Set(this.ticks());
    if (on) s.add(slug); else s.delete(slug);
    this.ticks.set(s);
  }

  resetTicks() {
    const saved = this.savedTicks();
    this.ticks.set(new Set(saved ?? this.documents().map((d) => d.slug)));
  }

  ticksChanged() {
    const saved = this.savedTicks() ?? this.documents().map((d) => d.slug);
    const now = this.ticks();
    return this.savedTicks() === null ? now.size !== saved.length || saved.some((s) => !now.has(s))
                                      : saved.length !== now.size || saved.some((s) => !now.has(s));
  }

  async saveTicks() {
    try {
      const r = await this.api.put<any>(`/api/bench/references/${enc(this.ref())}`, { tag_sources: [...this.ticks()] });
      this.savedTicks.set(r.tag_sources);
      this.resetTicks();
    } catch (e) { this.error.set(errMsg(e)); }
  }

  async rename() {
    try {
      const r = await this.api.put<any>(`/api/bench/references/${enc(this.ref())}`, { label: this.newLabel.trim() });
      this.label.set(r.label);
      this.renaming.set(false);
      this.refs.set(await this.api.get('/api/bench/rubrics'));
    } catch (e) { this.error.set(errMsg(e)); }
  }

  readonly suggesting = signal(false);
  readonly suggestedCount = computed(() => this.topics().filter((t) => t.suggestions).length);
  private sugTimer: ReturnType<typeof setInterval> | null = null;

  async suggest() {
    this.error.set('');
    try {
      await this.api.post(`/api/bench/rubrics/${enc(this.ref())}/suggest`, { topics: this.topicFilter ? String(this.topicFilter) : '' });
      this.suggesting.set(true);
      this.watchSuggestions();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  /** While suggestions are being made, show each topic's as it arrives (topics you are editing are left alone). */
  private watchSuggestions() {
    if (this.sugTimer) return;
    this.sugTimer = setInterval(async () => {
      try {
        const d = await this.api.get<any>(`/api/bench/rubrics/${enc(this.ref())}`);
        const fresh = new Map<number, any>(d.topics.map((t: any) => [t.topic_number, t]));
        this.topics.update((ts) => ts.map((t) => {
          const f = fresh.get(t.n);
          if (!f || JSON.stringify(f.suggestions) === JSON.stringify(t.suggestions)) return t;
          return this.dirtyPoints(t) || this.dirtyFacts(t) || this.pending(t) ? t : this.edit(f);
        }));
        this.suggesting.set(d.suggesting);
        if (!d.suggesting && this.sugTimer) { clearInterval(this.sugTimer); this.sugTimer = null; }
      } catch { /* try again on the next tick */ }
    }, 5000);
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
        key_points: t.points.map((p) => ({ id: p.id, point: p.point.trim(), kind: p.kind, ...(p.ref ? { ref: p.ref } : {}) })),
        facts, approve_points: approvePoints, approve_facts: approveFacts, decisions: t.decisions,
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
