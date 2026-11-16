import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { Router, RouterLink } from '@angular/router';
import { Api, errMsg } from '../../core/api';
import { WikiNames } from '../../core/wiki-names';
import { slugify } from '../../shared/markdown';

@Component({
  selector: 'app-wiki-select',
  imports: [FormsModule, RouterLink, MatButtonModule, MatFormFieldModule, MatInputModule],
  template: `
    <div class="page">
      <h1>Wikis</h1>
      <div class="cards">
        @for (w of wikis(); track w.slug) {
          <div class="card">
            <a class="link" [routerLink]="['/wiki', w.slug]">
              <h3>{{ names.name(w.slug, w.name) }}</h3>
              @if (!names.masked(w.slug)) { <div class="muted">{{ w.description }}</div> }
              <p><span class="pill">{{ w.pages }} pages</span><span class="pill">{{ w.sources }} sources</span></p>
            </a>
            <label class="hide small muted"><input type="checkbox" [checked]="names.hidden().has(w.slug)"
              (change)="names.setHidden(w.slug, $any($event.target).checked)" /> Hide this name</label>
          </div>
        }
      </div>
      <div class="card create">
        <h3>Create a wiki</h3>
        <div class="row">
          <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Name</mat-label>
            <input matInput [(ngModel)]="name" (ngModelChange)="slug = slugify($event)" /></mat-form-field>
          <mat-form-field appearance="outline" subscriptSizing="dynamic"><mat-label>Slug</mat-label><input matInput [(ngModel)]="slug" /></mat-form-field>
          <mat-form-field appearance="outline" subscriptSizing="dynamic" class="grow"><mat-label>Description</mat-label><input matInput [(ngModel)]="description" /></mat-form-field>
          <button mat-flat-button (click)="create()" [disabled]="!name || !slug">Create</button>
        </div>
        <p class="muted">Starts with the default generic schema (page types, link and citation conventions); edit it under Settings.</p>
        @if (error()) { <p class="error">{{ error() }}</p> }
      </div>
    </div>
  `,
  styles: `.link { display: block; text-decoration: none; color: inherit; } .card:hover { border-color: var(--mat-sys-primary); }
    .hide { display: flex; align-items: center; gap: 6px; cursor: pointer; } .create { margin-top: 24px; }`,
})
export class WikiSelect {
  private api = inject(Api);
  private router = inject(Router);
  readonly names = inject(WikiNames);
  readonly wikis = signal<any[]>([]);
  readonly error = signal('');
  readonly slugify = slugify;
  name = '';
  slug = '';
  description = '';

  constructor() { this.api.wikis().then((w) => this.wikis.set(w)); }

  async create() {
    try {
      await this.api.post('/api/wiki/wikis', { slug: this.slug, name: this.name, description: this.description });
      this.router.navigate(['/wiki', this.slug, 'sources']);
    } catch (e) {
      this.error.set(errMsg(e));
    }
  }
}
