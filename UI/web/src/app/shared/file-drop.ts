import { Component, input, output, signal } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

/** Click-or-drop file picker. */
@Component({
  selector: 'app-file-drop',
  imports: [MatIconModule],
  template: `
    <label class="drop" [class.over]="over()" (dragover)="$event.preventDefault(); over.set(true)" (dragleave)="over.set(false)"
           (drop)="onDrop($event)">
      <input type="file" [accept]="accept()" (change)="onPick($event)" hidden />
      <mat-icon>upload_file</mat-icon>
      <span>{{ file()?.name ?? label() }}</span>
    </label>
  `,
  styles: `
    .drop { display: flex; align-items: center; gap: 10px; padding: 14px 16px; border: 2px dashed var(--mat-sys-outline-variant);
            border-radius: 12px; cursor: pointer; color: var(--mat-sys-on-surface-variant); }
    .drop.over { border-color: var(--mat-sys-primary); background: var(--mat-sys-primary-container); }
  `,
})
export class FileDrop {
  readonly accept = input('');
  readonly label = input('Drop a file here or click to choose');
  readonly picked = output<File>();
  readonly file = signal<File | null>(null);
  readonly over = signal(false);

  onPick(ev: Event) {
    const f = (ev.target as HTMLInputElement).files?.[0];
    if (f) this.set(f);
  }
  onDrop(ev: DragEvent) {
    ev.preventDefault();
    this.over.set(false);
    const f = ev.dataTransfer?.files?.[0];
    if (f) this.set(f);
  }
  reset() { this.file.set(null); }
  private set(f: File) { this.file.set(f); this.picked.emit(f); }
}
