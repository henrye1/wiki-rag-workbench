import { DatePipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
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
type Step = 1 | 2 | 3 | 4;

const TAG_LABEL: Record<string, string> = {
  standard: 'Standard (Part A)', supporting: 'Supporting (Part B/C)', beyond_standard: 'Beyond standard',
};

/** Explanations shown in the (i) icons. */
const INFO = {
  page: 'Review the marking rubric one topic at a time. Approved key points and facts are used by every later run, and each run records the rubric version it used. Nothing changes until you approve a topic.',
  progress: 'A topic counts as approved when both its key points and its fact list are approved and nothing has changed since.',
  status: 'To review: nothing decided yet. In progress: some suggestions decided, unsaved changes, or only part of the topic approved. Approved: key points and facts approved.',
  standard: 'Standard (Part A): the point is stated in a Standard\'s own text, including its appendices. Counts in coverage, standard-only coverage and Standard + Supporting coverage.',
  supporting: 'Supporting (Part B/C): stated only in documents published with the Standard (implementation guidance, illustrative examples, basis for conclusions). Counts in coverage and Standard + Supporting coverage, not in standard-only coverage.',
  beyond_standard: 'Beyond standard: practice, regulation or opinion not stated in the source documents. Counts in coverage only.',
  step1: 'Tags: for each key point the judge read the closest paragraphs of the ticked source documents and suggests a tag with the paragraph that backs it. Accept to apply the suggestion; reject to keep the current tag.',
  step2: 'Merges: key points that are only items of one list in the reference can be combined into one point, so a long list does not outweigh core requirements. Only points with the same tag are suggested for merging.',
  step3: 'Facts: the exact-match fact list holds only hard facts (numbers, periods, thresholds, yes/no answers). Exact match scores the share an answer states; Standard-only exact match uses the facts tagged Standard.',
  step4: 'Approve: saves the topic\'s key points and fact list as approved. Any change makes a new rubric version; earlier versions are kept. Suggestions left undecided are not applied.',
  colId: 'The key point\'s identifier, used in grading notes and run results.',
  refOnly: 'Points whose tag stays the same; the judge only adds the paragraph that backs it. They are included in Accept all suggestions.',
  colPoint: 'The key point as the judge grades it: full, partial or missing in each answer.',
  colCurrent: 'The tag saved in the rubric now.',
  colSuggested: 'The tag the judge suggests from the source paragraphs. "Check" means it believes a Standard states this but none of the paragraphs found does.',
  colParagraph: 'The paragraph and document that back the suggested tag. Empty for Beyond standard.',
  colReason: 'The judge\'s reason. "Second look" means its first reason named a paragraph it had not been shown, so it was asked again with that paragraph.',
  colDecision: 'Accept applies the suggestion to this point; Reject keeps the current tag. Decisions are saved when you approve the topic.',
  acceptAll: 'Applies every suggestion for this topic: tags, merges and the suggested fact list. You can then reject single items before approving.',
  showAll: 'Shows every key point, so you can edit its wording or tag, or delete it, not only those with a suggested change.',
  accept: 'Apply this suggestion. Saved when you approve the topic.',
  reject: 'Keep the rubric as it is for this item. If it was accepted, the original is restored.',
  mergeAccept: 'Replace these key points with the single merged point shown.',
  factsUse: 'Replace the current fact list with the suggested hard-fact list. You can still edit, tag or delete single facts.',
  factsKeep: 'Keep the current fact list.',
  addFact: 'Add a fact of your own. Give it a tag so it counts in Standard-only exact match.',
  approve: 'Approve this topic\'s key points and fact list and move to the next topic not yet approved.',
  undo: 'Discard this topic\'s unsaved changes and decisions.',
  prev: 'Previous topic.',
  next: 'Next topic.',
  settings: 'The memo\'s label, the source documents for the tag check, suggestions and exports.',
  rename: 'The memo is shown by this label everywhere; its file name is never shown.',
  docs: 'Suggest changes reads only the ticked documents. A new choice takes effect when you run Suggest changes again and approve; each approved version keeps the documents its tags were checked against.',
  suggest: 'For every key point and fact, the judge reads the closest paragraphs of the ticked documents (found by words and by meaning) and suggests a tag, list merges and a hard-fact list. Replaces earlier suggestions; the rubric itself does not change.',
  makeFacts: 'Make the fact lists still missing, from each topic\'s reference answer.',
  export: 'The saved rubric as a Word document. Unsaved changes are not included.',
  exportSug: 'The saved rubric with every suggestion: current and suggested tag, paragraph, reason, merges and the suggested hard-fact list.',
  version: 'Each saved change makes a new version of the topic; runs record the version they used.',
  checkedAgainst: 'The source documents this topic\'s approved tags were checked against.',
} as const;

@Component({
  selector: 'app-bench-rubric',
  imports: [FormsModule, RouterLink, DatePipe, MatButtonModule, MatButtonToggleModule, MatCheckboxModule, MatFormFieldModule, MatIconModule,
            MatInputModule, MatProgressBarModule, MatSelectModule, MatSlideToggleModule, MatTooltipModule],
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
              <mat-checkbox [checked]="ticks().has(d.slug)" (change)="tick(d.slug, $event.checked)" [matTooltip]="d.title + ' · ' + (d.tier === 'standard' ? 'Standard' : d.tier === 'supporting' ? 'Supporting' : 'other')">{{ d.name }}</mat-checkbox>
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
          <div class="row prog">
            <b>Approved: {{ approvedCount() }} of {{ topics().length }}</b><mat-icon class="info" [matTooltip]="info.progress">info_outline</mat-icon>
          </div>
          <mat-progress-bar mode="determinate" [value]="topics().length ? (100 * approvedCount()) / topics().length : 0" />
          <div class="row legend muted small">Status<mat-icon class="info" [matTooltip]="info.status">info_outline</mat-icon></div>
          <ul>
            @for (t of topics(); track t.n) {
              <li [class.on]="t.n === current()" (click)="go(t.n)" (keydown.enter)="go(t.n)" tabindex="0">
                <span class="num">{{ t.n }}</span><span class="name" [title]="t.title">{{ t.title }}</span>
                <span class="pill" [class.ok]="status(t) === 'approved'" [class.warn]="status(t) === 'progress'">{{ statusLabel[status(t)] }}</span>
              </li>
            }
          </ul>
        </nav>

        @if (topic(); as t) {
          <section class="card main">
            <div class="row">
              <button mat-icon-button (click)="step(-1)" [disabled]="!hasPrev()" [matTooltip]="info.prev"><mat-icon>chevron_left</mat-icon></button>
              <h2 class="grow">{{ t.n }}. {{ t.title }}</h2>
              <span class="pill" [class.ok]="status(t) === 'approved'" [class.warn]="status(t) === 'progress'">{{ statusLabel[status(t)] }}</span>
              <span class="muted small" [matTooltip]="info.version">version {{ t.version }}</span>
              <button mat-icon-button (click)="step(1)" [disabled]="!hasNext()" [matTooltip]="info.next"><mat-icon>chevron_right</mat-icon></button>
            </div>
            <div class="row muted small meta">
              <span>{{ t.points.length }} key points:</span>
              @for (k of tags; track k) { <span class="pill tagpill" [class]="'pill tagpill ' + k" [matTooltip]="tip(k)">{{ count(t, k) }} {{ shortTag[k] }}</span> }
              <span>· {{ t.facts === null ? 'no fact list' : (t.facts.length + ' facts') }}</span>
              <span class="grow"></span>
              <span [matTooltip]="info.checkedAgainst">Tags checked against: {{ t.tagSources ? docNames(t.tagSources) : 'not recorded' }}</span>
            </div>

            <div class="row stepper">
              @for (s of steps; track s.n) {
                <button mat-button class="stepbtn" [class.active]="stepNo() === s.n" (click)="stepNo.set(s.n)">
                  <span class="dot" [class.done]="stepDone(t, s.n)">{{ stepDone(t, s.n) ? '✓' : s.n }}</span> {{ s.label }}
                  @if (stepCount(t, s.n); as c) { <span class="pill">{{ c }}</span> }
                </button>
                <mat-icon class="info" [matTooltip]="tip('step' + s.n)">info_outline</mat-icon>
              }
              <span class="grow"></span>
              @if (anySuggestion(t)) {
                <button mat-stroked-button (click)="acceptAll(t)" [matTooltip]="info.acceptAll"><mat-icon>done_all</mat-icon> Accept all suggestions</button>
              }
            </div>

            @switch (stepNo()) {
              @case (1) {
                <div class="row sub">
                  <span class="muted">{{ changeRows(t).length ? changeRows(t).length + ' key point(s) with a suggested tag change' : 'No tag changes suggested for this topic' }}</span>
                  @if (refRows(t).length && !showAll) {
                    <button mat-button (click)="showRefs = !showRefs" [matTooltip]="info.refOnly">{{ showRefs ? 'Hide' : 'Show' }} {{ refRows(t).length }} paragraph-only suggestion(s)</button>
                  }
                  <span class="grow"></span>
                  <mat-slide-toggle [(ngModel)]="showAll" [matTooltip]="info.showAll">Show all points</mat-slide-toggle>
                </div>
                @if (!showAll) {
                  @if (shownRows(t).length) {
                    <table class="simple">
                      <thead><tr>
                        <th class="id">ID <mat-icon class="info sm" [matTooltip]="info.colId">info_outline</mat-icon></th>
                        <th>Key point <mat-icon class="info sm" [matTooltip]="info.colPoint">info_outline</mat-icon></th>
                        <th class="tagcol">Current <mat-icon class="info sm" [matTooltip]="info.colCurrent">info_outline</mat-icon></th>
                        <th class="tagcol">Suggested <mat-icon class="info sm" [matTooltip]="info.colSuggested">info_outline</mat-icon></th>
                        <th class="para">Paragraph <mat-icon class="info sm" [matTooltip]="info.colParagraph">info_outline</mat-icon></th>
                        <th>Reason <mat-icon class="info sm" [matTooltip]="info.colReason">info_outline</mat-icon></th>
                        <th class="dec">Decision <mat-icon class="info sm" [matTooltip]="info.colDecision">info_outline</mat-icon></th>
                      </tr></thead>
                      <tbody>
                        @for (r of shownRows(t); track r.id) {
                          <tr [class.accepted]="r.decision === 'accepted'" [class.rejected]="r.decision === 'rejected'">
                            <td class="id mono">{{ r.id }}</td>
                            <td>{{ r.point }}</td>
                            <td><span [class]="'pill tagpill ' + r.orig.kind" [matTooltip]="tip(r.orig.kind)">{{ shortTag[r.orig.kind] }}</span></td>
                            <td><span [class]="'pill tagpill ' + r.s.tag" [matTooltip]="tip(r.s.tag)">{{ shortTag[r.s.tag] }}</span>
                              @if (!r.s.found) { <span class="pill warn" [matTooltip]="info.colSuggested">Check</span> }</td>
                            <td class="small">{{ r.s.paragraph ? r.s.paragraph : '—' }}<div class="muted">{{ r.s.paragraph ? r.s.document : '' }}</div></td>
                            <td class="small">{{ r.s.reason }}
                              @if (r.s.second_look) { <span class="pill" [matTooltip]="info.colReason">Second look: {{ r.s.second_look.join(', ') }}</span> }</td>
                            <td class="dec">
                              @if (r.saved) { <span class="pill" [class.ok]="r.decision === 'accepted'">{{ r.decision === 'accepted' ? 'Accepted' : 'Rejected' }} (saved)</span> }
                              @else {
                                <button mat-button class="small-btn" [class.on]="r.decision === 'accepted'" (click)="acceptPoint(t, r.id)" [matTooltip]="info.accept">Accept</button>
                                <button mat-button class="small-btn" [class.on]="r.decision === 'rejected'" (click)="rejectPoint(t, r.id)" [matTooltip]="info.reject">Reject</button>
                              }
                            </td>
                          </tr>
                        }
                      </tbody>
                    </table>
                  }
                } @else {
                  <table class="simple">
                    <thead><tr><th class="id">ID <mat-icon class="info sm" [matTooltip]="info.colId">info_outline</mat-icon></th>
                      <th>Key point <mat-icon class="info sm" [matTooltip]="info.colPoint">info_outline</mat-icon></th>
                      <th class="tagsel-col">Tag <mat-icon class="info sm" [matTooltip]="info.colCurrent">info_outline</mat-icon></th><th></th></tr></thead>
                    <tbody>
                      @for (p of t.points; track p.id) {
                        <tr>
                          <td class="id mono">{{ p.id }}</td>
                          <td><textarea class="edit autosize" rows="1" [(ngModel)]="p.point"></textarea>
                            @if (p.ref) { <div class="muted small">Backed by {{ p.ref }}</div> }</td>
                          <td><mat-select [(ngModel)]="p.kind" class="tagsel">
                            @for (k of tags; track k) { <mat-option [value]="k">{{ tagLabel[k] }}</mat-option> }
                          </mat-select></td>
                          <td><button mat-icon-button (click)="removePoint(t, p)" matTooltip="Delete this key point. Saved when you approve the topic."><mat-icon>delete</mat-icon></button></td>
                        </tr>
                      }
                    </tbody>
                  </table>
                }
              }
              @case (2) {
                @if (mergeRows(t).length) {
                  @for (r of mergeRows(t); track r.i) {
                    <div class="item" [class.accepted]="r.decision === 'accepted'" [class.rejected]="r.decision === 'rejected'">
                      <div class="row">
                        <span class="mono">{{ r.m.ids.join(', ') }}</span><mat-icon>arrow_forward</mat-icon>
                        <span [class]="'pill tagpill ' + r.m.tag" [matTooltip]="tip(r.m.tag)">{{ shortTag[r.m.tag] }}</span>
                        <span class="grow"></span>
                        @if (r.saved) { <span class="pill">{{ r.decision === 'accepted' ? 'Accepted' : 'Rejected' }} (saved)</span> }
                        @else {
                          <button mat-button class="small-btn" [class.on]="r.decision === 'accepted'" (click)="acceptMerge(t, r.i)" [matTooltip]="info.mergeAccept">Accept</button>
                          <button mat-button class="small-btn" [class.on]="r.decision === 'rejected'" (click)="rejectMerge(t, r.i)" [matTooltip]="info.reject">Reject</button>
                        }
                      </div>
                      <div>“{{ r.m.point }}”</div>
                      <div class="muted small">{{ r.m.reason }}</div>
                      <ul class="small muted">@for (id of r.m.ids; track id) { <li><span class="mono">{{ id }}</span> {{ origPoint(t, id)?.point }}</li> }</ul>
                    </div>
                  }
                } @else { <p class="muted">No merges suggested for this topic.</p> }
              }
              @case (3) {
                @if (t.suggestions?.facts; as sf) {
                  @let fd = factsDecision(t);
                  <div class="item" [class.accepted]="fd === 'accepted'" [class.rejected]="fd === 'rejected'">
                    <div class="row"><b>Suggested hard-fact list</b><span class="muted small">({{ sf.items.length }})</span>
                      <span class="grow"></span>
                      @if (sf.status) { <span class="pill">{{ sf.status === 'accepted' ? 'Used' : 'Kept current' }} (saved)</span> }
                      @else {
                        <button mat-button class="small-btn" [class.on]="fd === 'accepted'" (click)="acceptFacts(t)" [matTooltip]="info.factsUse">Use this list</button>
                        <button mat-button class="small-btn" [class.on]="fd === 'rejected'" (click)="rejectFacts(t)" [matTooltip]="info.factsKeep">Keep current</button>
                      }
                    </div>
                    @if (sf.items.length) {
                      <table class="simple">
                        <tbody>
                          @for (f of sf.items; track f.id) {
                            <tr><td class="id mono">{{ f.id }}</td><td>{{ f.fact }}</td>
                              <td><span [class]="'pill tagpill ' + f.tag" [matTooltip]="tip(f.tag)">{{ shortTag[f.tag] ?? '—' }}</span></td>
                              <td class="small">{{ f.paragraph || '—' }}<div class="muted">{{ f.paragraph ? f.document : '' }}</div></td></tr>
                          }
                        </tbody>
                      </table>
                    } @else { <p class="muted small">The reference answer has no hard facts for this topic; using this list leaves it empty, so exact match is not measured for the topic.</p> }
                  </div>
                }
                <div class="row sub"><b>Fact list</b><span class="muted small">{{ t.facts === null ? '(not made yet)' : '(' + t.facts.length + ')' }}</span>
                  @if (t.facts_reviewed_at && !dirtyFacts(t)) { <span class="pill ok">approved {{ t.facts_reviewed_at | date: 'd MMM y' }}</span> }</div>
                @for (f of t.facts ?? []; track f.id) {
                  <div class="row fact"><span class="id mono">{{ f.id }}</span>
                    <textarea class="edit grow autosize" rows="1" [(ngModel)]="f.fact"></textarea>
                    <mat-select [(ngModel)]="f.kind" class="tagsel" placeholder="Tag">
                      @for (k of tags; track k) { <mat-option [value]="k">{{ tagLabel[k] }}</mat-option> }
                    </mat-select>
                    <button mat-icon-button (click)="removeFact(t, f)" matTooltip="Delete this fact. Saved when you approve the topic."><mat-icon>delete</mat-icon></button></div>
                }
                <button mat-stroked-button (click)="addFact(t)" [matTooltip]="info.addFact"><mat-icon>add</mat-icon> Add fact</button>
              }
              @case (4) {
                @let sm = summary(t);
                <table class="simple summary">
                  <tbody>
                    <tr><td>Tag suggestions</td><td>{{ sm.tags.accepted }} accepted · {{ sm.tags.rejected }} rejected · {{ sm.tags.open }} undecided</td></tr>
                    <tr><td>Merges</td><td>{{ sm.merges.accepted }} accepted · {{ sm.merges.rejected }} rejected · {{ sm.merges.open }} undecided</td></tr>
                    <tr><td>Fact list</td><td>{{ sm.facts }}</td></tr>
                    <tr><td>Key points after approval</td><td>{{ t.points.length }}: {{ count(t, 'standard') }} Standard · {{ count(t, 'supporting') }} Supporting · {{ count(t, 'beyond_standard') }} Beyond standard</td></tr>
                    <tr><td>Version</td><td>{{ dirtyPoints(t) || dirtyFacts(t) || pending(t) ? 'version ' + (t.version + 1) + ' (new)' : 'version ' + t.version + ' (unchanged)' }}</td></tr>
                  </tbody>
                </table>
                <div class="row actions">
                  <button mat-flat-button (click)="approve(t)" [disabled]="t.busy || !t.points.length" [matTooltip]="info.approve">
                    <mat-icon>check</mat-icon> Approve topic</button>
                  @if (dirtyPoints(t) || dirtyFacts(t) || pending(t)) {
                    <button mat-button (click)="undo(t)" [matTooltip]="info.undo">Discard changes</button>
                  }
                </div>
              }
            }
            @if (t.error) { <p class="error">{{ t.error }}</p> }

            <div class="row nav">
              <button mat-button (click)="step(-1)" [disabled]="!hasPrev()" [matTooltip]="info.prev"><mat-icon>chevron_left</mat-icon> Previous</button>
              <span class="grow"></span>
              @if (stepNo() < 4) { <button mat-stroked-button (click)="stepNo.set(nextStep())">Next step</button> }
              <button mat-button (click)="step(1)" [disabled]="!hasNext()" [matTooltip]="info.next">Next <mat-icon iconPositionEnd>chevron_right</mat-icon></button>
            </div>
          </section>
        }
      </div>
    </div>
  `,
  styles: `
    .loading { margin-bottom: 8px; } .title h1 { margin: 0; } .title { margin: 4px 0 12px; } .memo { min-width: 240px; }
    .info { font-size: 18px; width: 18px; height: 18px; color: var(--mat-sys-on-surface-variant); cursor: help; vertical-align: middle; }
    .info.sm { font-size: 15px; width: 15px; height: 15px; }
    .settings { margin-bottom: 12px; } .settings .docs { margin-top: 8px; gap: 4px 14px; }
    .layout { display: grid; grid-template-columns: 1fr; gap: 16px; align-items: start; }
    .side { max-height: 260px; overflow: auto; padding: 12px; }  /* one column: a short scrolling list above the topic */
    @media (min-width: 1200px) {  /* side by side (the app's own menu takes 220px): the list stays in view */
      .layout { grid-template-columns: 290px minmax(0, 1fr); }
      .side { position: sticky; top: 8px; max-height: calc(100vh - 24px); }
    }
    .main { min-width: 0; } .main table { display: block; overflow-x: auto; }
    .side .prog { gap: 4px; margin-bottom: 6px; } .side .legend { gap: 2px; margin: 8px 0 2px; }
    .side ul { list-style: none; margin: 0; padding: 0; }
    .side li { display: grid; grid-template-columns: 22px 1fr auto; gap: 6px; align-items: center; padding: 6px 6px; border-radius: 8px; cursor: pointer; font-size: 13px; }
    .side li:hover { background: var(--mat-sys-surface-container); } .side li.on { background: var(--mat-sys-secondary-container); }
    .side .num { color: var(--mat-sys-on-surface-variant); text-align: right; } .side .name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .main h2 { margin: 0; font: var(--mat-sys-title-large); } .meta { gap: 6px; margin: 2px 0 10px; }
    .stepper { gap: 2px; border-bottom: 1px solid var(--mat-sys-outline-variant); padding-bottom: 8px; margin-bottom: 12px; }
    .stepbtn.active { background: var(--mat-sys-secondary-container); }
    .dot { display: inline-grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; font-size: 12px; margin-right: 4px;
           border: 1px solid var(--mat-sys-outline); } .dot.done { background: #2e7d32; border-color: #2e7d32; color: #fff; }
    .sub { margin: 4px 0 8px; }
    .id { width: 40px; color: var(--mat-sys-on-surface-variant); } .tagcol { width: 120px; } .para { width: 120px; } .dec { width: 150px; white-space: nowrap; }
    .tagsel-col { width: 220px; } .tagsel { width: 200px; }
    .mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; } .small { font-size: 12px; }
    .tagpill.standard { background: color-mix(in srgb, #2e7d32 22%, transparent); }
    .tagpill.supporting { background: color-mix(in srgb, #1565c0 22%, transparent); }
    .tagpill.beyond_standard { background: color-mix(in srgb, #ef6c00 22%, transparent); }
    tr.accepted td { background: color-mix(in srgb, #2e7d32 7%, transparent); } tr.rejected td { opacity: 0.6; }
    .item { border: 1px solid var(--mat-sys-outline-variant); border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; }
    .item.accepted { border-color: #2e7d32; } .item.rejected { opacity: 0.65; } .item ul { margin: 6px 0 0; padding-left: 18px; }
    .small-btn { min-width: 0; padding: 0 8px; } .small-btn.on { background: var(--mat-sys-secondary-container); font-weight: 600; }
    .edit { width: 100%; box-sizing: border-box; background: var(--mat-sys-surface-container); color: inherit;
            border: 1px solid var(--mat-sys-outline-variant); border-radius: 6px; padding: 6px 8px; font: inherit; resize: vertical; }
    .autosize { field-sizing: content; min-height: 0; } .fact { gap: 8px; margin: 4px 0; flex-wrap: nowrap; } .fact .edit { flex: 1; min-width: 0; }
    .summary td:first-child { width: 220px; color: var(--mat-sys-on-surface-variant); } .actions { margin-top: 12px; }
    .nav { margin-top: 16px; border-top: 1px solid var(--mat-sys-outline-variant); padding-top: 8px; }`,
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
  readonly steps: { n: Step; label: string }[] = [{ n: 1, label: 'Tags' }, { n: 2, label: 'Merges' }, { n: 3, label: 'Facts' }, { n: 4, label: 'Approve' }];
  readonly refs = signal<any[]>([]);
  readonly ref = signal('');
  readonly topics = signal<TopicEdit[]>([]);
  readonly error = signal('');
  readonly current = signal(0);
  readonly stepNo = signal<Step>(1);
  readonly showSettings = signal(false);
  readonly loading = signal(true);
  showAll = false;
  showRefs = false;

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

  go(n: number) { this.current.set(n); this.stepNo.set(1); this.showAll = false; this.showRefs = false; }
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

  stepDone(t: TopicEdit, n: Step) {
    if (n === 1) return this.tagRows(t).every((r) => r.decision);
    if (n === 2) return this.mergeRows(t).every((r) => r.decision);
    if (n === 3) return !t.suggestions?.facts || !!this.factsDecision(t);
    return this.status(t) === 'approved';
  }

  stepCount(t: TopicEdit, n: Step) {
    if (n === 1) return this.tagRows(t).filter((r) => !r.decision).length || null;
    if (n === 2) return this.mergeRows(t).filter((r) => !r.decision).length || null;
    return null;
  }

  nextStep(): Step { return Math.min(4, this.stepNo() + 1) as Step; }

  // ---------- suggestions ----------

  private saved(t: TopicEdit): Record<string, Point> {
    return Object.fromEntries((JSON.parse(t.savedPoints) as Point[]).map((p) => [p.id, p]));
  }

  origPoint(t: TopicEdit, id: string) { return this.saved(t)[id]; }

  private refOf(s: any) { return s.paragraph ? `${s.paragraph} (${s.document})` : undefined; }

  /** Key points whose suggestion would change the saved rubric (still shown once decided, so a decision can be changed). */
  tagRows(t: TopicEdit) {
    const sug = t.suggestions?.points ?? {};
    const orig = this.saved(t);
    const present = new Set(t.points.map((p) => p.id));
    const merged = new Set(this.mergeRows(t).filter((r) => r.decision === 'accepted').flatMap((r) => r.m.ids as string[]));
    return Object.entries<any>(sug)
      .filter(([id, s]) => orig[id] && present.has(id) && !merged.has(id)
                           && (s.tag !== orig[id].kind || (this.refOf(s) && this.refOf(s) !== orig[id].ref)))
      .map(([id, s]) => ({ id, s, orig: orig[id], point: t.points.find((p) => p.id === id)!.point,
                           decision: (t.decisions['point:' + id] ?? s.status ?? null) as Decision | null, saved: !!s.status }));
  }

  /** Shown by default: suggestions that change a tag (or are flagged Check); the rest only add the backing paragraph. */
  changeRows(t: TopicEdit) { return this.tagRows(t).filter((r) => r.s.tag !== r.orig.kind || !r.s.found); }
  refRows(t: TopicEdit) { return this.tagRows(t).filter((r) => r.s.tag === r.orig.kind && r.s.found); }
  shownRows(t: TopicEdit) { return this.showRefs ? this.tagRows(t) : this.changeRows(t); }

  mergeRows(t: TopicEdit): { m: any; i: number; decision: Decision | null; saved: boolean }[] {
    const orig = this.saved(t);
    return (t.suggestions?.merges ?? []).map((m: any, i: number) => ({ m, i, decision: (t.decisions['merge:' + i] ?? m.status ?? null) as Decision | null, saved: !!m.status }))
      .filter((r: any) => r.saved || r.m.ids.every((id: string) => orig[id]));
  }

  factsDecision(t: TopicEdit): Decision | null { return t.decisions['facts'] ?? t.suggestions?.facts?.status ?? null; }

  anySuggestion(t: TopicEdit) {
    return this.tagRows(t).some((r) => !r.decision) || this.mergeRows(t).some((r: any) => !r.decision) || (t.suggestions?.facts && !this.factsDecision(t));
  }

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
    const ref = this.refOf(s);
    if (ref) p.ref = ref; else delete p.ref;
    this.decide(t, 'point:' + id, 'accepted');
  }

  rejectPoint(t: TopicEdit, id: string) {
    const o = this.saved(t)[id];
    const p = t.points.find((x) => x.id === id);
    if (p && o) { p.kind = o.kind; if (o.ref) p.ref = o.ref; else delete p.ref; }
    this.decide(t, 'point:' + id, 'rejected');
  }

  acceptMerge(t: TopicEdit, i: number) {
    const m = t.suggestions.merges[i];
    if (t.decisions['merge:' + i] === 'accepted') return;
    const at = t.points.findIndex((p) => m.ids.includes(p.id));
    if (at < 0) return;
    t.points = t.points.filter((p) => !m.ids.includes(p.id));
    t.points.splice(at, 0, { id: m.ids[0], point: m.point, kind: m.tag });
    for (const id of m.ids) this.decide(t, 'point:' + id, 'rejected');  // their own tag suggestions no longer apply
    this.decide(t, 'merge:' + i, 'accepted');
  }

  rejectMerge(t: TopicEdit, i: number) {
    const m = t.suggestions.merges[i];
    if (t.decisions['merge:' + i] === 'accepted') {  // put the original points back where the merged one is
      const orig = this.saved(t);
      const at = t.points.findIndex((p) => p.id === m.ids[0]);
      t.points = t.points.filter((p) => p.id !== m.ids[0]);
      t.points.splice(at < 0 ? t.points.length : at, 0, ...m.ids.map((id: string) => structuredClone(orig[id])));
      for (const id of m.ids) this.decide(t, 'point:' + id, null);
    }
    this.decide(t, 'merge:' + i, 'rejected');
  }

  acceptFacts(t: TopicEdit) {
    const sf = t.suggestions.facts;
    t.facts = sf.items.map((f: any) => ({ id: f.id, fact: f.fact, ...(f.tag ? { kind: f.tag } : {}), ...(this.refOf(f) ? { ref: this.refOf(f) } : {}) }));
    this.decide(t, 'facts', 'accepted');
  }

  rejectFacts(t: TopicEdit) {
    t.facts = JSON.parse(t.savedFacts);
    this.decide(t, 'facts', 'rejected');
  }

  /** Every suggestion of the topic: merges first (they replace points), then tags, then the fact list. */
  acceptAll(t: TopicEdit) {
    for (const r of this.mergeRows(t)) if (!r.decision) this.acceptMerge(t, r.i);
    for (const r of this.tagRows(t)) if (!r.decision) this.acceptPoint(t, r.id);
    if (t.suggestions?.facts && !this.factsDecision(t)) this.acceptFacts(t);
  }

  summary(t: TopicEdit) {
    const tally = (rows: { decision: Decision | null }[]) => ({
      accepted: rows.filter((r) => r.decision === 'accepted').length, rejected: rows.filter((r) => r.decision === 'rejected').length,
      open: rows.filter((r) => !r.decision).length });
    const fd = this.factsDecision(t);
    const facts = t.facts === null ? 'not made yet' : `${t.facts.length} fact(s), ${t.facts.filter((f) => f.kind === 'standard').length} tagged Standard`
      + (t.suggestions?.facts ? (fd === 'accepted' ? ' · suggested list used' : fd === 'rejected' ? ' · current list kept' : ' · suggested list undecided') : '');
    return { tags: tally(this.tagRows(t)), merges: tally(this.mergeRows(t)), facts };
  }

  // ---------- editing ----------

  removePoint(t: TopicEdit, p: Point) { t.points = t.points.filter((x) => x !== p); this.refresh(); }
  removeFact(t: TopicEdit, f: Fact) { t.facts = (t.facts ?? []).filter((x) => x !== f); this.refresh(); }

  addFact(t: TopicEdit) {
    const used = new Set((t.facts ?? []).map((f) => f.id));
    let i = 1;
    while (used.has(`F${i}`)) i++;
    t.facts = [...(t.facts ?? []), { id: `F${i}`, fact: '' }];
    this.refresh();
  }

  undo(t: TopicEdit) {
    t.points = JSON.parse(t.savedPoints);
    t.facts = JSON.parse(t.savedFacts);
    t.decisions = {};
    this.refresh();
  }

  /** Approve the topic's key points and fact list (a change makes a new version), then go to the next topic not approved. */
  async approve(t: TopicEdit) {
    t.busy = true;
    t.error = '';
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
