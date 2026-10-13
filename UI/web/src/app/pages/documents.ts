import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { Api, enc, errMsg } from '../core/api';
import { RagCollections } from '../core/collections';
import { FileDrop } from '../shared/file-drop';

type Editing = 'new' | 'rename' | 'delete' | null;

@Component({
  selector: 'app-documents',
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatProgressBarModule, MatSelectModule,
    DatePipe, DecimalPipe, FileDrop],
  template: `
    <div class="page">
      <h1>RAG documents</h1>
      <div class="card">
        <h3>Collection</h3>
        <p class="muted">Each collection is a separate set of documents. A question searches only the collection you choose.</p>
        <div class="row">
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="col-select"><mat-label>Collection</mat-label>
            <mat-select [ngModel]="cols.current()" (ngModelChange)="choose($event)">
              @for (c of cols.list(); track c.slug) {
                <mat-option [value]="c.slug">{{ c.name }} ({{ c.slug }}) · {{ c.documents }} doc(s)</mat-option>
              }
            </mat-select>
          </mat-form-field>
          <button mat-stroked-button (click)="edit('new')"><mat-icon>add</mat-icon> New</button>
          <button mat-stroked-button (click)="edit('rename')" [disabled]="!cols.current()"><mat-icon>edit</mat-icon> Rename</button>
          <button mat-stroked-button class="error" (click)="edit('delete')" [disabled]="!cols.current()"><mat-icon>delete</mat-icon> Delete</button>
        </div>
        @if (editing() === 'new' || editing() === 'rename') {
          <div class="row form">
            <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Name</mat-label>
              <input matInput [(ngModel)]="name" placeholder="e.g. IFRS 9 with examples" /></mat-form-field>
            <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Slug</mat-label>
              <input matInput [(ngModel)]="slug" placeholder="e.g. ifrs9-examples" /></mat-form-field>
            <button mat-flat-button (click)="save()" [disabled]="!name.trim() || !slug.trim()">{{ editing() === 'new' ? 'Create' : 'Save' }}</button>
            <button mat-button (click)="edit(null)">Cancel</button>
          </div>
          <p class="muted small">Slug: lowercase letters, digits and dashes. It identifies the collection in benchmark runs.</p>
        }
        @if (editing() === 'delete') {
          <p class="error">Deletes collection <b>{{ cols.current() }}</b> with all its documents, their chunks and their stored files. This cannot be undone.</p>
          <div class="row form">
            <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Type {{ cols.current() }} to confirm</mat-label>
              <input matInput [(ngModel)]="confirmSlug" autocomplete="off" /></mat-form-field>
            <button mat-flat-button class="del" (click)="removeCollection()" [disabled]="confirmSlug !== cols.current()">Delete collection</button>
            <button mat-button (click)="edit(null)">Cancel</button>
          </div>
        }
      </div>

      @if (cols.current(); as c) {
        <div class="card">
          <h3>Ingest a document into {{ c }}</h3>
          <p class="muted">PDF, TXT or MD. IFRS-layout PDFs are split by paragraph number; other files get generic chunking. Embedding a large PDF takes a minute.</p>
          <div class="row">
            <app-file-drop class="grow" accept=".pdf,.txt,.md" (picked)="file.set($event)" />
            <button mat-flat-button (click)="ingest()" [disabled]="!file() || busy()"><mat-icon>upload</mat-icon> Ingest</button>
          </div>
          @if (busy()) { <mat-progress-bar mode="indeterminate" /> }
          @if (result(); as r) {
            <p>Ingested <b>{{ r.filename }}</b> into {{ r.collection }} ({{ r.parser }}): {{ r.chunks }} chunks
              @for (kv of entries(r.by_source_type); track kv[0]) { <span class="pill">{{ kv[0] }} {{ kv[1] }}</span> }</p>
          }
        </div>

        <h3>Documents in {{ c }}</h3>
        <div class="scroll-x">
          <table class="simple">
            <thead><tr><th>File</th><th>Parser</th><th>Chunks</th><th>Added</th><th></th></tr></thead>
            <tbody>
              @for (d of docs(); track d.id) {
                <tr>
                  <td>{{ d.filename }}</td><td>{{ d.parser }}</td><td>{{ d.chunks | number }}</td><td>{{ d.created_at | date: 'medium' }}</td>
                  <td class="actions">
                    @if (d.has_file) { <button mat-icon-button (click)="view(d)" title="View the original file"><mat-icon>open_in_new</mat-icon></button> }
                    @if (confirming() === d.id) {
                      <button mat-button class="error" (click)="remove(d)">Confirm delete</button>
                      <button mat-button (click)="confirming.set(null)">Cancel</button>
                    } @else {
                      <button mat-icon-button (click)="confirming.set(d.id)" aria-label="Delete"><mat-icon>delete</mat-icon></button>
                    }
                  </td>
                </tr>
              } @empty { <tr><td colspan="5" class="muted">No documents in this collection yet.</td></tr> }
            </tbody>
          </table>
        </div>
      } @else {
        <p class="muted">No collections yet: create one to start ingesting documents.</p>
      }
      @if (error()) { <p class="error">{{ error() }}</p> }
    </div>
  `,
  styles: `
    .col-select { min-width: 320px; } .form { margin-top: 12px; flex-wrap: wrap; } .small { font-size: 12px; }
    .actions { white-space: nowrap; } .del { background: var(--mat-sys-error); color: var(--mat-sys-on-error); }
  `,
})
export class Documents {
  private api = inject(Api);
  readonly cols = inject(RagCollections);
  readonly drop = viewChild(FileDrop);
  readonly docs = signal<any[]>([]);
  readonly file = signal<File | null>(null);
  readonly busy = signal(false);
  readonly result = signal<any>(null);
  readonly error = signal('');
  readonly confirming = signal<string | null>(null);
  readonly editing = signal<Editing>(null);
  name = '';
  slug = '';
  confirmSlug = '';

  constructor() { void this.reload(); }

  async reload() {
    try {
      await this.cols.refresh();
      await this.load();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async load() {
    const c = this.cols.current();
    this.docs.set(c ? await this.api.ragDocuments(c) : []);
  }

  choose(slug: string) {
    this.cols.select(slug);
    this.result.set(null);
    this.edit(null);
    void this.load();
  }

  entries(o: Record<string, number>) { return Object.entries(o ?? {}); }

  edit(mode: Editing) {
    this.error.set('');
    this.editing.set(mode);
    const cur = this.cols.list().find((c) => c.slug === this.cols.current());
    this.name = mode === 'rename' ? cur?.name ?? '' : '';
    this.slug = mode === 'rename' ? cur?.slug ?? '' : '';
    this.confirmSlug = '';
  }

  async save() {
    this.error.set('');
    try {
      const body = { name: this.name.trim(), slug: this.slug.trim() };
      const c = this.editing() === 'new'
        ? await this.api.post('/api/rag/collections', body)
        : await this.api.patch(`/api/rag/collections/${enc(this.cols.current())}`, body);
      this.cols.select(c.slug);
      this.editing.set(null);
      await this.reload();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async removeCollection() {
    this.error.set('');
    try {
      await this.api.delete(`/api/rag/collections/${enc(this.cols.current())}`);
      this.editing.set(null);
      this.cols.select('');
      await this.reload();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async ingest() {
    this.busy.set(true);
    this.error.set('');
    this.result.set(null);
    try {
      this.result.set(await this.api.upload(`/api/rag/collections/${enc(this.cols.current())}/documents`, this.file()!));
      this.file.set(null);
      this.drop()?.reset();
      await this.reload();
    } catch (e) {
      this.error.set(errMsg(e));
    } finally {
      this.busy.set(false);
    }
  }

  async view(d: any) {
    try {
      await this.api.openFile(`/api/rag/documents/${enc(d.id)}/file`);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async remove(d: any) {
    try {
      await this.api.delete(`/api/rag/documents/${enc(d.id)}`);
      this.confirming.set(null);
      await this.reload();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }
}
