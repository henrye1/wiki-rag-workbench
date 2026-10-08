import { Injectable, signal } from '@angular/core';

export type CitationTarget = { kind: 'rag'; ref: string } | { kind: 'wiki'; wiki: string; slug: string };

/** Opens the source-viewer drawer for a RAG paragraph citation or a wiki page link. */
@Injectable({ providedIn: 'root' })
export class CitationService {
  readonly target = signal<CitationTarget | null>(null);
  openRag(ref: string) { this.target.set({ kind: 'rag', ref }); }
  openWiki(wiki: string, slug: string) { this.target.set({ kind: 'wiki', wiki, slug }); }
  close() { this.target.set(null); }
}
