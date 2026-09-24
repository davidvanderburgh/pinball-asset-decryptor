#!/usr/bin/env python3
"""port_tool.py - draft the PORT for a game build from a port that already works (item 135).

    port_tool.py <reference game ELF> <reference port> <target game ELF> -o <draft port>
                 [--game NAME] [--version TEXT]
    port_tool.py recipe <reference game ELF> <reference port> [-o <recipe>]
                 the reference half of every draft, kept so a draft needs only the target
                 (default -o: ports/recipes/<port>.recipe.gz beside the port)

A port tells the mode runtime where a game's functions and globals are in ONE build
(MODE_SDK.md, "Ports"). This drafts one for a new build from a proven one, and says,
entry by entry, how sure it is:

  site   located by a masked signature of the reference function's first instructions,
         strict (only branch and literal offsets masked) or loose (small immediates too);
         a PLT stub (a library call such as __dynamic_cast) by its imported symbol name.
         Its two instruction words are read from the target, as port_words.py does.
  data   derived: every place the reference code loads the address is found, the
         function around it is located in the target, the instructions from its start to
         that place must line up, and the address the TARGET loads there is taken. At
         least two agreeing places are needed (one for a global in ONE_PLACE_DATA, which
         says why one is enough); disagreement is reported, not voted away.
  scene  a 40-hex id the reference code loads as a string is derived the same way, and
         the target's string read back.
  value / shot / callout / text / a scene no code names
         COPIED from the reference and marked unverified: struct offsets, shot bits and
         sound ids are not in any instruction this can line up. The emulator decides
         (the shot census, and a mode that runs). A scene id is copied only if the
         target program names it too.
  ANOTHER TITLE (--game jaws_le from godzilla_pro; _le/_pro are one title)
         shot, callout and text lines are LEFT OUT as comments: they are the reference
         title's, and so are the values in TITLE_VALUES (a rule's light owner and light
         set, an award screen type). Other values are still copied: framework offsets.

Nothing is guessed silently: an entry it cannot place is written as a comment saying why,
and the runtime then treats that capability as absent. Under it, CANDIDATES where there
are any - the framework calls the reference function makes that the target has (a title's
own wrapper usually ends in one), or for a scene the first id after the same neighbouring
strings - for a person to prove (MODE_SDK.md, "Making a port"). Exit status 1 if a CORE
site (tick, shot_dispatch, ball_end, score_add) or core global is missing.

The drafting is pinball_decryptor/plugins/stern/portgen.py (the app drafts with it too);
every name this tool had is importable from here as before.
"""
import argparse
import os
import sys

# the package this file ships beside (a checkout or an install: four folders up)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if os.path.isdir(os.path.join(_ROOT, "pinball_decryptor")) and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from pinball_decryptor.plugins.stern import portgen as _lib  # noqa: E402

globals().update({k: v for k, v in vars(_lib).items() if not k.startswith("__")})


def _elf(path):
    try:
        return _lib.Elf(path)
    except (OSError, _lib.PortgenError) as e:
        raise SystemExit(str(e))


def recipe_main(argv):
    ap = argparse.ArgumentParser(prog="port_tool.py recipe",
                                 description="the reference half of every draft, from a proven port's program")
    ap.add_argument("ref_elf")
    ap.add_argument("ref_port")
    ap.add_argument("-o", "--out")
    args = ap.parse_args(argv)
    text = open(args.ref_port, encoding="utf-8").read()
    name = os.path.basename(args.ref_port)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.ref_port)), "recipes",
                                   name[:-len(".port")] + ".recipe.gz")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    r = _lib.compile_recipe(_elf(args.ref_elf), text, name)
    _lib.save_recipe(r, out)
    print("wrote %s (%d sites, %d globals, %d scenes; %d sequences; bus bound %d, generation %s)"
          % (out, len(r["sites"]), len(r["data"]), len(r["scenes"]), len(r["chains"]), r["bus_bound"],
             r["generation"] or "?"))
    return 0


def main(argv):
    if argv[:1] == ["recipe"]:
        return recipe_main(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ref_elf")
    ap.add_argument("ref_port")
    ap.add_argument("target_elf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--game")
    ap.add_argument("--version")
    args = ap.parse_args(argv)
    text = open(args.ref_port, encoding="utf-8").read()
    d = _lib.draft(_elf(args.ref_elf), text, _elf(args.target_elf), args.game, args.version,
                   port_name=args.ref_port, target_name=args.target_elf)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(d.text)
    print("wrote %s" % args.out)
    for k in sorted(d.report):
        print("  %-16s %d" % (k, d.report[k]))
    print("  (value, shot, callout and text lines are COPIED from the reference, unverified)")
    if d.missing_core:
        print("CORE MISSING: %s - the runtime would hook nothing with this port" % ", ".join(d.missing_core))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
