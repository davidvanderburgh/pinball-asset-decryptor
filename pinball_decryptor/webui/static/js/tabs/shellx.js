// The shellx service is not a rail tab (its key is empty, so the rail never
// shows it): its windows live in ../shellx_dialogs.js, which shell.js
// imports.  This page only answers a stray navigation.
import { html, Empty } from "../core/ui.js";

export default function ShellExtras() {
  return html`<div class="page"><${Empty} title="Not a tab" icon="info">The app-wide menus and windows are in the top bar: the project menu, the ? tips and the gear.<//></div>`;
}
