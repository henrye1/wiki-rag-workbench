import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

/** Thin typed wrapper over the BFF (/api). The BFF adds API keys and proxies /api/rag/* and /api/wiki/*. */
@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);

  get<T = any>(url: string, params?: Record<string, any>): Promise<T> {
    return firstValueFrom(this.http.get<T>(url, { params: toParams(params) }));
  }
  text(url: string): Promise<string> {
    return firstValueFrom(this.http.get(url, { responseType: 'text' }));
  }
  post<T = any>(url: string, body: any = {}, params?: Record<string, any>): Promise<T> {
    return firstValueFrom(this.http.post<T>(url, body, { params: toParams(params) }));
  }
  put<T = any>(url: string, body: any): Promise<T> {
    return firstValueFrom(this.http.put<T>(url, body));
  }
  delete<T = any>(url: string): Promise<T> {
    return firstValueFrom(this.http.delete<T>(url));
  }
  upload<T = any>(url: string, file: File, params?: Record<string, any>, fields?: Record<string, string>): Promise<T> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    for (const [k, v] of Object.entries(fields ?? {})) fd.append(k, v);
    return firstValueFrom(this.http.post<T>(url, fd, { params: toParams(params) }));
  }

  // ---- RAG ----
  ragDocuments() { return this.get<any[]>('/api/rag/documents'); }
  ragChunks(paraRef: string) { return this.get<any[]>('/api/rag/chunks', { para_ref: paraRef }); }

  // ---- Wiki ----
  wikis() { return this.get<any[]>('/api/wiki/wikis'); }
  wiki(w: string) { return this.get<any>(`/api/wiki/wikis/${enc(w)}`); }
  pages(w: string) { return this.get<any[]>(`/api/wiki/wikis/${enc(w)}/pages`); }
  page(w: string, slug: string) { return this.get<any>(`/api/wiki/wikis/${enc(w)}/pages/${enc(slug)}`); }
  job(id: string) { return this.get<any>(`/api/wiki/jobs/${enc(id)}`); }
}

export const enc = encodeURIComponent;

function toParams(p?: Record<string, any>): HttpParams | undefined {
  if (!p) return undefined;
  let hp = new HttpParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) v.forEach((x) => (hp = hp.append(k, String(x))));
    else hp = hp.set(k, String(v));
  }
  return hp;
}

/** Extract a readable message from an HttpErrorResponse / Error. */
export function errMsg(e: any): string {
  const d = e?.error?.detail ?? e?.error;
  if (typeof d === 'string') return d;
  if (d?.message) return d.message + (d.source ? ` (${d.source})` : '') + (d.document_id ? ` (${d.document_id})` : '');
  if (Array.isArray(d)) return d.map((x: any) => x.msg ?? JSON.stringify(x)).join('; ');
  return e?.message ?? String(e);
}
