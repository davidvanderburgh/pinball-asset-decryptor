"""block_tool.py <game program> <port> [--defaults 21,23] [--dry] - write the port's block section (PAD-363): one
veto site per mode of the game's that a mode of ours may keep from starting, read from the game program by the
app's stock scanner (pinball_decryptor/plugins/stern/game_mode_blocks.py). Replaces an earlier block section
(every block_start_* / block_obj_* / block_name_* line, block_default, and PAD-347's hand-made lines) and keeps
everything else of the port, the battle rule's block_battle_* lines included. --defaults: the ids checked on
this title, which a mode that lists none blocks. Run under the repo root's Python (it imports the app)."""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))
from pinball_decryptor.plugins.stern import game_mode_blocks as G  # noqa: E402

OLD = re.compile(r"^(site block_start_\d+|data block_obj_\d+|text block_name_\d+|value block_default|"
                 r"data block_mode_table|value block_mode_count|value block_mode_ids|site stock_mode_start)\b")
OLD_COMMENT = ("# PAD-347: a mode may keep the game's modes from starting", "# PAD-363: the game's own modes a mode")


def strip_old(lines):
    out, skipping = [], False
    for ln in lines:
        if ln.startswith(OLD_COMMENT):
            skipping = True                      # an old section's comment block
            continue
        if skipping and ln.startswith("#") and not ln.startswith("# The battle rule's shot handler"):
            continue
        skipping = False
        if OLD.match(ln):
            continue
        out.append(ln)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("port")
    ap.add_argument("--defaults", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    defaults = {int(x) for x in a.defaults.split(",") if x.strip()}
    modes = G.read_modes(open(a.game, "rb").read())
    raw = open(a.port, "rb").read().decode("utf-8")
    crlf = "\r\n" in raw
    lines = strip_old(raw.replace("\r\n", "\n").rstrip("\n").split("\n"))
    names = {m.id: m.name for m in modes}
    left_out = ["%d %s (%s)" % (m.id, m.name, "multiball" if m.multiball else "not vetoable")
                for m in modes if not m.blockable]
    section = G.port_lines(modes, defaults, header=["left out: " + ", ".join(left_out)] if left_out else None)
    for d in sorted(defaults):
        if d not in {m.id for m in modes if m.blockable}:
            sys.exit("--defaults %d is not a mode this tool can name (%s)" % (d, names.get(d, "no such id")))
    out = "\n".join(lines + [""] + section) + "\n"
    if a.dry:
        print("\n".join(section))
        return
    if crlf:
        out = out.replace("\n", "\r\n")
    open(a.port, "wb").write(out.encode("utf-8"))
    print("%s: %d modes named, defaults %s; left out %d" % (os.path.basename(a.port), sum(m.blockable for m in modes),
                                                          sorted(defaults) or "none", len(left_out)))


if __name__ == "__main__":
    main()
