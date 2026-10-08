/** POST + Server-Sent Events reader (EventSource only supports GET). Yields {event, data} until the stream ends. */
export async function* postSse(url: string, body: unknown, signal?: AbortSignal): AsyncGenerator<{ event: string; data: string }> {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  });
  if (resp.status === 401) window.dispatchEvent(new Event('wb-unauthorized'));
  if (!resp.ok || !resp.body) {
    let detail = `${resp.status} ${resp.statusText}`;
    try { detail = (await resp.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value.replace(/\r\n/g, '\n');
    let idx: number;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      const data: string[] = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (data.length || event !== 'message') yield { event, data: data.join('\n') };
    }
  }
}
