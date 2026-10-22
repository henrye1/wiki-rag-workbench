import { DestroyRef, inject } from '@angular/core';
import { quietly } from '../core/loading';

/** Calls fn every `ms` until it returns false or the component is destroyed (a background refresh: no loading circle). */
export function poller(fn: () => Promise<boolean>, ms = 3000) {
  const destroy = inject(DestroyRef);
  let timer: any;
  let stopped = false;
  destroy.onDestroy(() => { stopped = true; clearTimeout(timer); });
  const tick = async () => {
    if (stopped) return;
    let again = true;
    try { again = await quietly(fn); } catch { again = true; }
    if (again && !stopped) timer = setTimeout(tick, ms);
  };
  return { start: () => { clearTimeout(timer); void tick(); }, stop: () => clearTimeout(timer) };
}
