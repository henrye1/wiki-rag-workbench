import { DatePipe } from '@angular/common';
import { Component, effect, inject, input, signal } from '@angular/core';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { Api, enc } from '../../core/api';

@Component({
  selector: 'app-wiki-changesets',
  imports: [DatePipe, FormsModule, RouterLink, MatButtonToggleModule],
  template: `
    <div class="row">
      <p class="muted grow">Proposed wiki edits from ingest (review mode), saved answers and lint fixes. Open one to see diffs and apply or discard.</p>
      <mat-button-toggle-group [ngModel]="status()" (ngModelChange)="status.set($event)">
        <mat-button-toggle value="pending">Pending</mat-button-toggle>
        <mat-button-toggle value="">All</mat-button-toggle>
      </mat-button-toggle-group>
    </div>
    <table class="simple">
      <thead><tr><th>Changeset</th><th>Kind</th><th>Ops</th><th>Status</th><th>Created</th></tr></thead>
      <tbody>
        @for (c of items(); track c.id) {
          <tr>
            <td><a [routerLink]="[c.id]">{{ c.summary || c.id }}</a></td><td>{{ c.kind }}</td><td>{{ c.ops }}</td>
            <td><span class="pill" [class.warn]="c.status === 'pending'" [class.ok]="c.status === 'applied'">{{ c.status }}</span></td>
            <td>{{ c.created_at | date: 'short' }}</td>
          </tr>
        } @empty { <tr><td colspan="5" class="muted empty">Nothing here.</td></tr> }
      </tbody>
    </table>
  `,
})
export class WikiChangesets {
  private api = inject(Api);
  readonly w = input.required<string>();
  readonly status = signal('pending');
  readonly items = signal<any[]>([]);
  constructor() {
    effect(() => {
      const s = this.status();
      void this.api.get(`/api/wiki/wikis/${enc(this.w())}/changesets`, { status: s }).then((x) => this.items.set(x));
    });
  }
}
