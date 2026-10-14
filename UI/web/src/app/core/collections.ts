import { Injectable, inject, signal } from '@angular/core';
import { Api } from './api';

const KEY = 'rag-collection';

/** The RAG collections and the one currently chosen, shared by the Documents, Ask and Bulk pages (remembered per browser). */
@Injectable({ providedIn: 'root' })
export class RagCollections {
  private api = inject(Api);
  readonly list = signal<any[]>([]);
  readonly current = signal<string>(read());

  /** Reload the list; keep the chosen collection if it still exists, else pick the first. */
  async refresh(): Promise<any[]> {
    const list = await this.api.ragCollections();
    this.list.set(list);
    if (!list.some((c) => c.slug === this.current())) this.select(list[0]?.slug ?? '');
    return list;
  }

  select(slug: string) {
    this.current.set(slug);
    try { localStorage.setItem(KEY, slug); } catch { /* storage unavailable: choice lasts for this visit */ }
  }
}

function read(): string {
  try { return localStorage.getItem(KEY) ?? ''; } catch { return ''; }
}
