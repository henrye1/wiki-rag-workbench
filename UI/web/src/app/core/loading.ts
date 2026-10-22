import { HttpInterceptorFn } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { finalize } from 'rxjs';

/** Screen loads in progress (GET requests), for the loading circle. Background refreshes are not counted. */
@Injectable({ providedIn: 'root' })
export class Loading {
  private readonly count = signal(0);
  private readonly late = signal(false);
  private timer: ReturnType<typeof setTimeout> | null = null;
  /** True as soon as anything loads: empty-list messages wait until it is false. */
  readonly busy = computed(() => this.count() > 0);
  /** True once a load has taken longer than a moment, so quick loads never flash the circle. */
  readonly show = computed(() => this.busy() && this.late());

  start() {
    this.count.update((n) => n + 1);
    if (!this.timer && !this.late()) this.timer = setTimeout(() => { this.timer = null; if (this.count() > 0) this.late.set(true); }, 300);
  }
  end() {
    this.count.update((n) => Math.max(0, n - 1));
    if (this.count() === 0) {
      this.late.set(false);
      if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    }
  }
}

let quiet = 0;

/** Run a background refresh (polling): the requests it starts do not show the loading circle. */
export async function quietly<T>(fn: () => Promise<T>): Promise<T> {
  quiet++;
  try {
    return await fn();
  } finally {
    quiet--;
  }
}

/** Counts each GET (a screen loading its data) unless it was started by a background refresh. */
export const loadingInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.method !== 'GET' || quiet > 0) return next(req);
  const loading = inject(Loading);
  loading.start();
  return next(req).pipe(finalize(() => loading.end()));
};
