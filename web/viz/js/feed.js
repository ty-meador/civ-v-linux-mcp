// The stream: /state once for the world as it is, then /events (SSE) from that seq on. Live and replay look the same.
export function connect({ onState, onEvent, onStatus }) {
  let es = null;
  let seq = 0;
  const start = async () => {
    try {
      const st = await (await fetch("/state", { cache: "no-store" })).json();
      seq = st.seq || 0;
      onState(st);
    } catch (e) {
      onStatus(false, `state: ${e.message}`);
      setTimeout(start, 3000);
      return;
    }
    es = new EventSource(`/events?since=${seq}`);
    es.onopen = () => onStatus(true, "connected");
    es.onerror = () => onStatus(false, "reconnecting");
    for (const type of ["hello", "snapshot", "call", "event", "notebook", "status"]) {
      es.addEventListener(type, (m) => {
        try {
          const ev = JSON.parse(m.data);
          seq = ev.seq;
          onEvent(ev);
        } catch (e) { onStatus(true, `bad event: ${e.message}`); }
      });
    }
  };
  start();
  return { close: () => es && es.close() };
}
