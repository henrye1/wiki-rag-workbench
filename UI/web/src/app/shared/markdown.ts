import { Component, ElementRef, HostListener, computed, inject, input } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { Router } from '@angular/router';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { CitationService } from './citation-service';

const MARK = String.fromCharCode(0xe000); // private-use char: survives markdown rendering untouched
const WIKI_LINK = /\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]/g;
// RAG citation keys: [5.5.3], [B5.5.17], [5.5.15 (a)(i)], [Appendix A: credit loss], [C123]; not markdown links "[x](url)"
const CITE = /\[((?:B|C|BCZ?|IE|IG)?\d+(?:\.\d+)+[A-Z]{0,2}(?:\s*\([^\]]*\))?|Appendix A: [^\]]+|C\d+)\](?!\()/g;

export function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80) || 'page';
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

function humanize(slug: string): string {
  const s = slug.trim().replace(/-/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Renders LLM markdown safely. [[wiki links]] and [para] citations become clickable. */
export function renderMarkdown(text: string, opts: { existing?: Set<string>; titles?: Map<string, string>; cites?: boolean } = {}): string {
  const anchors: string[] = [];
  const stash = (html: string) => `${MARK}${anchors.push(html) - 1}${MARK}`;
  let src = (text ?? '').replace(WIKI_LINK, (_m, target: string, label?: string) => {
    const slug = slugify(target);
    const missing = opts.existing && !opts.existing.has(slug) ? ' missing' : '';
    // Bare [[slug]] links read better as titles: use the known title, else a humanised slug
    const text = label?.trim() || opts.titles?.get(slug) || humanize(target);
    return stash(`<a class="wl${missing}" data-wiki="${esc(slug)}">${esc(text)}</a>`);
  });
  if (opts.cites !== false) {
    src = src.replace(CITE, (_m, key: string) => {
      const ref = key.replace(/\s*\(.*$/, '').trim(); // "5.5.15 (a)(i)" -> "5.5.15"
      return stash(`<a class="cite" data-cite="${esc(ref)}" title="Show source paragraph">${esc(key)}</a>`);
    });
  }
  let html = marked.parse(src, { async: false, gfm: true }) as string;
  html = html.replace(new RegExp(`${MARK}(\\d+)${MARK}`, 'g'), (_m, i) => anchors[+i]);
  html = html.replace(/<blockquote>\s*<p>\[!(\w+)\]\s*/gi, (_m, kind) => `<blockquote class="callout"><p><strong>${esc(kind)}:</strong> `);
  return DOMPurify.sanitize(html);
}

@Component({
  selector: 'app-md',
  template: `<div class="md" [innerHTML]="html()"></div>`,
})
export class Markdown {
  readonly text = input<string>('');
  /** Wiki whose pages [[links]] point to (enables link clicks). */
  readonly wiki = input<string | undefined>(undefined);
  /** Existing page slugs: links to others render as missing. */
  readonly existing = input<Set<string> | undefined>(undefined);
  /** 'drawer' previews linked wiki pages in the side drawer; 'navigate' opens them. */
  readonly wikiLinks = input<'drawer' | 'navigate'>('drawer');
  readonly cites = input(true);
  /** slug -> title, used as link text for bare [[slug]] links. */
  readonly titles = input<Map<string, string> | undefined>(undefined);

  private sanitizer = inject(DomSanitizer);
  private citations = inject(CitationService);
  private router = inject(Router);
  private host = inject(ElementRef);

  // DOMPurify has already sanitised; bypass so Angular keeps our data-* attributes
  readonly html = computed(() =>
    this.sanitizer.bypassSecurityTrustHtml(renderMarkdown(this.text(), { existing: this.existing(), titles: this.titles(), cites: this.cites() })),
  );

  @HostListener('click', ['$event'])
  onClick(ev: MouseEvent) {
    const a = (ev.target as HTMLElement).closest('a') as HTMLAnchorElement | null;
    if (!a || !this.host.nativeElement.contains(a)) return;
    if (a.dataset['cite']) {
      ev.preventDefault();
      this.citations.openRag(a.dataset['cite']);
    } else if (a.dataset['wiki'] && this.wiki()) {
      ev.preventDefault();
      if (this.wikiLinks() === 'navigate') this.router.navigate(['/wiki', this.wiki(), 'pages', a.dataset['wiki']]);
      else this.citations.openWiki(this.wiki()!, a.dataset['wiki']);
    }
  }
}
