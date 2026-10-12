import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, inject, signal, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Api, enc, errMsg } from '../core/api';
import { FileDrop } from '../shared/file-drop';

@Component({
  selector: 'app-documents',
  imports: [MatButtonModule, MatIconModule, MatProgressBarModule, DatePipe, DecimalPipe, FileDrop],
  template: `
    <div class="page">
      <h1>RAG documents</h1>
      <div class="card">
        <h3>Ingest a document</h3>
        <p class="muted">PDF, TXT or MD. IFRS-layout PDFs are split by paragraph number; other files get generic chunking. Embedding a large PDF takes a minute.</p>
        <div class="row">
          <app-file-drop class="grow" accept=".pdf,.txt,.md" (picked)="file.set($event)" />
          <button mat-flat-button (click)="ingest()" [disabled]="!file() || busy()"><mat-icon>upload</mat-icon> Ingest</button>
        </div>
        @if (busy()) { <mat-progress-bar mode="indeterminate" /> }
        @if (result(); as r) {
          <p>Ingested <b>{{ r.filename }}</b> ({{ r.parser }}): {{ r.chunks }} chunks
            @for (kv of entries(r.by_source_type); track kv[0]) { <span class="pill">{{ kv[0] }} {{ kv[1] }}</span> }</p>
        }
        @if (error()) { <p class="error">{{ error() }}</p> }
      </div>

      <h3>Indexed documents</h3>
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
            } @empty { <tr><td colspan="5" class="muted">No documents yet.</td></tr> }
          </tbody>
        </table>
      </div>
    </div>
  `,
})
export class Documents {
  private api = inject(Api);
  readonly drop = viewChild(FileDrop);
  readonly docs = signal<any[]>([]);
  readonly file = signal<File | null>(null);
  readonly busy = signal(false);
  readonly result = signal<any>(null);
  readonly error = signal('');
  readonly confirming = signal<string | null>(null);

  constructor() { void this.load(); }

  async load() { this.docs.set(await this.api.ragDocuments()); }
  entries(o: Record<string, number>) { return Object.entries(o ?? {}); }

  async ingest() {
    this.busy.set(true);
    this.error.set('');
    this.result.set(null);
    try {
      this.result.set(await this.api.upload('/api/rag/ingest', this.file()!));
      this.file.set(null);
      this.drop()?.reset();
      await this.load();
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
      await this.load();
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }
}
