// Boot: load the state, render the shell, follow the event stream.
import { html, render } from "./vendor/preact-htm.js";
import { loadAll, connect, POLL, stopPolling } from "./core/store.js";
import { Shell, applyZoom } from "./shell.js";

async function boot() {
  const root = document.getElementById("app");
  try {
    await loadAll();
  } catch (err) {
    root.innerHTML = '<div style="padding:40px;font-family:sans-serif">The app did not answer (' +
      String(err.message || err) + '). Close this window and start the app again.</div>';
    return;
  }
  try {
    const z = (window.__padState && window.__padState.zoom) || null;
    if (z) applyZoom(z);
  } catch (e) { /* ignore */ }
  render(html`<${Shell} />`, root);
  connect();
  // captures and tests: say when the first render has settled
  const settle = Number(new URLSearchParams(location.search).get("settle") || 0);
  if (POLL && settle > 0) {
    setTimeout(() => { stopPolling(); window.__padReady = true; }, settle);
  } else {
    setTimeout(() => { window.__padReady = true; }, 400);
  }
}

boot();
