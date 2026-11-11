import { Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';

export interface ConfirmData {
  title: string;
  message: string;
  confirm?: string; // the confirm button's label (default "Delete")
}

/** A modal asking the user to confirm a destructive action. Use `confirmDialog(dialog, data)`. */
@Component({
  selector: 'app-confirm-dialog',
  imports: [MatDialogModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content><p>{{ data.message }}</p></mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [mat-dialog-close]="false" cdkFocusInitial>Cancel</button>
      <button mat-flat-button class="danger" [mat-dialog-close]="true">{{ data.confirm ?? 'Delete' }}</button>
    </mat-dialog-actions>
  `,
  styles: `.danger { background: var(--mat-sys-error); color: var(--mat-sys-on-error); } p { margin: 0; }`,
})
export class ConfirmDialog {
  readonly data = inject<ConfirmData>(MAT_DIALOG_DATA);
}

/** Opens the confirm modal; resolves true only when the user confirms. */
export function confirmDialog(dialog: MatDialog, data: ConfirmData): Promise<boolean> {
  return firstValueFrom(dialog.open(ConfirmDialog, { data, width: '420px', autoFocus: 'dialog' }).afterClosed()).then((r) => r === true);
}
