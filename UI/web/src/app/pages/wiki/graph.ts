import { Component, ElementRef, OnDestroy, effect, inject, input, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { Router } from '@angular/router';
import cytoscape from 'cytoscape';
import { Api, enc } from '../../core/api';

const COLORS: Record<string, string> = {
  overview: '#1565c0', topic: '#6a1b9a', subtopic: '#9c4dcc', concept: '#2e7d32', entity: '#ef6c00', comparison: '#00838f',
  synthesis: '#ad1457', source: '#5d4037', missing: '#9e9e9e',
};

@Component({
  selector: 'app-wiki-graph',
  imports: [FormsModule, MatCheckboxModule],
  template: `
    <div class="row">
      <mat-checkbox [ngModel]="showMissing()" (ngModelChange)="showMissing.set($event)">Show missing pages (broken link targets)</mat-checkbox>
      <span class="grow"></span>
      @for (c of legend; track c[0]) { <span class="legend"><i [style.background]="c[1]"></i>{{ c[0] }}</span> }
    </div>
    <p class="muted">{{ stats() }} Node size = inbound links. Red ring = orphan. Click a page to open it.</p>
    <div #host class="graph"></div>
  `,
  styles: `
    .graph { height: calc(100vh - 290px); min-height: 420px; border: 1px solid var(--mat-sys-outline-variant); border-radius: 12px; }
    .legend { font-size: 12px; display: inline-flex; align-items: center; gap: 4px; text-transform: capitalize; }
    .legend i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  `,
})
export class WikiGraph implements OnDestroy {
  private api = inject(Api);
  private router = inject(Router);
  readonly w = input.required<string>();
  readonly host = viewChild.required<ElementRef<HTMLDivElement>>('host');
  readonly showMissing = signal(false);
  readonly stats = signal('');
  readonly legend = Object.entries(COLORS);
  private data = signal<any>(null);
  private cy?: cytoscape.Core;

  constructor() {
    effect(() => { void this.api.get(`/api/wiki/wikis/${enc(this.w())}/graph`).then((d) => this.data.set(d)); });
    effect(() => {
      const d = this.data();
      if (d) this.draw(d, this.showMissing());
    });
  }

  private draw(d: any, showMissing: boolean) {
    const nodes = d.nodes.filter((n: any) => showMissing || !n.missing);
    const ids = new Set(nodes.map((n: any) => n.id));
    const edges = d.edges.filter((e: any) => ids.has(e.source) && ids.has(e.target));
    const missing = d.nodes.filter((n: any) => n.missing).length;
    this.stats.set(`${nodes.length} nodes, ${edges.length} links. ${missing} linked pages not written yet.`);
    this.cy?.destroy();
    this.cy = cytoscape({
      container: this.host().nativeElement,
      elements: [
        ...nodes.map((n: any) => ({ data: { ...n, label: n.title, size: 10 + Math.sqrt(n.inbound) * 5 } })),
        ...edges.map((e: any, i: number) => ({ data: { id: `e${i}`, source: e.source, target: e.target } })),
      ],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': (n: any) => COLORS[n.data('type')] ?? '#777',
            width: 'data(size)', height: 'data(size)', label: 'data(label)', 'font-size': 10, color: '#666', 'text-background-color': '#fff', 'text-background-opacity': 0.7, 'text-background-padding': '1px',
            'text-valign': 'bottom', 'text-margin-y': 3, 'text-max-width': '120px', 'text-wrap': 'ellipsis',
          },
        },
        { selector: 'node[?orphan]', style: { 'border-width': 3, 'border-color': '#d32f2f' } },
        { selector: 'node[?missing]', style: { 'background-opacity': 0.35, shape: 'round-rectangle' } },
        { selector: 'edge', style: { width: 0.6, 'line-color': '#9aa4b2', 'target-arrow-color': '#9aa4b2', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.6, 'curve-style': 'bezier', opacity: 0.35 } },
        { selector: 'node:active, node.hover', style: { 'font-size': 11, 'z-index': 10 } },
        { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#1565c0' } },
      ],
      // Hubs (most-linked pages) in the centre, rings outward; readable for small and mid-sized wikis
      layout: {
        name: 'concentric', concentric: (n: any) => n.data('inbound'), levelWidth: () => 3,
        minNodeSpacing: 28, spacingFactor: 1.1, padding: 30, animate: false,
      } as any,
      minZoom: 0.2,
      maxZoom: 2,
      wheelSensitivity: 0.3,
    });
    this.cy.on('tap', 'node', (ev) => {
      const n = ev.target.data();
      this.router.navigate(['/wiki', this.w(), 'pages', n.id]);
    });
  }

  ngOnDestroy() { this.cy?.destroy(); }
}
