import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';

interface Point { id: string; point: string; kind: string; ref?: string }
interface Fact { id: string; fact: string; kind?: string; ref?: string }
type Decision = 'accepted' | 'rejected';
interface TopicEdit {
  n: number; title: string; version: number; reviewed_at: string | null; facts_reviewed_at: string | null;
  points: Point[]; facts: Fact[] | null; savedPoints: string; savedFacts: string; busy: boolean; error: string;
  suggestions: any; decisions: Record<string, Decision>; tagSources: any[] | null;
}
type Status = 'review' | 'progress' | 'approved';
type Filter = 'all' | 'pending' | 'standard' | 'supporting' | 'beyond_standard';

const TAG_LABEL: Record<string, string> = {
  standard: 'Standard (Part A)', supporting: 'Supporting (Part B/C)', beyond_standard: 'Beyond standard',
};

/** Explanations shown in the (i) icons and tooltips. */
const INFO = {
  page: 'The marking rubric, one topic at a time: its key points and its exact-match facts as they are saved. Approved topics are used by every later run, and each run records the rubric version it used.',
  progress: 'A topic counts as approved when both its key points and its fact list are approved and nothing has changed since.',
  status: 'Icons: green tick approved, orange circle in progress, empty circle to review. The blue number counts suggestions still to decide. To review: nothing decided yet. In progress: unsaved changes, decided suggestions, or only part of the topic approved. Approved: key points and facts approved.',
  standard: 'Standard (Part A): stated in a Standard\'s own text, including its appendices. Counts in coverage, standard-only coverage and Standard + Supporting coverage.',
  supporting: 'Supporting (Part B/C): stated only in documents published with the Standard (implementation guidance, illustrative examples, basis for conclusions). Counts in coverage and Standard + Supporting coverage.',
  beyond_standard: 'Beyond standard: practice, regulation or opinion not stated in the source documents. Counts in coverage only.',
  version: 'Each saved change makes a new version of the topic; earlier versions are kept and runs record the version they used.',
  keyPoints: 'Each key point is graded full, partial or missing in every answer. Click the pencil to edit its wording or tag.',
  facts: 'Hard facts (numbers, periods, thresholds, yes/no answers). Exact match scores the share an answer states; Standard-only exact match uses the facts tagged Standard.',
  suggestion: 'The judge read the closest paragraphs of the ticked source documents and suggests this tag. Accept applies it; Reject keeps the current tag. Nothing is saved until you approve the topic.',
  check: 'The judge believes a Standard states this, but none of the paragraphs it found does. Worth checking yourself.',
  merge: 'These key points are only items of one list in the reference; merging them stops a long list outweighing core requirements.',
  factList: 'A list holding only hard facts, each tagged with the paragraph behind it. Using it replaces the current fact list.',
  acceptAll: 'Applies every pending suggestion for this topic: tags, backing paragraphs, merges and the suggested fact list. You can still undo single items before approving.',
  approve: 'Saves this topic\'s key points and facts as approved (a change makes a new version) and opens the next topic not yet approved.',
  discard: 'Discards this topic\'s unsaved changes.',
  settings: 'The memo\'s label, the source documents for the tag check, suggestions and exports.',
  rename: 'The memo is shown by this label everywhere; its file name is never shown.',
  docs: 'Suggest changes reads only the ticked documents. A new choice takes effect when you run Suggest changes again and approve; each approved version keeps the documents its tags were checked against.',
  suggest: 'For every key point and fact, the judge reads the closest paragraphs of the ticked documents (found by words and by meaning) and suggests a tag, list merges and a hard-fact list. Replaces earlier suggestions; the rubric itself does not change.',
  makeFacts: 'Make the fact lists still missing, from each topic\'s reference answer.',
  export: 'The saved rubric as a Word document. Unsaved changes are not included.',
  exportSug: 'The saved rubric with every suggestion: current and suggested tag, paragraph, reason, merges and the suggested hard-fact list.',
  pendingFilter: 'Only key points with a suggested tag change still to decide.',
} as const;

@Component({
  selector: 'app-bench-rubric',
  imports: [FormsModule, RouterLink, DatePipe, MatButtonModule, MatCheckboxModule, MatFormFieldModule, MatIconModule,
            MatInputModule, MatProgressBarModule, MatSelectModule, MatTooltipModule],
  template: `
    <div class="page">
      <a routerLink="/benchmark" class="muted">← Runs</a>
      <div class="row title">
        <h1>Rubric review</h1><mat-icon class="info" [matTooltip]="info.page">info_outline</mat-icon>
        <span class="grow"></span>
        @if (refs().length > 1) {
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="memo"><mat-label>Reference memo</mat-label>
            <mat-select [ngModel]="ref()" (ngModelChange)="load($event)">
              @for (r of refs(); track r.reference_sha256) { <mat-option [value]="r.reference_sha256">{{ r.reference_name }}</mat-option> }
            </mat-select></mat-form-field>
        } @else { <span class="muted">{{ label() }}</span> }
        <button mat-stroked-button (click)="showSettings.set(!showSettings())" [matTooltip]="info.settings">
          <mat-icon>settings</mat-icon> Settings</button>
      </div>

      @if (showSettings() && ref()) {
        <div class="card settings">
          <div class="row">
            @if (renaming()) {
              <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Label</mat-label>
                <input matInput [(ngModel)]="newLabel" maxlength="80" (keydown.enter)="rename()" /></mat-form-field>
              <button mat-flat-button (click)="rename()" [disabled]="!newLabel.trim()">Save</button>
              <button mat-button (click)="renaming.set(false)">Cancel</button>
            } @else {
              <b>{{ label() }}</b>
              <button mat-button (click)="newLabel = label(); renaming.set(true)" [matTooltip]="info.rename"><mat-icon>edit</mat-icon> Rename</button>
            }
            <span class="grow"></span>
            @if (suggesting()) { <span class="pill warn">Suggesting changes… {{ suggestedCount() }} of {{ topics().length }}</span> }
            @else { <button mat-stroked-button (click)="suggest()" [matTooltip]="info.suggest"><mat-icon>auto_fix_high</mat-icon> Suggest changes</button> }
            @if (makingFacts()) { <span class="pill warn">Making fact lists… {{ factsMade() }} of {{ topics().length }}</span> }
            @else if (factsMissing()) { <button mat-stroked-button (click)="makeFacts()" [matTooltip]="info.makeFacts"><mat-icon>fact_check</mat-icon> Make fact lists ({{ factsMissing() }})</button> }
            <a mat-stroked-button [href]="exportUrl()" download [matTooltip]="info.export"><mat-icon>download</mat-icon> Export</a>
            @if (suggestedCount()) { <a mat-stroked-button [href]="exportUrl(true)" download [matTooltip]="info.exportSug"><mat-icon>download</mat-icon> Export with suggestions</a> }
          </div>
          <div class="row docs">
            <span class="muted">Documents for the tag check</span><mat-icon class="info" [matTooltip]="info.docs">info_outline</mat-icon>
            @for (d of documents(); track d.slug) {
              <mat-checkbox [checked]="ticks().has(d.slug)" (change)="tick(d.slug, $event.checked)" [matTooltip]="d.title">{{ d.name }}</mat-checkbox>
            }
            @if (ticksChanged()) {
              <button mat-flat-button (click)="saveTicks()" [disabled]="!ticks().size">Save choice</button>
              <button mat-button (click)="resetTicks()">Undo</button>
            }
          </div>
        </div>
      }
      @if (error()) { <p class="error">{{ error() }}</p> }
      @if (loading()) { <mat-progress-bar mode="indeterminate" class="loading" /> }

      <div class="layout">
        <nav class="card side">
          <div class="row prog"><b>Approved: {{ approvedCount() }} of {{ topics().length }}</b>
            <mat-icon class="info" [matTooltip]="info.progress + ' ' + info.status">info_outline</mat-icon></div>
          <mat-progress-bar mode="determinate" [value]="topics().length ? (100 * approvedCount()) / topics().length : 0" />
          <ul>
            @for (t of topics(); track t.n) {
              @let st = status(t);
              <li [class.on]="t.n === current()" (click)="go(t.n)" (keydown.enter)="go(t.n)" tabindex="0" [title]="t.title + ' · ' + statusLabel[st]">
                <mat-icon class="st" [class.ok]="st === 'approved'" [class.warn]="st === 'progress'">{{ st === 'approved' ? 'check_circle' : st === 'progress' ? 'pending' : 'radio_button_unchecked' }}</mat-icon>
                <span class="num">{{ t.n }}</span><span class="name">{{ t.title }}</span>
                @if (pendingCount(t); as c) { <span class="badge" matTooltip="Suggestions still to decide">{{ c }}</span> }
              </li>
            }
          </ul>
        </nav>

        @if (topic(); as t) {
          <section class="card main">
            @let st = status(t);
            <div class="head">
              <h2>{{ t.n }}. {{ t.title }}</h2>
              <div class="headside">
                <span class="pill" [class.ok]="st === 'approved'" [class.warn]="st === 'progress'">{{ statusLabel[st] }}</span>
                <span class="muted small" [matTooltip]="info.version + (t.tagSources ? ' Tags checked against: ' + docNames(t.tagSources) + '.' : '')">v{{ t.version }}</span>
                <button mat-icon-button (click)="step(-1)" [disabled]="!hasPrev()" matTooltip="Previous topic"><mat-icon>chevron_left</mat-icon></button>
                <button mat-icon-button (click)="step(1)" [disabled]="!hasNext()" matTooltip="Next topic"><mat-icon>chevron_right</mat-icon></button>
              </div>
            </div>

            <div class="row filters">
              <button class="chip" [class.on]="filter() === 'all'" (click)="filter.set('all')">All {{ t.points.length }}</button>
              @if (pendingTags(t).length) {
                <button class="chip" [class.on]="filter() === 'pending'" (click)="filter.set('pending')" [matTooltip]="info.pendingFilter">Suggestions {{ pendingTags(t).length }}</button>
              }
              @for (k of tags; track k) {
                <button [class]="'chip ' + k" [class.on]="filter() === k" (click)="filter.set($any(k))" [matTooltip]="tip(k)">{{ shortTag[k] }} {{ count(t, k) }}</button>
              }
              <span class="grow"></span>
              @if (pendingCount(t)) {
                <button mat-stroked-button (click)="acceptAll(t)" [matTooltip]="info.acceptAll"><mat-icon>done_all</mat-icon> Accept all suggestions ({{ pendingCount(t) }})</button>
              }
            </div>

            @for (r of mergeRows(t); track r.i) {
              @if (!r.decision) {
                <div class="sugcard">
                  <div class="row"><mat-icon class="sic">call_merge</mat-icon>
                    <b>Merge {{ r.m.ids.join(', ') }} into one point</b>
                    <span [class]="'pill tagpill ' + r.m.tag">{{ shortTag[r.m.tag] }}</span>
                    <mat-icon class="info sm" [matTooltip]="info.merge + ' ' + r.m.reason">info_outline</mat-icon>
                    <span class="grow"></span>
                    <button mat-button (click)="acceptMerge(t, r.i)">Accept</button>
                    <button mat-button (click)="rejectMerge(t, r.i)">Reject</button>
                  </div>
                  <div class="merged">“{{ r.m.point }}”</div>
                </div>
              }
            }

            <h3 class="sec">Key points <mat-icon class="info sm" [matTooltip]="info.keyPoints">info_outline</mat-icon></h3>
            <div class="rows">
              @for (p of shownPoints(t); track p.id) {
                @let chg = pointChange(t, p);
                @let ch = chg.major;
                @let sg = pendingTag(t, p.id);
                <div class="item" [class.changed]="ch">
                  <div class="row line">
                    <span class="id mono">{{ p.id }}</span>
                    @if (editing() === t.n + ':' + p.id) {
                      <textarea class="edit grow autosize" rows="1" [(ngModel)]="p.point"></textarea>
                      <mat-select [(ngModel)]="p.kind" class="tagsel">
                        @for (k of tags; track k) { <mat-option [value]="k">{{ tagLabel[k] }}</mat-option> }
                      </mat-select>
                      <button mat-icon-button (click)="removePoint(t, p)" matTooltip="Delete this key point"><mat-icon>delete</mat-icon></button>
                      <button mat-flat-button (click)="editing.set('')">Done</button>
                    } @else {
                      <span class="text grow">{{ p.point }}</span>
                      <span class="tagcell">
                        <span [class]="'pill tagpill ' + p.kind" [matTooltip]="tip(p.kind)">{{ shortTag[p.kind] }}</span>
                        @if (p.ref && p.kind !== 'beyond_standard') { <span class="muted small">{{ p.ref }}</span> }
                      </span>
                      <button mat-icon-button class="pencil" (click)="editing.set(t.n + ':' + p.id)" matTooltip="Edit wording or tag"><mat-icon>edit</mat-icon></button>
                    }
                  </div>
                  @if (ch) {
                    <div class="row note changednote"><mat-icon class="sic">edit_note</mat-icon><span class="grow">{{ ch }}{{ chg.minor ? ' · ' + chg.minor : '' }}</span>
                      <button mat-button (click)="undoPoint(t, p.id)">Undo</button></div>
                  } @else if (chg.minor) {
                    <div class="row note minornote muted small"><span class="grow">{{ chg.minor }} (not saved yet)</span>
                      <a class="undo" (click)="undoPoint(t, p.id)" (keydown.enter)="undoPoint(t, p.id)" tabindex="0">Undo</a></div>
                  }
                  @if (sg) {
                    <div class="row note sug">
                      <mat-icon class="sic">lightbulb</mat-icon>
                      <span>Suggested <span [class]="'pill tagpill ' + sg.tag">{{ shortTag[sg.tag] }}</span>
                        @if (sg.paragraph && sg.tag !== 'beyond_standard') { <span class="muted small">{{ sg.paragraph }} · {{ doc(sg.document) }}</span> }</span>
                      @if (!sg.found) { <span class="pill warn" [matTooltip]="info.check">Check</span> }
                      <mat-icon class="info sm" [matTooltip]="sg.reason + (sg.second_look ? ' (Second look with ' + sg.second_look.join(', ') + '.)' : '')">info_outline</mat-icon>
                      <span class="grow"></span>
                      <button mat-button (click)="acceptPoint(t, p.id)" [matTooltip]="info.suggestion">Accept</button>
                      <button mat-button (click)="rejectPoint(t, p.id)">Reject</button>
                    </div>
                  }
                </div>
              } @empty { <p class="muted">No key points in this view.</p> }
            </div>

            <h3 class="sec">Facts <mat-icon class="info sm" [matTooltip]="info.facts">info_outline</mat-icon>
              @if (t.facts_reviewed_at && !dirtyFacts(t)) { <span class="muted small">approved {{ t.facts_reviewed_at | date: 'd MMM y' }}</span> }</h3>
            @if (t.suggestions?.facts && !factsDecision(t)) {
              <div class="sugcard">
                <div class="row"><mat-icon class="sic">lightbulb</mat-icon>
                  <b>Suggested hard-fact list ({{ t.suggestions.facts.items.length }})</b>
                  <mat-icon class="info sm" [matTooltip]="info.factList">info_outline</mat-icon>
                  <span class="grow"></span>
                  <button mat-button (click)="acceptFacts(t)">Use this list</button>
                  <button mat-button (click)="rejectFacts(t)">Keep current</button>
                </div>
                @for (f of t.suggestions.facts.items; track f.id) {
                  <div class="row factline"><span class="id mono">{{ f.id }}</span><span class="text grow">{{ f.fact }}</span>
                    <span [class]="'pill tagpill ' + f.tag">{{ shortTag[f.tag] ?? '—' }}</span>
                    @if (f.paragraph && f.tag !== 'beyond_standard') { <span class="muted small">{{ f.paragraph }}</span> }</div>
                } @empty { <p class="muted small">The reference has no hard facts for this topic; using this list leaves it empty.</p> }
              </div>
            }
            <div class="rows">
              @for (f of t.facts ?? []; track f.id) {
                <div class="item" [class.changed]="factChanged(t, f)">
                  <div class="row line">
                    <span class="id mono">{{ f.id }}</span>
                    @if (editing() === t.n + ':' + f.id) {
                      <textarea class="edit grow autosize" rows="1" [(ngModel)]="f.fact"></textarea>
                      <mat-select [(ngModel)]="f.kind" class="tagsel" placeholder="Tag">
                        @for (k of tags; track k) { <mat-option [value]="k">{{ tagLabel[k] }}</mat-option> }
                      </mat-select>
                      <button mat-icon-button (click)="removeFact(t, f)" matTooltip="Delete this fact"><mat-icon>delete</mat-icon></button>
                      <button mat-flat-button (click)="editing.set('')">Done</button>
                    } @else {
                      <span class="text grow">{{ f.fact || '(empty)' }}</span>
                      <span class="tagcell">
                        @if (f.kind) { <span [class]="'pill tagpill ' + f.kind" [matTooltip]="tip(f.kind)">{{ shortTag[f.kind] }}</span> }
                        @if (f.ref && f.kind !== 'beyond_standard') { <span class="muted small">{{ f.ref }}</span> }
                      </span>
                      <button mat-icon-button class="pencil" (click)="editing.set(t.n + ':' + f.id)" matTooltip="Edit wording or tag"><mat-icon>edit</mat-icon></button>
                    }
                  </div>
                </div>
              } @empty { <p class="muted small">{{ t.facts === null ? 'No fact list yet.' : 'No facts: exact match is not measured for this topic.' }}</p> }
            </div>
            <button mat-button (click)="addFact(t)"><mat-icon>add</mat-icon> Add fact</button>
            @if (t.error) { <p class="error">{{ t.error }}</p> }

            @let chs = changes(t);
            @if (chs.length || st !== 'approved') {
              <div class="savebar">
                <div class="grow">
                  @if (chs.length) {
                    <b>Unsaved:</b> {{ chs.join(' · ') }}
                  } @else { <span class="muted">Not yet approved{{ t.reviewed_at ? ' (key points approved, facts not)' : t.facts_reviewed_at ? ' (facts approved, key points not)' : '' }}</span> }
                </div>
                @if (chs.length) { <button mat-button (click)="undo(t)" [matTooltip]="info.discard">Discard</button> }
                <button mat-flat-button (click)="approve(t)" [disabled]="t.busy || !t.points.length" [matTooltip]="info.approve"><mat-icon>check</mat-icon> Approve topic</button>
              </div>
            } @else {
              <div class="row approved muted small"><mat-icon class="st ok">check_circle</mat-icon> Approved {{ t.reviewed_at | date: 'd MMM y, HH:mm' }} · version {{ t.version }}</div>
            }
          </section>
        }
      </div>
    </div>
  `,
  styles: `
    .title h1 { margin: 0; } .title { margin: 4px 0 12px; } .memo { min-width: 240px; } .loading { margin-bottom: 8px; }
    .info { font-size: 18px; width: 18px; height: 18px; color: var(--mat-sys-on-surface-variant); cursor: help; vertical-align: middle; }
    .info.sm { font-size: 15px; width: 15px; height: 15px; }
    .settings { margin-bottom: 12px; } .settings .docs { margin-top: 8px; gap: 4px 14px; }
    .layout { display: grid; grid-template-columns: 1fr; gap: 16px; align-items: start; }
    .side { max-height: 260px; overflow: auto; padding: 12px; }
    @media (min-width: 1200px) {
      .layout { grid-template-columns: 270px minmax(0, 1fr); }
      .side { position: sticky; top: 8px; max-height: calc(100vh - 24px); }
    }
    .side .prog { gap: 4px; margin-bottom: 6px; } .side ul { list-style: none; margin: 8px 0; padding: 0; }
    .side li { display: grid; grid-template-columns: 20px 20px 1fr auto; gap: 6px; align-items: center; padding: 5px 6px; border-radius: 8px; cursor: pointer; font-size: 13px; }
    .side li:hover { background: var(--mat-sys-surface-container); } .side li.on { background: var(--mat-sys-secondary-container); }
    .side .num { color: var(--mat-sys-on-surface-variant); text-align: right; } .side .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .st { font-size: 18px; width: 18px; height: 18px; color: var(--mat-sys-outline); } .st.ok { color: #2e7d32; } .st.warn { color: #ef6c00; }
    .badge { background: #1565c0; color: #fff; border-radius: 9px; font-size: 11px; padding: 0 6px; line-height: 18px; }
    .main { min-width: 0; } .head { display: flex; align-items: flex-start; gap: 12px; }
    .head h2 { margin: 0; font: var(--mat-sys-title-large); flex: 1; min-width: 0; padding-top: 6px; }
    .headside { display: flex; align-items: center; gap: 4px; white-space: nowrap; flex: none; }
    .minornote { margin-top: 2px; } .undo { cursor: pointer; color: var(--mat-sys-primary); }
    .savebar button { white-space: nowrap; flex: none; }
    .filters { gap: 6px; margin: 10px 0 6px; }
    .chip { border: 1px solid var(--mat-sys-outline-variant); background: transparent; color: inherit; border-radius: 16px; padding: 3px 12px; font: inherit; font-size: 13px; cursor: pointer; }
    .chip.on { background: var(--mat-sys-secondary-container); border-color: transparent; font-weight: 600; }
    .sec { margin: 18px 0 6px; font: var(--mat-sys-title-small); display: flex; align-items: center; gap: 6px; }
    .rows { display: flex; flex-direction: column; }
    .item { border-bottom: 1px solid var(--mat-sys-outline-variant); padding: 6px 4px; border-left: 3px solid transparent; }
    .item.changed { border-left-color: #ef6c00; background: color-mix(in srgb, #ef6c00 5%, transparent); }
    .line { flex-wrap: nowrap; align-items: flex-start; gap: 10px; } .line .text { line-height: 1.45; padding-top: 2px; }
    .tagcell { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; min-width: 110px; text-align: right; }
    .pencil { opacity: 0.35; } .item:hover .pencil { opacity: 1; }
    .note { gap: 8px; margin: 4px 0 2px 46px; font-size: 13px; }
    .sug { color: var(--mat-sys-on-surface); background: color-mix(in srgb, #1565c0 8%, transparent); border-radius: 8px; padding: 2px 8px; }
    .changednote { color: #ef6c00; } .sic { font-size: 18px; width: 18px; height: 18px; }
    .sugcard { border: 1px solid color-mix(in srgb, #1565c0 45%, transparent); border-radius: 10px; padding: 8px 12px; margin: 8px 0; }
    .sugcard .merged { margin: 4px 0 2px 26px; } .factline { gap: 8px; margin: 3px 0 0 26px; font-size: 13px; }
    .id { width: 34px; flex: none; color: var(--mat-sys-on-surface-variant); }
    .mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; } .small { font-size: 12px; }
    .tagpill.standard { background: color-mix(in srgb, #2e7d32 22%, transparent); }
    .tagpill.supporting { background: color-mix(in srgb, #1565c0 22%, transparent); }
    .tagpill.beyond_standard { background: color-mix(in srgb, #ef6c00 22%, transparent); }
    .chip.standard.on { background: color-mix(in srgb, #2e7d32 25%, transparent); }
    .chip.supporting.on { background: color-mix(in srgb, #1565c0 25%, transparent); }
    .chip.beyond_standard.on { background: color-mix(in srgb, #ef6c00 25%, transparent); }
    .tagsel { width: 190px; flex: none; }
    .edit { width: 100%; box-sizing: border-box; background: var(--mat-sys-surface-container); color: inherit;
            border: 1px solid var(--mat-sys-outline-variant); border-radius: 6px; padding: 6px 8px; font: inherit; resize: vertical; }
    .autosize { field-sizing: content; min-height: 0; }
    .savebar { position: sticky; bottom: 0; display: flex; align-items: center; gap: 8px; margin: 16px -16px -16px; padding: 10px 16px;
               background: var(--mat-sys-surface-container); border-top: 1px solid var(--mat-sys-outline-variant); border-radius: 0 0 12px 12px; }
    .approved { margin-top: 16px; gap: 6px; }`,
})
export class BenchRubric {
  private api = inject(Api);
  private route = inject(ActivatedRoute);
  readonly tags = ['standard', 'supporting', 'beyond_standard'];
  readonly tagLabel = TAG_LABEL;
  readonly shortTag: Record<string, string> = { standard: 'Standard', supporting: 'Supporting', beyond_standard: 'Beyond' };
  readonly info = INFO;
  tip(k: string | null | undefined): string { return k ? (INFO as Record<string, string>)[k] ?? '' : ''; }
  readonly statusLabel: Record<Status, string> = { review: 'To review', progress: 'In progress', approved: 'Approved' };
  readonly refs = signal<any[]>([]);
  readonly ref = signal('');
  readonly topics = signal<TopicEdit[]>([]);
  readonly error = signal('');
  readonly current = signal(0);
  readonly filter = signal<Filter>('all');
  readonly editing = signal('');
  readonly showSettings = signal(false);
  readonly loading = signal(true);

  readonly topic = computed(() => this.topics().find((t) => t.n === this.current()) ?? null);
  readonly approvedCount = computed(() => this.topics().filter((t) => this.status(t) === 'approved').length);

  constructor() {
    void this.init();
  }

  async init() {
    try {
      this.refs.set(await this.api.get('/api/bench/rubrics'));
      const want = this.route.snapshot.queryParamMap.get('ref') || this.refs()[0]?.reference_sha256;
      if (want) await this.load(want);
      else this.loading.set(false);
    } catch (e) {
      this.loading.set(false);
      this.error.set(errMsg(e));
    }
  }

  async load(sha: string) {
    this.error.set('');
    this.ref.set(sha);
    this.loading.set(true);
    const d = await this.api.get<any>(`/api/bench/rubrics/${enc(sha)}`).finally(() => this.loading.set(false));
    this.topics.set(d.topics.map((t: any) => this.edit(t)));
    this.makingFacts.set(d.making_facts);
    if (d.making_facts) this.watchFacts();
    this.label.set(d.label ?? d.reference_name);
    this.documents.set(d.documents ?? []);
    this.savedTicks.set(d.tag_sources ?? null);
    this.resetTicks();
    this.suggesting.set(d.suggesting);
    if (d.suggesting) this.watchSuggestions();
    const first = this.topics().find((t) => this.status(t) !== 'approved') ?? this.topics()[0];
    if (first && !this.topics().some((t) => t.n === this.current())) this.go(first.n);
  }

  private edit(t: any): TopicEdit {
    const points = structuredClone(t.key_points) as Point[];
    const facts = t.facts === null || t.facts === undefined ? null : (structuredClone(t.facts) as Fact[]);
    return { n: t.topic_number, title: t.topic_title, version: t.version, reviewed_at: t.reviewed_at, facts_reviewed_at: t.facts_reviewed_at,
             points, facts, savedPoints: JSON.stringify(t.key_points), savedFacts: JSON.stringify(t.facts ?? null), busy: false, error: '',
             suggestions: t.suggestions ?? null, decisions: {}, tagSources: t.tag_sources ?? null };
  }

  private refresh() { this.topics.update((ts) => [...ts]); }

  // ---------- navigation and status ----------

  go(n: number) { this.current.set(n); this.filter.set('all'); this.editing.set(''); }
  private index() { return this.topics().findIndex((t) => t.n === this.current()); }
  hasPrev() { return this.index() > 0; }
  hasNext() { return this.index() < this.topics().length - 1; }
  step(d: number) { const t = this.topics()[this.index() + d]; if (t) this.go(t.n); }

  dirtyPoints(t: TopicEdit) { return JSON.stringify(t.points) !== t.savedPoints; }
  dirtyFacts(t: TopicEdit) { return JSON.stringify(t.facts) !== t.savedFacts; }
  pending(t: TopicEdit) { return Object.keys(t.decisions).length > 0; }

  status(t: TopicEdit): Status {
    if (this.dirtyPoints(t) || this.dirtyFacts(t) || this.pending(t)) return 'progress';
    if (t.reviewed_at && t.facts !== null && t.facts_reviewed_at) return 'approved';
    const sug = t.suggestions;
    const decided = sug && (Object.values<any>(sug.points ?? {}).some((p) => p.status) || (sug.merges ?? []).some((m: any) => m.status) || sug.facts?.status);
    return t.reviewed_at || t.facts_reviewed_at || decided ? 'progress' : 'review';
  }

  count(t: TopicEdit, k: string) { return t.points.filter((p) => p.kind === k).length; }
  docNames(docs: any[]) { return docs.map((d) => (typeof d === 'string' ? d : d.name)).join(', '); }

  shownPoints(t: TopicEdit) {
    const f = this.filter();
    if (f === 'all') return t.points;
    if (f === 'pending') { const ids = new Set(this.pendingTags(t).map((r) => r.id)); return t.points.filter((p) => ids.has(p.id)); }
    return t.points.filter((p) => p.kind === f);
  }

  // ---------- suggestions ----------

  private saved(t: TopicEdit): Record<string, Point> {
    return Object.fromEntries((JSON.parse(t.savedPoints) as Point[]).map((p) => [p.id, p]));
  }

  private refOf(s: any) { return s.paragraph ? `${s.paragraph} (${this.doc(s.document)})` : undefined; }
  doc(d: string | undefined) { return (d ?? '').replace(/\s*\((Standard|Supporting)\)\s*$/, ''); }

  /** Key points whose suggestion would change the saved rubric and is not yet decided. */
  private openSuggestions(t: TopicEdit) {
    const sug = t.suggestions?.points ?? {};
    const orig = this.saved(t);
    const present = new Set(t.points.map((p) => p.id));
    const merged = new Set(this.mergeRows(t).filter((r) => r.decision === 'accepted').flatMap((r) => r.m.ids as string[]));
    return Object.entries<any>(sug)
      .filter(([id, s]) => !s.status && !t.decisions['point:' + id] && orig[id] && present.has(id) && !merged.has(id)
                           && (s.tag !== orig[id].kind || (s.tag !== 'beyond_standard' && this.refOf(s) && this.refOf(s) !== orig[id].ref)))
      .map(([id, s]) => ({ id, s, orig: orig[id] }));
  }

  /** Pending suggestions that change a tag (or are flagged Check): shown on their row. Paragraph-only ones go with Accept all. */
  pendingTags(t: TopicEdit) { return this.openSuggestions(t).filter((r) => r.s.tag !== r.orig.kind || !r.s.found); }
  pendingTag(t: TopicEdit, id: string) { return this.pendingTags(t).find((r) => r.id === id)?.s ?? null; }

  pendingCount(t: TopicEdit) {
    return this.pendingTags(t).length + this.mergeRows(t).filter((r) => !r.decision).length + (t.suggestions?.facts && !this.factsDecision(t) ? 1 : 0);
  }

  mergeRows(t: TopicEdit): { m: any; i: number; decision: Decision | null; saved: boolean }[] {
    const orig = this.saved(t);
    return (t.suggestions?.merges ?? []).map((m: any, i: number) => ({ m, i, decision: (t.decisions['merge:' + i] ?? m.status ?? null) as Decision | null, saved: !!m.status }))
      .filter((r: any) => r.saved || r.m.ids.every((id: string) => orig[id]));
  }

  factsDecision(t: TopicEdit): Decision | null { return t.decisions['facts'] ?? t.suggestions?.facts?.status ?? null; }

  private decide(t: TopicEdit, key: string, d: Decision | null) {
    const next = { ...t.decisions };
    if (d) next[key] = d; else delete next[key];
    t.decisions = next;
    this.refresh();
  }

  acceptPoint(t: TopicEdit, id: string) {
    const s = t.suggestions.points[id];
    const p = t.points.find((x) => x.id === id);
    if (!p) return;
    p.kind = s.tag;
    const ref = s.tag === 'beyond_standard' ? undefined : this.refOf(s);
    if (ref) p.ref = ref; else delete p.ref;
    this.decide(t, 'point:' + id, 'accepted');
  }

  rejectPoint(t: TopicEdit, id: string) { this.decide(t, 'point:' + id, 'rejected'); }

  acceptMerge(t: TopicEdit, i: number) {
    const m = t.suggestions.merges[i];
    const at = t.points.findIndex((p) => m.ids.includes(p.id));
    if (at < 0) return;
    t.points = t.points.filter((p) => !m.ids.includes(p.id));
    t.points.splice(at, 0, { id: m.ids[0], point: m.point, kind: m.tag });
    for (const id of m.ids) this.decide(t, 'point:' + id, 'rejected');  // their own tag suggestions no longer apply
    this.decide(t, 'merge:' + i, 'accepted');
  }

  rejectMerge(t: TopicEdit, i: number) { this.decide(t, 'merge:' + i, 'rejected'); }

  acceptFacts(t: TopicEdit) {
    t.facts = t.suggestions.facts.items.map((f: any) => ({ id: f.id, fact: f.fact, ...(f.tag ? { kind: f.tag } : {}),
                                                         ...(f.tag !== 'beyond_standard' && this.refOf(f) ? { ref: this.refOf(f) } : {}) }));
    this.decide(t, 'facts', 'accepted');
  }

  rejectFacts(t: TopicEdit) { this.decide(t, 'facts', 'rejected'); }

  /** Every pending suggestion of the topic: merges first (they replace points), then tags and paragraphs, then the fact list. */
  acceptAll(t: TopicEdit) {
    for (const r of this.mergeRows(t)) if (!r.decision) this.acceptMerge(t, r.i);
    for (const r of this.openSuggestions(t)) this.acceptPoint(t, r.id);
    if (t.suggestions?.facts && !this.factsDecision(t)) this.acceptFacts(t);
  }

  // ---------- what changed ----------

  private mergedAway(t: TopicEdit, id: string) {
    return this.mergeRows(t).some((r) => t.decisions['merge:' + r.i] === 'accepted' && r.m.ids.includes(id));
  }

  /** How a key point differs from the saved rubric: major (tag, wording, merge) and minor (only its backing paragraph). */
  pointChange(t: TopicEdit, p: Point): { major: string; minor: string; kinds: string[] } {
    const o = this.saved(t)[p.id];
    const merge = this.mergeRows(t).find((r) => t.decisions['merge:' + r.i] === 'accepted' && r.m.ids[0] === p.id);
    if (merge) return { major: `Merged from ${merge.m.ids.join(', ')}`, minor: '', kinds: ['merge'] };
    if (!o) return { major: 'New point', minor: '', kinds: ['new'] };
    const major = [], kinds = [];
    if (o.kind !== p.kind) { major.push(`Tag ${this.shortTag[o.kind]} → ${this.shortTag[p.kind]}`); kinds.push('tag'); }
    if (o.point !== p.point) { major.push('Wording edited'); kinds.push('wording'); }
    let minor = '';
    if ((o.ref ?? '') !== (p.ref ?? '') && p.kind !== 'beyond_standard') {
      minor = p.ref ? `Paragraph ${p.ref} added` : 'Paragraph removed';
      if (!major.length) kinds.push('paragraph');
    }
    return { major: major.join(' · '), minor, kinds };
  }

  factChanged(t: TopicEdit, f: Fact) {
    const saved = (JSON.parse(t.savedFacts) as Fact[] | null) ?? [];
    const o = saved.find((x) => x.id === f.id);
    return !o || JSON.stringify(o) !== JSON.stringify(f);
  }

  /** The topic's unsaved changes, counted by kind: "3 tag changes", "1 merge", "11 paragraphs added", ... */
  changes(t: TopicEdit): string[] {
    const n: Record<string, number> = {};
    const add = (k: string) => (n[k] = (n[k] ?? 0) + 1);
    const orig = this.saved(t);
    const now = new Set(t.points.map((p) => p.id));
    for (const p of t.points) this.pointChange(t, p).kinds.forEach(add);
    for (const id of Object.keys(orig)) if (!now.has(id) && !this.mergedAway(t, id)) add('deleted');
    const rejected = Object.entries(t.decisions).filter(([k, v]) => v === 'rejected' && !(k.startsWith('point:') && this.mergedAway(t, k.slice(6)))).length;
    const word = (c: number, one: string, many: string) => `${c} ${c === 1 ? one : many}`;
    const out = [];
    if (n['tag']) out.push(word(n['tag'], 'tag change', 'tag changes'));
    if (n['merge']) out.push(word(n['merge'], 'merge', 'merges'));
    if (n['wording']) out.push(word(n['wording'], 'wording edit', 'wording edits'));
    if (n['new']) out.push(word(n['new'], 'new point', 'new points'));
    if (n['deleted']) out.push(word(n['deleted'], 'point deleted', 'points deleted'));
    if (n['paragraph']) out.push(word(n['paragraph'], 'paragraph added', 'paragraphs added'));
    if (this.dirtyFacts(t)) {
      const replaced = t.decisions['facts'] === 'accepted';
      out.push(replaced && !(t.facts ?? []).length ? 'fact list emptied (no hard facts in the reference)' : replaced ? 'fact list replaced' : 'facts edited');
    }
    if (rejected) out.push(word(rejected, 'suggestion rejected', 'suggestions rejected'));
    return out;
  }

  /** Put one key point back as saved (a merged point: its original points), with its suggestion undecided again. */
  undoPoint(t: TopicEdit, id: string) {
    const orig = this.saved(t);
    const merge = this.mergeRows(t).find((r) => t.decisions['merge:' + r.i] === 'accepted' && r.m.ids[0] === id);
    if (merge) {
      const at = t.points.findIndex((p) => p.id === id);
      t.points = t.points.filter((p) => p.id !== id);
      t.points.splice(at < 0 ? t.points.length : at, 0, ...merge.m.ids.map((x: string) => structuredClone(orig[x])));
      for (const x of merge.m.ids) this.decide(t, 'point:' + x, null);
      this.decide(t, 'merge:' + merge.i, null);
      return;
    }
    const i = t.points.findIndex((x) => x.id === id);
    if (i >= 0 && orig[id]) t.points[i] = structuredClone(orig[id]);
    this.decide(t, 'point:' + id, null);
  }

  // ---------- editing ----------

  removePoint(t: TopicEdit, p: Point) { t.points = t.points.filter((x) => x !== p); this.editing.set(''); this.refresh(); }
  removeFact(t: TopicEdit, f: Fact) { t.facts = (t.facts ?? []).filter((x) => x !== f); this.editing.set(''); this.refresh(); }

  addFact(t: TopicEdit) {
    const used = new Set((t.facts ?? []).map((f) => f.id));
    let i = 1;
    while (used.has(`F${i}`)) i++;
    t.facts = [...(t.facts ?? []), { id: `F${i}`, fact: '' }];
    this.editing.set(`${t.n}:F${i}`);
    this.refresh();
  }

  undo(t: TopicEdit) {
    t.points = JSON.parse(t.savedPoints);
    t.facts = JSON.parse(t.savedFacts);
    t.decisions = {};
    this.editing.set('');
    this.refresh();
  }

  /** Approve the topic's key points and fact list (a change makes a new version), then go to the next topic not approved. */
  async approve(t: TopicEdit) {
    t.busy = true;
    t.error = '';
    this.editing.set('');
    this.refresh();
    try {
      const facts = t.facts === null ? null : t.facts.filter((f) => f.fact.trim());
      const row = await this.api.put<any>(`/api/bench/rubrics/${enc(this.ref())}/topics/${t.n}`, {
        key_points: t.points.map((p) => ({ id: p.id, point: p.point.trim(), kind: p.kind, ...(p.ref ? { ref: p.ref } : {}) })),
        facts, approve_points: true, approve_facts: facts !== null, decisions: t.decisions,
      });
      const next = this.edit(row);
      next.title = t.title;
      this.topics.update((ts) => ts.map((x) => (x.n === t.n ? next : x)));
      const all = this.topics();
      const i = all.findIndex((x) => x.n === t.n);
      const after = [...all.slice(i + 1), ...all.slice(0, i)].find((x) => this.status(x) !== 'approved');
      if (after) this.go(after.n);
    } catch (e) {
      t.error = errMsg(e);
      t.busy = false;
      this.refresh();
    }
  }

  // ---------- settings: label, documents, suggestions, exports ----------

  readonly label = signal('');
  readonly renaming = signal(false);
  newLabel = '';
  readonly documents = signal<any[]>([]);
  readonly savedTicks = signal<string[] | null>(null);
  readonly ticks = signal<Set<string>>(new Set());

  exportUrl(suggestions = false) {
    return `/api/bench/rubrics/${enc(this.ref())}/export.docx?${new URLSearchParams({ suggestions: String(suggestions) })}`;
  }

  tick(slug: string, on: boolean) {
    const s = new Set(this.ticks());
    if (on) s.add(slug); else s.delete(slug);
    this.ticks.set(s);
  }

  resetTicks() { this.ticks.set(new Set(this.savedTicks() ?? this.documents().map((d) => d.slug))); }

  ticksChanged() {
    const saved = this.savedTicks() ?? this.documents().map((d) => d.slug);
    const now = this.ticks();
    return saved.length !== now.size || saved.some((s) => !now.has(s));
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
    } catch (e) { this.error.set(errMsg(e)); }
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
          return f && t.facts === null && f.facts !== null && !this.dirtyPoints(t) && !this.pending(t) ? this.edit(f) : t;
        }));
        this.makingFacts.set(d.making_facts);
        if (!d.making_facts && this.factsTimer) { clearInterval(this.factsTimer); this.factsTimer = null; }
      } catch { /* try again on the next tick */ }
    }, 4000);
  }

  readonly suggesting = signal(false);
  readonly suggestedCount = computed(() => this.topics().filter((t) => t.suggestions).length);
  private sugTimer: ReturnType<typeof setInterval> | null = null;

  async suggest() {
    this.error.set('');
    try {
      await this.api.post(`/api/bench/rubrics/${enc(this.ref())}/suggest`, { topics: '' });
      this.suggesting.set(true);
      this.watchSuggestions();
    } catch (e) { this.error.set(errMsg(e)); }
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
}
