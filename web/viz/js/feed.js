// The server's three doors: /state once for the world as it is, /recording for everything recorded so far
// (JSON lines), and /events (SSE) from a seq on. Live and replay look the same to the page.
export async function state() {
  return (await fetch("/state", { cache: "no-store" })).json();
}

// The recording's rows after `since`, each handed to `onRow` as it is parsed off the response body (the body is
// never held whole: a 72 MB recording came in as one string before); none when the spectator has no recording.
// Returns how many rows were read.
export async function recording(since = 0, onRow) {
  const r = await fetch(`/recording?since=${since}`, { cache: "no-store" });
  if (!r.ok || !r.body) return 0;
  return readLines(r.body.getReader(), onRow);
}

// JSON lines off a byte-stream reader, one row to `onRow` per complete line; a line that does not parse (one still
// being written, or the half line a file ends on) is dropped. Returns the count handed on.
export async function readLines(reader, onRow) {
  const dec = new TextDecoder();
  let buf = "", n = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buf += dec.decode(value, { stream: !done });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i);
      buf = buf.slice(i + 1);
      if (!line) continue;
      try { onRow(JSON.parse(line)); n++; } catch { /* a line still being written */ }
    }
    if (done) return n;
  }
}

export function stream(since, { onEvent, onStatus }) {
  let seq = since || 0;
  const es = new EventSource(`/events?since=${seq}`);
  es.onopen = () => onStatus(true, "connected");
  es.onerror = async () => {
    onStatus(false, "reconnecting");
    // a restarted spectator counts from 1 again: our cursor is ahead of it, so start the page over
    try {
      const st = await state();
      if ((st.seq || 0) < seq) location.reload();
    } catch { /* still down; EventSource retries by itself */ }
  };
  for (const type of ["hello", "snapshot", "call", "event", "notebook", "status"]) {
    es.addEventListener(type, (m) => {
      try {
        const ev = JSON.parse(m.data);
        seq = ev.seq;
        onEvent(ev);
      } catch (e) { onStatus(true, `bad event: ${e.message}`); }
    });
  }
  return { close: () => es.close() };
}
