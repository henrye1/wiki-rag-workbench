import { Component, computed, inject } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from './core/auth';
import { CitationService } from './shared/citation-service';
import { CitationPanel } from './shared/citations';
import { Login } from './shared/login';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, MatSidenavModule, MatToolbarModule, MatListModule, MatIconModule, CitationPanel, Login],
  template: `
    @if (auth.authenticated() === false) { <app-login /> }
    @else if (auth.authenticated()) {
    <mat-sidenav-container class="shell">
      <mat-sidenav mode="side" opened class="nav">
        <div class="brand"><mat-icon>account_balance</mat-icon> IFRS Workbench</div>
        <mat-nav-list>
          @for (n of nav; track n.path) {
            <a mat-list-item [routerLink]="n.path" routerLinkActive #rla="routerLinkActive" [activated]="rla.isActive"
               [routerLinkActiveOptions]="{ exact: n.path === '/' }">
              <mat-icon matListItemIcon>{{ n.icon }}</mat-icon><span matListItemTitle>{{ n.label }}</span>
            </a>
          }
        </mat-nav-list>
      </mat-sidenav>
      <mat-sidenav position="end" mode="over" class="drawer" [opened]="drawerOpen()" (closedStart)="cites.close()">
        <app-citation-panel />
      </mat-sidenav>
      <mat-sidenav-content><router-outlet /></mat-sidenav-content>
    </mat-sidenav-container>
    }
  `,
  styles: `
    .shell { height: 100vh; }
    .nav { width: 220px; border-right: 1px solid var(--mat-sys-outline-variant); }
    .brand { display: flex; align-items: center; gap: 8px; padding: 16px; font: var(--mat-sys-title-medium); }
    .drawer { width: min(560px, 92vw); }
  `,
})
export class App {
  readonly auth = inject(AuthService);
  readonly cites = inject(CitationService);
  readonly drawerOpen = computed(() => this.cites.target() !== null);
  readonly nav = [
    { path: '/', label: 'Home', icon: 'home' },
    { path: '/ask', label: 'Ask (side by side)', icon: 'forum' },
    { path: '/documents', label: 'RAG documents', icon: 'description' },
    { path: '/bulk', label: 'Bulk requirements', icon: 'playlist_add_check' },
    { path: '/wiki', label: 'Wiki', icon: 'menu_book' },
    { path: '/benchmark', label: 'Benchmark', icon: 'leaderboard' },
  ];
}
