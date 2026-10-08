import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { catchError, throwError } from 'rxjs';

/** Shared-password session (only enforced when the BFF has UI_PASSWORD set). */
@Injectable({ providedIn: 'root' })
export class AuthService {
  /** null = still checking */
  readonly authenticated = signal<boolean | null>(null);

  constructor() {
    window.addEventListener('wb-unauthorized', () => this.authenticated.set(false));
    void this.check();
  }

  async check() {
    try {
      const r = await (await fetch('/api/auth/session')).json();
      this.authenticated.set(r.authenticated);
    } catch {
      this.authenticated.set(true); // BFF unreachable: let pages show their own errors
    }
  }

  async login(password: string): Promise<string | null> {
    const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
    if (r.ok) { this.authenticated.set(true); return null; }
    return r.status === 401 ? 'Wrong password' : `Login failed (${r.status})`;
  }

  async logout() {
    await fetch('/api/auth/logout', { method: 'POST' });
    this.authenticated.set(false);
  }
}

/** Any 401 from the BFF means the session is missing or expired: show the login screen. */
export const authInterceptor: HttpInterceptorFn = (req, next) =>
  next(req).pipe(
    catchError((e: HttpErrorResponse) => {
      if (e.status === 401) window.dispatchEvent(new Event('wb-unauthorized'));
      return throwError(() => e);
    }),
  );
