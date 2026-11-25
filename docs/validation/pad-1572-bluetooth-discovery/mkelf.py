"""PAD-1572: main's game-program Write (program text, longer text -> extension segment, MUSIC MODE row)
applied to a stock Godzilla 1.16 ELF, the same function a card Write runs (patched_fw form)."""
import os, shutil, sys, tempfile
sys.path.insert(0, r"C:\Users\david\Documents\development\pad-triage\work\tickets\PAD-1572")
from pinball_decryptor.plugins.stern import engine
src, out, kind = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.copyfile(src, out)
log = lambda m, lvl="info": print("  [%s] %s" % (lvl, m))
pairs = {}
if kind in ("text", "all"):
    pairs = {"GODZILLA VS EBIRAH": "GODZILLA VS EBIRAH, HORROR OF THE DEEP",   # longer: extension segment
             "MOTHRA": "MOTHRX"}                                                  # same length: in place
menu = engine._MusicModeMenu(2, ["ORCHESTRAL", "STANDARD"], log) if kind in ("menu", "all") else None
d = tempfile.mkdtemp()
r = engine._program_text_writes(None, None, src, pairs, out, log, grow={"ok": True, "why": "", "dir": d}, menu=menu)
grown = r[3]
if grown:
    print("  grown:", {k: v for k, v in grown.items() if k != "node"})
    if grown.get("path") and os.path.abspath(grown["path"]) != os.path.abspath(out):
        shutil.copyfile(grown["path"], out)
if menu is not None:
    print("  music mode ok=%s why=%s" % (menu.ok, menu.why))
print("  size %d -> %d" % (os.path.getsize(src), os.path.getsize(out)))
