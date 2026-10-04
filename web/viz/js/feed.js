// The server's three doors: /state once for the world as it is, /recording for everything recorded so far
// (JSON lines), and /events (SSE) from a seq on. Live and replay look the same to the page.
export async function state() {
  return (await fetch("/state", { cache: "no-store" })).json();
}

// The recording's rows after `since` (none when the spectator has no recording); a half-written last line is dropped.
export async function recording(since = 0) {
  const r = await fetch(`/recording?since=${since}`, { cache: "no-store" });
  if (!r.ok) return [];
  const out = [];
  for (const line of (await r.text()).split("\n")) {
    if (!line) continue;
    try { out.push(JSON.parse(line)); } catch { /* a line still being written */ }
  }
  return out;
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
