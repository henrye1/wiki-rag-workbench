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
            <app-file-drop class="grow" accept=".pdf,.docx,.md,.txt" label="PDF, DOCX, MD or TXT" (picked)="file.set($event)" />
            <button mat-flat-button (click)="submitFile()" [disabled]="!file() || busy()">Ingest</button>
          </div>
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
      @if (error()) { <p class="error">{{ error() }}</p> }
    </div>

    <h3>Sources</h3>
    <table class="simple">
      <thead><tr><th>Title</th><th>Kind</th><th>Size</th><th>Added</th><th></th></tr></thead>
      <tbody>
        @for (s of sources(); track s.id) {
          <tr>
            <td><a [routerLink]="['..', 'pages', s.slug]">{{ s.title }}</a><div class="muted mono">{{ s.uri }}</div></td>
            <td>{{ s.kind }}</td><td>{{ s.chars | number }} chars</td><td>{{ s.created_at | date: 'medium' }}</td>
            <td>
              @if (confirming() === s.slug) {
                <button mat-button class="error" (click)="remove(s.slug)">Confirm</button><button mat-button (click)="confirming.set(null)">Cancel</button>
              } @else { <button mat-icon-button (click)="confirming.set(s.slug)" title="Delete raw source (pages are kept)"><mat-icon>delete</mat-icon></button> }
            </td>
          </tr>
        } @empty { <tr><td colspan="5" class="muted">No sources yet.</td></tr> }
      </tbody>
    </table>
  `,
  styles: `.pad { padding: 12px 0; }`,
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
  mode: 'auto' | 'review' = 'review';
  tab = 0;
  url = '';
  title = '';
  text = '';

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
  submitFile() {
    return this.submit(async () => {
      const r = await this.api.upload(`/api/wiki/wikis/${enc(this.w())}/sources`, this.file()!, { mode: this.mode });
      this.file.set(null);
      this.drop()?.reset();
      return r;
    });
  }
  submitUrl() { return this.submit(() => this.api.post(`/api/wiki/wikis/${enc(this.w())}/sources/url`, { url: this.url }, { mode: this.mode })); }
  submitText() {
    return this.submit(() => this.api.post(`/api/wiki/wikis/${enc(this.w())}/sources/text`, { title: this.title, text: this.text }, { mode: this.mode }));
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
