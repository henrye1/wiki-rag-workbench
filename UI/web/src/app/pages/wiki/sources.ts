import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, effect, inject, input, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatTabsModule } from '@angular/material/tabs';
import { RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../../core/api';
import { FileDrop } from '../../shared/file-drop';

@Component({
  selector: 'app-wiki-sources',
  imports: [FormsModule, RouterLink, DatePipe, DecimalPipe, MatButtonModule, MatButtonToggleModule, MatFormFieldModule, MatIconModule,
    MatInputModule, MatTabsModule, FileDrop],
  template: `
    <div class="card">
      <div class="row">
        <h3 class="grow">Add a source</h3>
        <mat-button-toggle-group [(ngModel)]="mode" aria-label="Mode">
          <mat-button-toggle value="review">Review changes first</mat-button-toggle>
          <mat-button-toggle value="auto">Apply automatically</mat-button-toggle>
        </mat-button-toggle-group>
      </div>
      <mat-tab-group [(selectedIndex)]="tab" animationDuration="0">
        <mat-tab label="File">
          <div class="pad row">
            <app-file-drop class="grow" accept=".pdf,.docx,.md,.txt" label="PDF, DOCX, MD or TXT" (picked)="pick($event)" />
            <button mat-flat-button (click)="submitFile()" [disabled]="!file() || busy() || describing()">Ingest</button>
          </div>
          @if (file()) {
            <div class="row doc">
              <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic"><mat-label>Title (optional)</mat-label><input matInput [(ngModel)]="fileTitle" placeholder="Leave blank to read it from the cover" /></mat-form-field>
              <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic"><mat-label>Issuer</mat-label><input matInput [(ngModel)]="issuer" /></mat-form-field>
              <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic"><mat-label>Edition</mat-label><input matInput [(ngModel)]="edition" /></mat-form-field>
              <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic"><mat-label>Part</mat-label><input matInput [(ngModel)]="part" /></mat-form-field>
              <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic"><mat-label>Status (optional)</mat-label><input matInput [(ngModel)]="status" placeholder="e.g. Draft, Approved" /></mat-form-field>
              <mat-icon class="muted" title="Read from the file's opening pages where they state it. Check each field before ingesting; leave a field blank if the document does not state it. The source page is checked against these values.">info</mat-icon>
            </div>
            @if (describing()) { <p class="muted">Reading the title page…</p> }
          }
        </mat-tab>
        <mat-tab label="URL">
          <div class="pad row">
            <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic"><mat-label>URL</mat-label><input matInput [(ngModel)]="url" /></mat-form-field>
            <button mat-flat-button (click)="submitUrl()" [disabled]="!url || busy()">Ingest</button>
          </div>
        </mat-tab>
        <mat-tab label="Text">
          <div class="pad">
            <mat-form-field appearance="outline" class="full" subscriptSizing="dynamic"><mat-label>Title</mat-label><input matInput [(ngModel)]="title" /></mat-form-field>
            <mat-form-field appearance="outline" class="full"><mat-label>Text</mat-label><textarea matInput rows="6" [(ngModel)]="text"></textarea></mat-form-field>
            <button mat-flat-button (click)="submitText()" [disabled]="!title || text.length < 20 || busy()">Ingest</button>
          </div>
        </mat-tab>
      </mat-tab-group>
      @if (started(); as s) {
        <p>Started ingest of <b>{{ s.title }}</b> ({{ s.sections }} sections, {{ s.mode }} mode). <a [routerLink]="['..', 'jobs']">Follow the job →</a></p>
      }
      @if (started()?.warnings?.length) { @for (w of started().warnings; track w) { <p class="warn"><b>Warning:</b> {{ w }}</p> } }
      @if (error()) { <p class="error">{{ error() }}</p> }
    </div>

    <h3>Sources</h3>
    <table class="simple">
      <thead><tr><th>Title</th><th>Kind</th><th>Size</th><th>Added</th><th></th></tr></thead>
      <tbody>
        @for (s of sources(); track s.id) {
          <tr>
            <td><a [routerLink]="['..', 'pages', s.slug]">{{ s.title }}</a><div class="muted mono">{{ s.uri }}</div>
              @if (s.meta?.document; as d) { <div class="muted">{{ docLine(d) }}</div> }</td>
            <td>{{ s.kind }}</td><td>{{ s.chars | number }} chars</td><td>{{ s.created_at | date: 'medium' }}</td>
            <td class="actions">
              @if (s.file) { <button mat-icon-button (click)="view(s.slug)" title="View the original file"><mat-icon>open_in_new</mat-icon></button> }
              @if (confirming() === s.slug) {
                <button mat-button class="error" (click)="remove(s.slug)">Confirm</button><button mat-button (click)="confirming.set(null)">Cancel</button>
              } @else { <button mat-icon-button (click)="confirming.set(s.slug)" title="Delete raw source (pages are kept)"><mat-icon>delete</mat-icon></button> }
            </td>
          </tr>
        } @empty { <tr><td colspan="5" class="muted empty">No sources yet.</td></tr> }
      </tbody>
    </table>
  `,
  styles: `.pad { padding: 12px 0; } .actions { white-space: nowrap; } .doc { gap: 12px; align-items: center; padding-bottom: 8px; }`,
})
export class WikiSources {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly drop = viewChild(FileDrop);
  readonly sources = signal<any[]>([]);
  readonly file = signal<File | null>(null);
  readonly busy = signal(false);
  readonly started = signal<any>(null);
  readonly error = signal('');
  readonly confirming = signal<string | null>(null);
  readonly describing = signal(false);
  mode: 'auto' | 'review' = 'review';
  tab = 0;
  url = '';
  title = '';
  text = '';
  issuer = '';
  edition = '';
  part = '';
  status = '';
  fileTitle = '';

  constructor() { effect(() => { void this.load(this.w()); }); }

  async load(w: string) { this.sources.set(await this.api.get(`/api/wiki/wikis/${enc(w)}/sources`)); }

  private async submit(fn: () => Promise<any>) {
    this.busy.set(true);
    this.error.set('');
    this.started.set(null);
    try {
      this.started.set(await fn());
      await this.load(this.w());
    } catch (e) {
      this.error.set(errMsg(e));
    } finally {
      this.busy.set(false);
    }
  }
  docLine(d: any) { return [d.issuer, d.edition, d.part, d.status].filter((x: string) => !!x).join(' · '); }
  /** A file was picked: suggest its issuer, edition and part from its opening pages, for the user to confirm. */
  async pick(f: File | null) {
    this.file.set(f);
    this.issuer = this.edition = this.part = this.status = this.fileTitle = '';
    if (!f) return;
    this.describing.set(true);
    try {
      const d = await this.api.upload(`/api/wiki/wikis/${enc(this.w())}/sources/describe`, f);
      if (this.file() === f) ({ issuer: this.issuer, edition: this.edition, part: this.part } = d);
    } catch {
      // no suggestion: the fields stay empty for the user to fill in
    } finally {
      this.describing.set(false);
    }
  }
  submitFile() {
    return this.submit(async () => {
      const r = await this.api.upload(`/api/wiki/wikis/${enc(this.w())}/sources`, this.file()!, { mode: this.mode },
        { issuer: this.issuer, edition: this.edition, part: this.part, status: this.status, title: this.fileTitle });
      this.file.set(null);
      this.issuer = this.edition = this.part = this.status = this.fileTitle = '';
      this.drop()?.reset();
      return r;
    });
  }
  submitUrl() { return this.submit(() => this.api.post(`/api/wiki/wikis/${enc(this.w())}/sources/url`, { url: this.url }, { mode: this.mode })); }
  submitText() {
    return this.submit(() => this.api.post(`/api/wiki/wikis/${enc(this.w())}/sources/text`, { title: this.title, text: this.text }, { mode: this.mode }));
  }
  async view(slug: string) {
    try {
      await this.api.openFile(`/api/wiki/wikis/${enc(this.w())}/sources/${enc(slug)}/file`);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }
  async remove(slug: string) {
    try {
      await this.api.delete(`/api/wiki/wikis/${enc(this.w())}/sources/${enc(slug)}`);
      this.confirming.set(null);
      await this.load(this.w());
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }
}
