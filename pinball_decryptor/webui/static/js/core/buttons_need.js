// The step that puts remote buttons on a machine, under its service buttons: shared by the Network tab's
// Machine screen card (tabs/network.js) and My machines' Remote panel (shell.js).  State is the `network`
// namespace (webui/tabs/network.py: buttons_note, buttons_kind, buttons_need, buttons_busy).
import { html, Button, call, cx } from "./ui.js";

// PAD-1634 (David: "the red text here doesn't make sense in this context ... the user flow is all over the
// place"): what is in the way of the service buttons, said under them, with the step that fits right there: a
// card with no remote buttons gets them from here (over remote access; the machine restarts, asked first).
export function ButtonsNeed({ n, off, size }) {
  const kind = n.buttons_kind;
  const text = n.buttons_note;
  if (!text && n.buttons_need !== "install") return null;
  return html`<div class="row wrap net-btn-need" style="gap:6px 10px;align-items:center">
    ${text ? html`<span role=${kind === "err" ? "alert" : "status"} class=${cx("small", kind === "err" ? "err-ink" : kind === "ok" ? "ok-ink" : "muted")}>${text}</span>` : null}
    ${n.buttons_need === "install" ? html`<${Button} size=${size} kind="primary" disabled=${off || !!n.buttons_busy || !!n.direct_busy}
      title="Puts remote buttons on this machine over remote access. The machine restarts (about a minute); a game being played ends."
      onClick=${() => call("network.buttons_turn_on")}>Turn on remote buttons…<//>` : null}
  </div>`;
}
