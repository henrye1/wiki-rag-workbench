import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatDialog } from '@angular/material/dialog';
import { Api, enc, errMsg } from '../core/api';
import { confirmDialog } from '../shared/confirm-dialog';

interface Skill {
  id?: string;
  name: string;
  description: string;
  instructions: string;
}

const blank = (): Skill => ({ name: '', description: '', instructions: '' });

/** Skills: named instructions a chat on the Ask screen can use (optional). A chat's chosen skills are added to how RAG
 * and the wiki answer; they never change what is searched. */
@Component({
  selector: 'app-skills',
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule],
  template: `
    <div class="page">
      <div class="row head">
        <h1 class="grow">Skills</h1>
        @if (!draft()) { <button mat-flat-button (click)="edit(null)"><mat-icon>add</mat-icon> New skill</button> }
      </div>
      <p class="muted intro">Instructions you can add to a chat on the Ask screen, such as an answer format or a tone. Choose them per chat
        under "Skills (optional)": RAG and the wiki get the same text. They change how the answer is written, never what is searched.</p>

      @if (draft(); as d) {
        <div class="card editor">
          <h3>{{ d.id ? 'Edit skill' : 'New skill' }}</h3>
          <div class="row fields">
            <mat-form-field appearance="outline" class="name"><mat-label>Name</mat-label>
              <input matInput [(ngModel)]="d.name" maxlength="80" /></mat-form-field>
            <mat-form-field appearance="outline" class="grow"><mat-label>Description (optional)</mat-label>
              <input matInput [(ngModel)]="d.description" maxlength="300" /></mat-form-field>
          </div>
          <mat-form-field appearance="outline" class="full"><mat-label>Instructions</mat-label>
            <textarea matInput rows="12" [(ngModel)]="d.instructions" maxlength="20000"
                      placeholder="e.g. Answer in at most three bullet points, then a one-line conclusion."></textarea>
          </mat-form-field>
          <div class="row">
            <button mat-flat-button (click)="save()" [disabled]="busy() || !d.name.trim() || !d.instructions.trim()">Save</button>
            <button mat-button (click)="draft.set(null)">Cancel</button>
            <span class="grow"></span>
            @if (d.id) {
              <button mat-button class="error" (click)="remove(d)" [disabled]="busy()"><mat-icon>delete</mat-icon> Delete</button>
            }
          </div>
        </div>
      }
      @if (msg()) { <p class="muted">{{ msg() }}</p> }
      @if (error()) { <p class="error">{{ error() }}</p> }

      <div class="cards">
        @for (s of skills(); track s.id) {
          <div class="card skill" [class.active]="s.id === draft()?.id" (click)="edit(s)" (keydown.enter)="edit(s)"
               tabindex="0" role="button" title="Edit">
            <button mat-icon-button class="bin" (click)="$event.stopPropagation(); remove(s)" (keydown.enter)="$event.stopPropagation()" [disabled]="busy()"
                    [attr.aria-label]="'Delete ' + s.name" title="Delete"><mat-icon>delete</mat-icon></button>
            <h3>{{ s.name }}</h3>
            @if (s.description) { <p class="muted desc">{{ s.description }}</p> }
            <p class="preview">{{ s.instructions }}</p>
          </div>
        } @empty {
          @if (!draft()) { <p class="muted empty">No skills yet. Add one with New skill.</p> }
        }
      </div>
    </div>
  `,
  styles: `
    .head { margin-bottom: 4px; } .head h1 { margin: 0; }
    .intro { margin: 0 0 16px; max-width: 900px; }
    .editor { margin-bottom: 16px; }
    .fields { align-items: flex-start; }
    .name { width: 280px; }
    .full { width: 100%; }
    .skill { position: relative; cursor: pointer; display: flex; flex-direction: column; gap: 6px; padding-right: 48px; }
    .bin { position: absolute; top: 4px; right: 4px; color: var(--mat-sys-on-surface-variant); }
    .bin:hover { color: var(--mat-sys-error); }
    .skill:hover { border-color: var(--mat-sys-outline); }
    .skill.active { border-color: var(--mat-sys-primary); }
    .skill h3, .skill p { margin: 0; }
    .desc { font-size: 13px; }
    .preview { font-size: 12px; white-space: pre-wrap; color: var(--mat-sys-on-surface-variant); display: -webkit-box;
      -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
    .small { font-size: 12px; }
  `,
})
export class Skills {
  private api = inject(Api);
  private dialog = inject(MatDialog);
  readonly skills = signal<Skill[]>([]);
  readonly draft = signal<Skill | null>(null); // a copy being edited (no id = new)
  readonly busy = signal(false);
  readonly msg = signal('');
  readonly error = signal('');

  constructor() {
    void this.load();
  }

  async load() {
    try { this.skills.set(await this.api.get<Skill[]>('/api/skills')); } catch (e) { this.error.set(errMsg(e)); }
  }

  edit(s: Skill | null) {
    this.draft.set(s ? { ...s } : blank());
    this.msg.set('');
    this.error.set('');
  }

  async save() {
    const d = this.draft();
    if (!d) return;
    this.busy.set(true);
    this.error.set('');
    try {
      const body = { name: d.name, description: d.description, instructions: d.instructions };
      const saved = d.id
        ? await this.api.put<Skill>(`/api/skills/${enc(d.id)}`, body)
        : await this.api.post<Skill>('/api/skills', body);
      await this.load();
      this.draft.set(null);
      this.msg.set(`Saved "${saved.name}". Chats using it use the new text from their next question.`);
    } catch (e) {
      this.error.set(errMsg(e));
    } finally {
      this.busy.set(false);
    }
  }

  /** Delete a skill after the user confirms it in a modal. */
  async remove(d: Skill) {
    const ok = await confirmDialog(this.dialog, {
      title: `Delete "${d.name}"?`,
      message: 'This permanently deletes the skill. Chats that use it stop using it; their past answers are kept.',
    });
    if (!ok) return;
    this.busy.set(true);
    this.error.set('');
    try {
      await this.api.delete(`/api/skills/${enc(d.id!)}`);
      if (this.draft()?.id === d.id) this.draft.set(null);
      this.msg.set(`Deleted "${d.name}".`);
      await this.load();
    } catch (e) {
      this.error.set(errMsg(e));
    } finally {
      this.busy.set(false);
    }
  }
}
