import { Component, computed, input } from '@angular/core';

/** Renders a unified diff (as produced by Python difflib) with add/delete highlighting. */
@Component({
  selector: 'app-diff',
  template: `
    @if (lines().length) {
      <div class="diff">@for (l of lines(); track $index) {<div [class]="l.cls">{{ l.text || ' ' }}</div>}</div>
    } @else { <p class="muted">No textual changes.</p> }
  `,
})
export class Diff {
  readonly text = input<string>('');
  readonly lines = computed(() =>
    (this.text() || '').split('\n').filter((l) => !l.startsWith('---') && !l.startsWith('+++')).map((l) => ({
      text: l,
      cls: l.startsWith('@@') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : '',
    })),
  );
}
