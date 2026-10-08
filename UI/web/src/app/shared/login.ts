import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { AuthService } from '../core/auth';

@Component({
  selector: 'app-login',
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule],
  template: `
    <form class="box card" (ngSubmit)="submit()">
      <div class="brand"><mat-icon>account_balance</mat-icon> IFRS Workbench</div>
      <p class="muted">Enter the password you were given.</p>
      <mat-form-field appearance="outline" class="full">
        <mat-label>Password</mat-label>
        <input matInput type="password" name="password" [(ngModel)]="password" autocomplete="current-password" autofocus />
      </mat-form-field>
      @if (error()) { <p class="error">{{ error() }}</p> }
      <button mat-flat-button class="full" type="submit" [disabled]="!password || busy()">Sign in</button>
    </form>
  `,
  styles: `
    :host { display: grid; place-items: center; min-height: 100vh; padding: 16px; box-sizing: border-box; }
    .box { width: min(380px, 100%); }
    .brand { display: flex; align-items: center; gap: 8px; font: var(--mat-sys-title-large); margin-bottom: 8px; }
    .full { width: 100%; }
  `,
})
export class Login {
  private auth = inject(AuthService);
  password = '';
  readonly error = signal('');
  readonly busy = signal(false);

  async submit() {
    this.busy.set(true);
    this.error.set((await this.auth.login(this.password)) ?? '');
    this.busy.set(false);
  }
}
