import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api';

const TYPES = ['overview', 'topic', 'concept', 'entity', 'comparison', 'synthesis', 'source'];

@Component({
  selector: 'app-wiki-pages',
  imports: [FormsModule, RouterLink, DatePipe, MatFormFieldModule, MatInputModule, MatIconModule],
  template: `
    <div class="row">
      <mat-form-field appearance="outline" class="grow" subscriptSizing="dynamic">
        <mat-icon matPrefix>search</mat-icon><mat-label>Filter pages</mat-label>
        <input matInput [ngModel]="q()" (ngModelChange)="q.set($event)" />
      </mat-form-field>
      <span class="muted">{{ filtered().length }} of {{ pages().length }}</span>
    </div>
    @for (g of groups(); track g.type) {
      <h3>{{ g.type }} ({{ g.items.length }})</h3>
      <table class="simple">
        <tbody>
          @for (p of g.items; track p.slug) {
            <tr>
              <td class="t"><a [routerLink]="[p.slug]">{{ p.title }}</a>
                @if (p.saved_answer) { <span class="pill">saved answer</span> }
                @if (p.needs_checking) { <span class="pill bad" [title]="p.needs_checking.why + ': ' + p.needs_checking.paragraphs.join(', ')">needs checking</span> }</td>
              <td class="muted">{{ p.summary }}</td>
              <td class="muted nowrap">v{{ p.version }} · {{ p.updated_at | date: 'short' }}</td>
            </tr>
          }
        </tbody>
      </table>
    } @empty { <p class="muted">No pages. Add a source under “Sources & ingest”.</p> }
  `,
  styles: `.t { width: 30%; } .nowrap { white-space: nowrap; } h3 { text-transform: capitalize; margin-top: 20px; }`,
})
export class WikiPages {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly pages = signal<any[]>([]);
  readonly q = signal('');
  readonly filtered = computed(() => {
    const q = this.q().toLowerCase();
    return this.pages().filter((p) => !q || `${p.title} ${p.slug} ${p.summary}`.toLowerCase().includes(q));
  });
  readonly groups = computed(() =>
    TYPES.map((type) => ({ type, items: this.filtered().filter((p) => p.type === type) })).filter((g) => g.items.length),
  );
  constructor() {
    effect(() => { void this.api.pages(this.w()).then((p) => this.pages.set(p)); });
  }
}
