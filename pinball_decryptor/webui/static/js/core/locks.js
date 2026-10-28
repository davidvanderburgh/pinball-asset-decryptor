// Which tabs work on a project's extracted files, and why one can't be used
// yet (PAD-224).  The rail greys such a tab out, its page opens under a
// banner saying why, and the Select card tab lists every tab with what it
// can do before and after an extract.  ``project_state`` is the shell's
// (webui/extract_helpers.extract_state): undefined = not known yet (nothing
// is greyed), null = no project folder.

// "extract" = reads the files an extract pulls off the card; "project" =
// only saves its changes into a project folder
export const NEEDS = {
  audio: "extract", video: "extract", images: "extract", text: "extract", scenes: "extract",
  write: "extract", modpack: "extract",
  modes: "project", defaults: "project",
};

// What rail entry *t* needs: its tab's own answer for this manufacturer
// (webui/tabs/base.py rail_needs) over the table above; undefined = nothing.
export function needOf(t) {
  const need = t && t.needs != null ? t.needs : NEEDS[t && t.ns];
  return need === "none" ? undefined : need;
}

// one line per tab for the Select card tab's list
export const WHAT = {
  partitions: "Browse the card's partitions and copy files off it.",
  compare: "Compare it with another card and see what changed.",
  emulate: "Run the game on this computer.",
  emulate_jjp: "Run the game on this computer.",
  emulate_ap: "Run the game on this computer.",
  emulate_bof: "Run the game on this computer.",
  emulate_dp: "Run the game on this computer.",
  emulate_spooky: "Run the game on this computer from its update file.",
  emulate_pb: "Run the game on this computer from its update file (Predator so far).",
  emulate_spike1: "Run the game on this computer.",
  vpx: "Play a Visual Pinball table with this game behind it.",
  multiboot: "Put it on one card with other games behind a boot menu.",
  defaults: "Change the game's factory settings.",
  modes: "Make your own modes.",
  audio: "Replace sounds, music and call-outs.",
  video: "Replace videos.",
  images: "Replace pictures.",
  text: "Replace on-screen text.",
  color: "Correct your pictures' and videos' colors for the machine's screen.",
  scenes: "See each scene as the machine draws it; move, resize, recolour or add to it.",
  write: "Build a new card with your changes.",
  write_flash: "Flash a card image onto an SD card, or build one with your changes.",
  modpack: "Share your changes as a zip, or apply someone else's.",
};

// null when rail entry *t* can be used, else {short, long, need}
export function tabLock(t, ps) {
  const need = needOf(t);
  const label = t.label;
  if (!need || ps === undefined) return null;
  const tab = "The " + label + " tab";
  if (need === "project") {
    if (ps) return null;
    return { need, short: "Needs a project folder: there isn't one yet.",
      long: tab + " saves its changes into a project folder, and there isn't one yet. "
        + "Choose one on the Extract tab (you don't have to extract to use this tab)." };
  }
  if (!ps) {
    return { need, short: "Needs an extract: there is no project folder yet.",
      long: tab + " works on the files an extract pulls off the card, and there is no project folder yet. "
        + "Select the card, then extract it into a project folder on the Extract tab." };
  }
  if (ps.archived) {
    return { need, short: "Needs an extract: this project is archived.",
      long: ps.name + " is archived, so its extracted files are not on disk and " + tab.charAt(0).toLowerCase() + tab.slice(1)
        + " has nothing to work on. Extract into it again to bring them back: your edits are set aside and restored automatically." };
  }
  if (!ps.extracted) {
    return { need, short: "Needs an extract: nothing is extracted into this project yet.",
      long: "Nothing has been extracted into " + ps.name + " yet, so " + tab.charAt(0).toLowerCase() + tab.slice(1)
        + " has nothing to work on. Extract the card into this project folder first." };
  }
  return null;
}
