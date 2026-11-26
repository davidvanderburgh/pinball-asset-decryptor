// The starting screen (index.html's #page-boot, the ball bouncing around the
// window) and how it leaves: it fades away over the app's first screen, the
// ball lifting off as it goes.  Called by whatever draws a first screen (the
// shell for the disclaimer and the picker, the tab host once the first tab
// is in); every call after the first does nothing.

const FADE_MS = 450;        // index.html's transition

export function dismissPageBoot() {
  const el = document.getElementById("page-boot");
  if (!el || el.dataset.out) return;
  el.dataset.out = "1";
  let instant = false;
  try {
    // captures and tests wait for a settled page, never for a fade
    instant = !!navigator.webdriver
      || new URLSearchParams(location.search).has("settle")
      || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) { /* ignore */ }
  if (instant) { el.remove(); return; }
  el.classList.add("out");
  setTimeout(() => el.remove(), FADE_MS + 40);
}
