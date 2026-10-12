import { Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { Api, enc, errMsg } from '../../core/api';
import { Markdown } from '../../shared/markdown';

@Component({
  selector: 'app-wiki-settings',
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, Markdown],
  template: `
    <div class="card">
      <div class="row">
        <h3 class="grow">Schema</h3>
        @if (editing()) {
          <button mat-button (click)="editing.set(false); draft = schema()">Cancel</button>
          <button mat-flat-button (click)="save()">Save</button>
        } @else { <button mat-stroked-button (click)="editing.set(true)"><mat-icon>edit</mat-icon> Edit</button> }
      </div>
      <p class="muted">The conventions every LLM call on this wiki follows: page types, link and citation style, contradiction handling.</p>
      @if (editing()) {
        <mat-form-field appearance="outline" class="full"><textarea matInput rows="24" class="mono" [(ngModel)]="draft"></textarea></mat-form-field>
      } @else { <app-md [text]="schema()" [cites]="false" /> }
      @if (msg()) { <p>{{ msg() }}</p> }
    </div>
    <div class="card export">
      <h3>Export</h3>
      <p class="muted">Download the wiki as an Obsidian-compatible vault: pages with YAML front matter, raw sources, index.md, log.md, SCHEMA.md.</p>
      <a mat-flat-button [href]="'/api/wiki/wikis/' + w() + '/export.zip'" download><mat-icon>download</mat-icon> Download zip</a>
      <a mat-button [href]="'/api/wiki/wikis/' + w() + '/index.md'" target="_blank">index.md</a>
      <a mat-button [href]="'/api/wiki/wikis/' + w() + '/log.md'" target="_blank">log.md</a>
    </div>
    <div class="card danger">
      <h3>Delete wiki</h3>
      <p class="muted">Permanently deletes this wiki and everything in it: pages, versions, sources, changesets, jobs and the log. This cannot be undone; download the zip above first if you want a copy.</p>
      @if (deleting()) {
        <mat-form-field appearance="outline">
          <mat-label>Type {{ w() }} to confirm</mat-label>
          <input matInput [(ngModel)]="confirmSlug" autocomplete="off" />
        </mat-form-field>
        <div class="row">
          <button mat-flat-button class="del" [disabled]="confirmSlug !== w() || busy()" (click)="remove()"><mat-icon>delete_forever</mat-icon> Delete wiki</button>
          <button mat-button (click)="deleting.set(false); confirmSlug = ''">Cancel</button>
        </div>
      } @else {
        <button mat-stroked-button class="error" (click)="deleting.set(true)"><mat-icon>delete</mat-icon> Delete this wiki…</button>
      }
      @if (delMsg()) { <p class="error">{{ delMsg() }}</p> }
    </div>
  `,
  styles: `.export, .danger { margin-top: 16px; }
    .del { background: var(--mat-sys-error); color: var(--mat-sys-on-error); }`,
})
export class WikiSettings {
  private api = inject(Api);
  private router = inject(Router);
  readonly w = input.required<string>();
  readonly schema = signal('');
  readonly editing = signal(false);
  readonly msg = signal('');
  readonly deleting = signal(false);
  readonly busy = signal(false);
  readonly delMsg = signal('');
  draft = '';
  confirmSlug = '';

  constructor() {
    effect(() => {
      void this.api.text(`/api/wiki/wikis/${enc(this.w())}/schema`).then((s) => { this.schema.set(s); this.draft = s; });
    });
  }

  async save() {
    try {
      await this.api.put(`/api/wiki/wikis/${enc(this.w())}/schema`, { schema_md: this.draft });
      this.schema.set(this.draft);
      this.editing.set(false);
      this.msg.set('Schema saved. It applies to future ingests, queries and lint runs.');
    } catch (e) {
      this.msg.set(errMsg(e));
    }
  }

  async remove() {
    this.busy.set(true);
    this.delMsg.set('');
    try {
      await this.api.delete(`/api/wiki/wikis/${enc(this.w())}`);
      await this.router.navigate(['/wiki']);
    } catch (e) {
      this.delMsg.set(errMsg(e));
    } finally {
      this.busy.set(false);
    }
  }
}
