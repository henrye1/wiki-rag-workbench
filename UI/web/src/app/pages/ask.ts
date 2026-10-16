import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Api, enc, errMsg } from '../core/api';
import { RagCollections } from '../core/collections';
import { postSse } from '../core/sse';
import { CitationService } from '../shared/citation-service';
import { Markdown } from '../shared/markdown';

type Mode = 'rag' | 'wiki' | 'both';
type Sources = 'standard' | 'all';

interface Pane {
  answer: string;
  running: boolean;
  error: string;
  sources: any[]; // RAG citations
  pages: any[]; // wiki pages read
  ms: number | null;
  saved?: any;
}

interface Msg {
  seq?: number;
  question: string;
  searched: string;
  rewritten?: boolean;
  mode: Mode;
  sources: Sources;
  rag_collection: string | null;
  wiki_slug: string | null;
  rag: Pane | null;
  wiki: Pane | null;
  created_at?: string;
  editing?: boolean;
  editText?: string;
  note?: string;
}

const pane = (): Pane => ({ answer: '', running: true, error: '', sources: [], pages: [], ms: null });
const stored = (p: any): Pane | null => (p ? { answer: p.answer ?? '', running: false, error: p.error ?? '', sources: p.sources ?? [], pages: p.pages ?? [], ms: p.ms ?? null } : null);
const MODE_LABEL: Record<Mode, string> = { rag: 'RAG only', wiki: 'Wiki only', both: 'Both' };

@Component({
  selector: 'app-ask',
  imports: [FormsModule, RouterLink, DatePipe, MatFormFieldModule, MatInputModule, MatButtonModule, MatButtonToggleModule, MatSelectModule,
    MatIconModule, MatProgressBarModule, Markdown],
  template: `
    <div class="ask">
      <aside class="chats">
        <button mat-flat-button class="new" (click)="newChat()"><mat-icon>add</mat-icon> New chat</button>
        @for (c of chats(); track c.id) {
          <div class="chat" [class.active]="c.id === chatId()">
            @if (renaming() === c.id) {
              <input class="rename" [(ngModel)]="renameText" (keydown.enter)="rename(c)" (keydown.escape)="renaming.set(null)" />
              <button mat-icon-button (click)="rename(c)" title="Save name"><mat-icon>check</mat-icon></button>
            } @else if (deleting() === c.id) {
              <span class="grow small">Delete this chat? Synthesis pages made from it stay in the wiki.</span>
              <button mat-button class="error" (click)="remove(c)">Delete</button>
              <button mat-button (click)="deleting.set(null)">Cancel</button>
            } @else {
              <button class="open" (click)="open(c.id)" [title]="c.title">
                <span class="title">{{ c.title || 'New chat' }}</span>
                <span class="muted small">{{ c.updated_at | date: 'd MMM, HH:mm' }} · {{ c.messages }} message(s)</span>
              </button>
              <button mat-icon-button (click)="renaming.set(c.id); renameText = c.title" title="Rename"><mat-icon>edit</mat-icon></button>
              <button mat-icon-button (click)="deleting.set(c.id)" title="Delete"><mat-icon>delete</mat-icon></button>
            }
          </div>
        } @empty { <p class="muted small">No chats yet.</p> }
      </aside>

      <section class="main">
        <div class="row controls">
          <mat-button-toggle-group [(ngModel)]="mode" hideSingleSelectionIndicator title="Which side(s) the next message asks">
            <mat-button-toggle value="rag">RAG only</mat-button-toggle>
            <mat-button-toggle value="wiki">Wiki only</mat-button-toggle>
            <mat-button-toggle value="both">Both</mat-button-toggle>
          </mat-button-toggle-group>
          @if (mode !== 'wiki') {
            <mat-form-field appearance="outline" class="pick" subscriptSizing="dynamic"><mat-label>Collection</mat-label>
              <mat-select [ngModel]="cols.current()" (ngModelChange)="cols.select($event)">
                @for (c of cols.list(); track c.slug) { <mat-option [value]="c.slug">{{ c.name }}</mat-option> }
              </mat-select></mat-form-field>
          }
          @if (mode !== 'rag') {
            <mat-form-field appearance="outline" class="pick" subscriptSizing="dynamic"><mat-label>Wiki</mat-label>
              <mat-select [(ngModel)]="wiki">
                @for (w of wikis(); track w.slug) { <mat-option [value]="w.slug">{{ w.name }}</mat-option> }
              </mat-select></mat-form-field>
          }
          <div class="sources" title="Which documents RAG and the wiki may use, for the next message">
            <span class="muted">Sources</span>
            <mat-button-toggle-group [(ngModel)]="sources" hideSingleSelectionIndicator>
              <mat-button-toggle value="standard">Standard only</mat-button-toggle>
              <mat-button-toggle value="all">All</mat-button-toggle>
            </mat-button-toggle-group>
          </div>
        </div>

        <div class="thread">
          @for (m of messages(); track $index; let i = $index) {
            <div class="msg">
              <div class="q"><b>{{ m.question }}</b></div>
              <div class="meta muted small">
                <span class="pill">{{ modeLabel[m.mode] }}</span><span class="pill">{{ m.sources === 'standard' ? 'Standard only' : 'All' }}</span>
                @if (m.created_at) { answered {{ m.created_at | date: 'd MMM y, HH:mm' }} }
              </div>
              @if (m.editing) {
                <div class="row searched">
                  <mat-form-field class="grow" appearance="outline" subscriptSizing="dynamic"><mat-label>Searched for</mat-label>
                    <input matInput [(ngModel)]="m.editText" (keydown.enter)="askAgain(i)" /></mat-form-field>
                  <button mat-flat-button (click)="askAgain(i)" [disabled]="!m.editText?.trim() || busy()">Search again</button>
                  <button mat-button (click)="m.editing = false">Cancel</button>
                </div>
              } @else {
                <div class="searched muted">Searched for: <span class="sq">{{ m.searched }}</span>
                  @if (!busy()) { <button mat-icon-button (click)="m.editing = true; m.editText = m.searched" title="Edit and search again"><mat-icon>edit</mat-icon></button> }
                </div>
              }
              @if (m.note) { <div class="warn small">{{ m.note }}</div> }
              <div class="panes" [class.single]="m.mode !== 'both'">
                @if (m.rag; as p) {
                  <div class="pane card">
                    <header class="row"><h3 class="grow">RAG · {{ m.rag_collection }}</h3>@if (p.ms) { <span class="muted">{{ p.ms / 1000 }} s</span> }</header>
                    @if (p.running) { <mat-progress-bar mode="indeterminate" /> }
                    @if (p.error) { <p class="error">{{ p.error }}</p> }
                    <app-md [text]="p.answer" />
                    @if (p.sources.length) {
                      <div class="chips"><span class="muted">Sources:</span>
                        @for (c of p.sources; track c.chunk_id) { <button class="chip" (click)="cites.openRag(c.para_ref ?? c.chunk_id)" [title]="c.snippet">{{ c.para_ref ?? c.chunk_id }}</button> }
                      </div>
                    }
                  </div>
                }
                @if (m.wiki; as p) {
                  <div class="pane card">
                    <header class="row"><h3 class="grow">Wiki · {{ m.wiki_slug }}</h3>@if (p.ms) { <span class="muted">{{ p.ms / 1000 }} s</span> }</header>
                    @if (p.running) { <mat-progress-bar mode="indeterminate" /> }
                    @if (p.error) { <p class="error">{{ p.error }}</p> }
                    <app-md [text]="p.answer" [wiki]="m.wiki_slug ?? ''" [titles]="titles(p)" [cites]="false" />
                    @if (p.pages.length) {
                      <div class="chips"><span class="muted">Pages read:</span>
                        @for (pg of p.pages; track pg.slug) {
                          <button class="chip" [class.dim]="!pg.cited" [class.saved]="pg.saved" (click)="cites.openWiki(m.wiki_slug ?? '', pg.slug)"
                                  [title]="pg.saved ? 'Saved answer, read in addition to the pages' : ''">{{ pg.saved ? 'Saved answer: ' : '' }}{{ pg.title }}</button>
                        }
                      </div>
                    }
                    @if (!p.running && p.answer && !p.error) {
                      <div class="row save">
                        @if (p.saved; as s) {
                          <span class="muted">Saved as <a [routerLink]="['/wiki', m.wiki_slug, s.status === 'applied' ? 'pages' : 'changesets', s.status === 'applied' ? s.slug : s.changeset_id]">{{ s.slug }}</a> ({{ s.status }})</span>
                        } @else {
                          <button mat-stroked-button (click)="save(i)" [disabled]="saving()"><mat-icon>bookmark_add</mat-icon> Save answer as wiki page</button>
                        }
                      </div>
                    }
                  </div>
                }
              </div>
            </div>
          } @empty {
            <p class="muted">Ask a question. Follow-ups in the same chat are rewritten into full questions from the earlier questions (never the answers); "Searched for" shows what was sent, and you can edit it.</p>
          }
        </div>

        @if (error()) { <p class="error">{{ error() }}</p> }
        <div class="composer">
          <mat-form-field class="full" appearance="outline" subscriptSizing="dynamic">
            <mat-label>{{ messages().length ? 'Follow-up question' : 'Question' }}</mat-label>
            <textarea matInput rows="2" [(ngModel)]="question" (keydown.control.enter)="ask()" (keydown.meta.enter)="ask()"
                      placeholder="e.g. When must lifetime expected credit losses be recognised?"></textarea>
            <mat-hint>Ctrl+Enter to ask · {{ modeLabel[mode] }} · {{ sources === 'standard' ? 'Standard only' : 'All' }}</mat-hint>
          </mat-form-field>
          @if (busy()) { <button mat-stroked-button (click)="stop()"><mat-icon>stop</mat-icon> Stop</button> }
          <button mat-flat-button (click)="ask()" [disabled]="!question.trim() || busy() || !canAsk()"><mat-icon>send</mat-icon> Ask</button>
        </div>
      </section>
    </div>
  `,
  styles: `
    .ask { display: grid; grid-template-columns: 270px minmax(0, 1fr); gap: 16px; padding: 16px; }
    @media (max-width: 900px) { .ask { grid-template-columns: 1fr; } }
    .chats { display: flex; flex-direction: column; gap: 4px; border-right: 1px solid var(--mat-sys-outline-variant); padding-right: 12px; }
    .chats .new { margin-bottom: 8px; }
    .chat { display: flex; align-items: center; gap: 2px; border-radius: 8px; }
    .chat.active { background: var(--mat-sys-secondary-container); }
    .chat .open { flex: 1; min-width: 0; text-align: left; border: 0; background: none; color: inherit; cursor: pointer; padding: 6px 8px; display: flex; flex-direction: column; }
    .chat .title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .chat .rename { flex: 1; min-width: 0; padding: 4px 6px; }
    .controls { flex-wrap: wrap; gap: 12px; align-items: center; }
    .pick { width: 200px; }
    .sources { display: flex; align-items: center; gap: 8px; }
    .thread { margin-top: 16px; display: flex; flex-direction: column; gap: 24px; }
    .msg .q { font-size: 15.5px; }
    .meta { margin: 2px 0 4px; }
    .searched { display: flex; align-items: center; gap: 6px; } .sq { font-style: italic; }
    .panes { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 8px; }
    .panes.single { grid-template-columns: 1fr; }
    @media (max-width: 1100px) { .panes { grid-template-columns: 1fr; } }
    .pane h3 { margin: 0; }
    .chips { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .chip { border: 1px solid var(--mat-sys-outline-variant); background: var(--mat-sys-surface-container); color: inherit; border-radius: 12px; padding: 2px 10px; cursor: pointer; font-size: 12.5px; }
    .chip.dim { opacity: .6; } .chip.saved { border-style: dashed; }
    .save { margin-top: 12px; }
    .composer { position: sticky; bottom: 0; display: flex; gap: 8px; align-items: flex-start; padding: 12px 0; background: var(--mat-sys-surface); margin-top: 16px; }
    .composer .full { flex: 1; }
    .small { font-size: 12px; } .warn { color: #8a5a00; }`,
})
export class Ask {
  private api = inject(Api);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  readonly cites = inject(CitationService);
  readonly cols = inject(RagCollections);
  readonly modeLabel = MODE_LABEL;
  question = '';
  mode: Mode = 'both';
  sources: Sources = 'all';
  wiki = '';
  renameText = '';
  readonly wikis = signal<any[]>([]);
  readonly chats = signal<any[]>([]);
  readonly chatId = signal<string | null>(null);
  readonly messages = signal<Msg[]>([]);
  readonly busy = signal(false);
  readonly saving = signal(false);
  readonly error = signal('');
  readonly renaming = signal<string | null>(null);
  readonly deleting = signal<string | null>(null);
  private abort?: AbortController;

  constructor() {
    void this.cols.refresh();
    this.api.wikis().then((w) => {
      this.wikis.set(w);
      this.wiki ||= w[0]?.slug ?? '';
    });
    void this.loadChats();
    const chat = this.route.snapshot.queryParamMap.get('chat');  // /ask?chat=<id> opens a saved chat
    if (chat) void this.open(chat);
  }

  private remember(id: string | null) {
    void this.router.navigate([], { relativeTo: this.route, queryParams: { chat: id }, replaceUrl: true });
  }

  canAsk() {
    return (this.mode === 'wiki' || !!this.cols.current()) && (this.mode === 'rag' || !!this.wiki);
  }

  titles(p: Pane) { return new Map<string, string>(p.pages.map((x: any) => [x.slug, x.title])); }

  async loadChats() {
    try { this.chats.set(await this.api.get('/api/ask/chats')); } catch (e) { this.error.set(errMsg(e)); }
  }

  newChat() {
    this.stop();
    this.chatId.set(null);
    this.remember(null);
    this.messages.set([]);
    this.question = '';
    this.error.set('');
  }

  async open(id: string) {
    this.stop();
    this.error.set('');
    try {
      const c = await this.api.get<any>(`/api/ask/chats/${enc(id)}`);
      this.chatId.set(id);
      this.remember(id);
      this.messages.set(c.messages.map((m: any) => ({ ...m, rag: stored(m.rag), wiki: stored(m.wiki) })));
      const last = c.messages[c.messages.length - 1];
      if (last) {  // carry on with the last message's settings
        this.mode = last.mode;
        this.sources = last.sources;
        if (last.wiki_slug) this.wiki = last.wiki_slug;
        if (last.rag_collection) this.cols.select(last.rag_collection);
      }
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }

  async rename(c: any) {
    try {
      await this.api.patch(`/api/ask/chats/${enc(c.id)}`, { title: this.renameText });
      this.renaming.set(null);
      await this.loadChats();
    } catch (e) { this.error.set(errMsg(e)); }
  }

  async remove(c: any) {
    try {
      await this.api.delete(`/api/ask/chats/${enc(c.id)}`);
      this.deleting.set(null);
      if (this.chatId() === c.id) this.newChat();
      await this.loadChats();
    } catch (e) { this.error.set(errMsg(e)); }
  }

  stop() { this.abort?.abort(); }

  private patch(i: number, f: (m: Msg) => Msg) {
    this.messages.update((ms) => ms.map((m, j) => (j === i ? f(m) : m)));
  }

  /** A new message: rewrite a follow-up into a full question, ask the chosen side(s), then save it in the chat. */
  async ask() {
    const q = this.question.trim();
    if (!q || this.busy() || !this.canAsk()) return;
    this.error.set('');
    this.busy.set(true);
    try {
      let id = this.chatId();
      if (!id) {
        id = (await this.api.post<any>('/api/ask/chats', {})).id as string;
        this.chatId.set(id);
        this.remember(id);
      }
      const rw = await this.api.post<any>(`/api/ask/chats/${enc(id)}/rewrite`, { question: q });
      const m: Msg = {
        question: q, searched: rw.searched, rewritten: rw.rewritten, mode: this.mode, sources: this.sources,
        rag_collection: this.mode !== 'wiki' ? this.cols.current() : null, wiki_slug: this.mode !== 'rag' ? this.wiki : null,
        rag: null, wiki: null, note: rw.error ?? '',
      };
      this.messages.update((ms) => [...ms, m]);
      this.question = '';
      await this.run(this.messages().length - 1, false);
    } catch (e) {
      this.error.set(errMsg(e));
    } finally {
      this.busy.set(false);
    }
  }

  /** Ask a message again with an edited "Searched for" (its own side(s) and Sources), replacing its answers. */
  async askAgain(i: number) {
    const m = this.messages()[i];
    const text = m.editText?.trim();
    if (!text || this.busy()) return;
    this.busy.set(true);
    this.patch(i, (x) => ({ ...x, searched: text, rewritten: text !== x.question, editing: false, note: '' }));
    try { await this.run(i, true); } catch (e) { this.error.set(errMsg(e)); } finally { this.busy.set(false); }
  }

  private async run(i: number, replace: boolean) {
    this.abort = new AbortController();
    const m = this.messages()[i];
    this.patch(i, (x) => ({ ...x, rag: x.mode !== 'wiki' ? pane() : null, wiki: x.mode !== 'rag' ? pane() : null, created_at: undefined }));
    const body = { question: m.searched, sources: m.sources };
    await Promise.all([
      m.mode !== 'wiki' ? this.stream(i, 'rag', `/api/rag/collections/${enc(m.rag_collection!)}/query/stream`, 'citations', body) : null,
      m.mode !== 'rag' ? this.stream(i, 'wiki', `/api/wiki/wikis/${enc(m.wiki_slug!)}/query/stream`, 'pages', body) : null,
    ]);
    const done = this.messages()[i];
    const side = (p: Pane | null) => (p ? { answer: p.answer, sources: p.sources, pages: p.pages, ms: p.ms, error: p.error } : null);
    const saved = await this.api.post<any>(`/api/ask/chats/${enc(this.chatId()!)}/messages`, {
      question: done.question, searched: done.searched, mode: done.mode, sources: done.sources,
      rag_collection: done.rag_collection, wiki_slug: done.wiki_slug, rag: side(done.rag), wiki: side(done.wiki),
      seq: replace ? done.seq : null,
    });
    this.patch(i, (x) => ({ ...x, seq: saved.seq, created_at: saved.created_at }));
    await this.loadChats();
  }

  private async stream(i: number, key: 'rag' | 'wiki', url: string, sourcesEvent: string, body: any) {
    const t0 = performance.now();
    const set = (f: (p: Pane) => Pane) => this.patch(i, (x) => ({ ...x, [key]: f(x[key]!) }));
    try {
      for await (const ev of postSse(url, body, this.abort!.signal)) {
        if (ev.event === 'token') set((p) => ({ ...p, answer: p.answer + JSON.parse(ev.data) }));
        else if (ev.event === sourcesEvent) set((p) => (key === 'rag' ? { ...p, sources: JSON.parse(ev.data) } : { ...p, pages: JSON.parse(ev.data) }));
      }
    } catch (e: any) {
      set((p) => ({ ...p, error: e?.name === 'AbortError' ? 'Stopped' : errMsg(e) }));
    } finally {
      set((p) => ({ ...p, running: false, ms: Math.round(performance.now() - t0) }));
    }
  }

  async save(i: number) {
    const m = this.messages()[i];
    this.saving.set(true);
    try {
      const r = await this.api.post(`/api/wiki/wikis/${enc(m.wiki_slug!)}/query`, { question: m.searched, save: true, mode: 'auto', sources: m.sources });
      this.patch(i, (x) => ({ ...x, wiki: { ...x.wiki!, saved: r.saved } }));
    } catch (e) {
      this.patch(i, (x) => ({ ...x, wiki: { ...x.wiki!, error: errMsg(e) } }));
    } finally {
      this.saving.set(false);
    }
  }
}
