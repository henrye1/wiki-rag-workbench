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

        <div class="row synth">
          <button mat-stroked-button (click)="createSynthesis()" [disabled]="!canSynthesize() || synthBusy() || !!draft()"
                  [title]="canSynthesize() ? 'Draft one summary of this chat from its wiki answers' : 'The chat has no wiki answers yet'">
            <mat-icon>summarize</mat-icon> Create synthesis</button>
          @if (synthBusy() && !draft()) { <span class="muted small">Drafting…</span> }
          @if (synthSaved(); as s) {
            <span class="muted">Saved as <a [routerLink]="['/wiki', s.wiki, 'pages', s.slug]">{{ s.slug }}</a>
              {{ s.problems?.length ? '(' + s.problems.length + ' citation problem(s) noted)' : '' }}</span>
          }
          @if (synthError()) { <span class="error">{{ synthError() }}</span> }
        </div>
        @if (draft(); as d) {
          <div class="card draft">
            <div class="row"><h3 class="grow">Synthesis draft · {{ d.wiki }}</h3>
              <span class="muted small">{{ d.answers.length }} wiki answer(s){{ d.other ? ' · ' + d.other + ' from another wiki left out' : '' }}</span></div>
            <p class="muted small">Page <b>{{ d.slug }}</b>{{ d.exists ? ' already exists (v' + d.version + '): saving updates it' : ' (new)' }}.
              Nothing is saved until you press Save.</p>
            <div class="row">
              <mat-form-field class="grow" appearance="outline" subscriptSizing="dynamic"><mat-label>Title</mat-label>
                <input matInput [(ngModel)]="d.title" (ngModelChange)="draftEdited()" /></mat-form-field>
              <mat-form-field class="grow" appearance="outline" subscriptSizing="dynamic"><mat-label>Summary</mat-label>
                <input matInput [(ngModel)]="d.summary" (ngModelChange)="draftEdited()" /></mat-form-field>
            </div>
            <div class="row"><span class="grow"></span>
              <mat-button-toggle-group [(ngModel)]="preview" hideSingleSelectionIndicator>
                <mat-button-toggle [value]="false">Edit</mat-button-toggle><mat-button-toggle [value]="true">Preview</mat-button-toggle>
              </mat-button-toggle-group></div>
            @if (preview) { <div class="previewbox"><app-md [text]="d.content_md" [wiki]="d.wiki" [cites]="false" /></div> }
            @else {
              <textarea class="editor" [(ngModel)]="d.content_md" (ngModelChange)="draftEdited()" spellcheck="false"></textarea>
            }
            <div class="problems">
              @if (d.content_md !== d.checkedText) { <p class="warn small">Edited since the last check: it is checked again before saving.</p> }
              @if (d.problems?.length) {
                <b>Citation problems ({{ d.problems.length }})</b>
                <ul>@for (p of d.problems; track $index) {
                  <li><span class="pill bad">{{ p.kind }}</span> <code>{{ p.link }}</code> — {{ p.detail }}{{ p.count > 1 ? ' (×' + p.count + ')' : '' }}</li>
                }</ul>
              } @else { <p class="muted small">No citation problems found.</p> }
            </div>
            <div class="row">
              <button mat-flat-button (click)="saveSynthesis()" [disabled]="synthBusy() || !d.title.trim() || !d.content_md.trim()">
                {{ d.confirm && d.problems?.length ? 'Save anyway (' + d.problems.length + ' problem(s))' : 'Save' }}</button>
              <button mat-stroked-button (click)="recheck()" [disabled]="synthBusy()">Check again</button>
              <button mat-button (click)="draft.set(null)" [disabled]="synthBusy()">Cancel</button>
              @if (synthBusy()) { <span class="muted small">Checking…</span> }
            </div>
          </div>
        }

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
    .synth { margin-top: 12px; gap: 12px; align-items: center; }
    .draft { margin-top: 12px; display: flex; flex-direction: column; gap: 10px; }
    .draft h3 { margin: 0; }
    .editor { width: 100%; min-height: 360px; font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; line-height: 1.45;
              background: var(--mat-sys-surface-container); color: inherit; border: 1px solid var(--mat-sys-outline-variant); border-radius: 8px; padding: 10px; box-sizing: border-box; }
    .previewbox { border: 1px solid var(--mat-sys-outline-variant); border-radius: 8px; padding: 4px 14px; max-height: 520px; overflow: auto; }
    .problems ul { margin: 6px 0 0; padding-left: 18px; } .problems li { margin: 3px 0; }
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
  readonly draft = signal<any>(null);
  readonly synthBusy = signal(false);
  readonly synthError = signal('');
  readonly synthSaved = signal<any>(null);
  preview = false;
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
    this.draft.set(null);
    this.synthSaved.set(null);
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
      this.draft.set(null);
      this.synthSaved.set(null);
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

  /** The chat's wiki answers for a synthesis: the latest wiki's, oldest first; RAG-only and failed answers are skipped. */
  synthAnswers() {
    const ok = this.messages().filter((m) => m.wiki && !m.wiki.running && !m.wiki.error && m.wiki.answer.trim() && m.created_at);
    const wiki = ok.length ? ok[ok.length - 1].wiki_slug : null;
    const mine = ok.filter((m) => m.wiki_slug === wiki);
    return {
      wiki, other: ok.length - mine.length,
      answers: mine.map((m) => ({ searched: m.searched, answer: m.wiki!.answer, sources: m.sources, date: m.created_at! })),
    };
  }

  canSynthesize() { return !this.busy() && !!this.chatId() && this.synthAnswers().answers.length > 0; }

  async createSynthesis() {
    const { wiki, other, answers } = this.synthAnswers();
    if (!wiki || !answers.length) return;
    this.synthBusy.set(true);
    this.synthError.set('');
    this.synthSaved.set(null);
    try {
      const title = this.chats().find((c) => c.id === this.chatId())?.title ?? '';
      const d = await this.api.post<any>(`/api/wiki/wikis/${enc(wiki)}/synthesis/draft`, { chat_id: this.chatId(), chat_title: title, answers });
      this.draft.set({ ...d, wiki, answers, other, checkedText: d.content_md, confirm: false });
    } catch (e) {
      this.synthError.set(errMsg(e));
    } finally {
      this.synthBusy.set(false);
    }
  }

  draftEdited() { this.draft.update((d) => ({ ...d, confirm: false })); }

  async checkDraft(): Promise<any> {
    const d = this.draft();
    const r = await this.api.post<any>(`/api/wiki/wikis/${enc(d.wiki)}/synthesis/check`, { content_md: d.content_md, answers: d.answers });
    this.draft.update((x) => ({ ...x, problems: r.problems, checkedText: x.content_md }));
    return r;
  }

  async recheck() {
    this.synthBusy.set(true);
    try { await this.checkDraft(); } catch (e) { this.synthError.set(errMsg(e)); } finally { this.synthBusy.set(false); }
  }

  /** Save: check the (edited) text again first; with problems, ask once more before saving. */
  async saveSynthesis() {
    this.synthBusy.set(true);
    this.synthError.set('');
    try {
      const d0 = this.draft();
      if (d0.content_md !== d0.checkedText || !d0.confirm) {
        const r = await this.checkDraft();
        if (r.problems.length && !d0.confirm) {
          this.draft.update((x) => ({ ...x, confirm: true }));
          return;
        }
      }
      const d = this.draft();
      const r = await this.api.post<any>(`/api/wiki/wikis/${enc(d.wiki)}/synthesis`, {
        slug: d.slug, title: d.title, summary: d.summary, tags: d.tags, content_md: d.content_md, answers: d.answers,
      });
      this.synthSaved.set({ ...r, wiki: d.wiki });
      this.draft.set(null);
    } catch (e) {
      this.synthError.set(errMsg(e));
    } finally {
      this.synthBusy.set(false);
    }
  }
}
