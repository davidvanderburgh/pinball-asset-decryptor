// PAD-1279: the TEST tick on a row of the Images, Video, Audio and Scenes tabs - it puts
// that picture, clip, sound or scene (its resting frame) on the test card, with the
// project's color profile in it (the Test card tab builds the card).
import { html, call, tip } from "./ui.js";

export const TEST_TIP = "Put it on the test card (the Test card tab): a small card that shows it on "
  + "the machine, with this project's color profile, without building the whole game.";

// A Table column: ns is the tab's (its set_test rpc), tags the ticked rows' keys (the
// tab's test_tags), keyOf(row) a row's key or null for a row with no tick.
export function testCol({ ns, tags, keyOf, full }) {
  const on = new Set(tags || []);
  return {
    key: "test", label: "Test", width: "minmax(44px,44px)", cls: "tc-cell", title: TEST_TIP,
    render: (r) => {
      const k = keyOf(r);
      if (k == null) return "";
      const ticked = on.has(k);
      return html`<input type="checkbox" class="tc-tick" checked=${ticked} disabled=${!ticked && !!full}
        aria-label="Put it on the test card" ...${tip(full && !ticked ? "The test card is full (64 items)" : TEST_TIP)}
        onClick=${(e) => {
          e.stopPropagation();
          if (e.detail > 1) { e.preventDefault(); return; }
          call(ns + ".set_test", k, !ticked);
        }} />`;
    },
  };
}
