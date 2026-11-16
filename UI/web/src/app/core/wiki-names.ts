import { Injectable, inject, signal } from '@angular/core';
import { Api } from './api';

const ON = 'hide-wiki-names';
const LIST = 'hidden-wiki-names';

/** Hiding wiki names on screen (for a demonstration or a screen share): a switch, and the wikis whose names it hides,
 * both remembered per browser. Only what is shown changes: names, slugs and data are untouched. A hidden wiki is shown
 * as "Client wiki <n>", numbered in the order the wikis were created, counting hidden wikis only. */
@Injectable({ providedIn: 'root' })
export class WikiNames {
  private api = inject(Api);
  readonly on = signal<boolean>(read(ON) === '1');
  readonly hidden = signal<Set<string>>(new Set(readList()));
  private readonly order = signal<string[]>([]); // every wiki's slug, oldest first

  /** Reload the wikis' order (for the numbering). */
  async refresh() {
    try { this.order.set((await this.api.wikis()).map((w) => w.slug)); } catch { /* not signed in yet: numbered later */ }
  }

  /** Whether this wiki's name is hidden now. */
  masked(slug: string | null | undefined): boolean { return !!slug && this.on() && this.hidden().has(slug); }

  /** What to show for a wiki: its name (or the given fallback), or "Client wiki <n>" while hidden. */
  name(slug: string | null | undefined, name?: string | null): string {
    if (!this.masked(slug)) return name ?? slug ?? '';
    const n = this.order().filter((s) => this.hidden().has(s)).indexOf(slug!) + 1;
    return n ? `Client wiki ${n}` : 'Client wiki';
  }

  toggle() {
    this.on.set(!this.on());
    write(ON, this.on() ? '1' : '0');
  }

  setHidden(slug: string, hide: boolean) {
    const s = new Set(this.hidden());
    if (hide) s.add(slug); else s.delete(slug);
    this.hidden.set(s);
    write(LIST, JSON.stringify([...s]));
  }
}

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function readList(): string[] {
  try { const v = JSON.parse(read(LIST) ?? '[]'); return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []; }
  catch { return []; }
}

function write(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable: lasts for this visit */ }
}
