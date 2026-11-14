#!/usr/bin/env python3
"""s3pf.py - the virtual playfield's tables for a Spike 3 card (PAD-1090).

    s3pf.py GAME_ELF CARD_ROOT TITLE OUT_DIR [SWITCH_LIST]

Writes OUT_DIR (= $PAD_TABLES/<title>, what the Spike 2 rig's playfield.py
reads) from the card's OWN data, exactly as its test menu draws the machine:

  device_xy.txt         every placed switch, coil and LED: the title's device
                        records (s3nodes.records) in devicexy.py's columns
  group_node_exact.txt  group -> node; on Spike 3 a device's group IS its
                        board's place in the node directory, so nothing is
                        inferred (coilmap.read_exact_group_node)
  node_ident.txt        the node directory, nbdir v2's `node= type= group=`
  playfield.png         the picture the layout is drawn on, from the card's
                        assets/nuk/images (and each other placed picture
                        beside it under its own name, for the cabinet views)
  switch_list.txt       the run's switch table (s3bridge.py writes it)

No manufacturer art leaves the card: the pictures are copied into the run's
own slot directory, which is deleted with the run's other scratch.
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "spike2_emu"))
import s3nodes  # noqa: E402

READER_TAG = "# reader-rev "
CLASS = {"switch": 1, "coil": 2, "led": 3, "gi": 3}


def layout_image(recs):
    """The picture a title's LAYOUT is drawn on: the one image carrying the
    most device classes, then the most devices (devicexy.layout_image's rule -
    a topper carries lamps alone). Unplaced records (no x, y) do not count:
    Walking Dead and Fallout name 432 strip lamps "playfield" at x = 0."""
    per = {}
    for r in recs:
        if r["image"] and r["x"] and r["w"]:
            per.setdefault(r["image"], []).append(r)
    if not per:
        return None
    return max(per.items(), key=lambda kv: (len({r["kind"] for r in kv[1]}),
                                            len(kv[1]), kv[0] == "playfield"))[0]


def is_playfield_picture(name):
    """A top-down playfield drawing, by the names every card uses for one:
    `playfield`, `TestMenu/picnic_pf`, `TestMode/Playfield_AK_..._cropped`.
    Not the cabinet front, topper, speaker panel or backbox."""
    n = (name or "").lower().rsplit("/", 1)[-1]
    return "playfield" in n or n == "pf" or n.endswith("_pf") or n.startswith("pf_")


def _words(s):
    return set(re.split(r"[^a-z0-9]+", s.lower()))


def find_picture(card_root, title, name):
    """The png the title's test menu names `name`, or None. Its own assets
    first (games/<title>/assets/*/images/<name>.png), then the shared
    spike_menu's. A bare "playfield" is the model's own drawing: the title
    ships one per model (`pokemon_playfield_le.png`, `buck_pro_playfield.png`)
    and the title's words pick it (whole words: "scaLEd" is not LE)."""
    roots = []
    g = os.path.join(card_root, "games", title)
    if not os.path.isdir(g):
        # a multi-boot card (PAD-1263): every image's tree is under games/pad/imgN
        pad = os.path.join(card_root, "games", "pad")
        for d in sorted(os.listdir(pad)) if os.path.isdir(pad) else ():
            if os.path.isdir(os.path.join(pad, d, title)):
                g = os.path.join(pad, d, title)
                break
    for base in (os.path.join(g, "assets"), os.path.join(g, "spike3", "spike_menu", "assets")):
        if os.path.isdir(base):
            roots += [os.path.join(base, d, "images") for d in sorted(os.listdir(base))]
    for r in roots:
        p = os.path.join(r, name + ".png")
        if os.path.isfile(p):
            return p
    if "/" in name:
        return None
    want = _words(title)
    best = None
    for r in roots:
        for dp, _dn, fn in os.walk(r):
            for f in sorted(fn):
                if not f.lower().endswith(".png") or name.lower() not in _words(f[:-4]):
                    continue
                score = len(want & _words(f[:-4]) & {"le", "pro", "prem", "premium", "elg"})
                if best is None or score > best[0]:
                    best = (score, os.path.join(dp, f))
    return best[1] if best else None


def device_xy(title, recs, image, pic_size):
    lines = ["# %s device positions, from the card's device records (Spike 3, s3pf.py)." % title,
             "# binary: spike3",
             "%s%d" % (READER_TAG, 3),
             "# %d records, %d on the layout image." % (
                 len(recs), sum(1 for r in recs if r["image"] == image)),
             "# playfield image: %s (%dx%d)" % (image or "(none)", pic_size[0], pic_size[1]),
             "# class     name                                   x     y    w    h  grp index  conn   image"]
    for r in recs:
        if not r["name"] or r["kind"] not in CLASS:
            continue
        name = re.sub(r"\s+", " ", r["name"]).strip()
        conn = re.sub(r"\s+", "_", r["conn"]) if r["conn"] else "-"
        img = re.sub(r"\s+", "_", r["image"]) if r["image"] else "-"
        lines.append("%-9s %-34s %5d %5d %4d %4d %4d %5d  %-6s %s" % (
            "led" if r["kind"] == "gi" else r["kind"], name, r["x"], r["y"], r["w"], r["h"],
            r["group"], r["index"], conn, img))
    return "\n".join(lines) + "\n"


def build(elf, card_root, title, out, switch_list=None):
    os.makedirs(out, exist_ok=True)
    e = s3nodes.Elf(elf)
    lo, cat = s3nodes.catalog(e)
    drows = s3nodes.directory(e, cat)
    recs = s3nodes.records(e, drows)
    image = layout_image(recs)
    # A PLAYFIELD OR NOTHING (David: Fallout's window showed the cabinet
    # front). fallout_le 0.81 places no playfield device - its records' x, y
    # are all 0 - so the vote fell to the cabinet front's 18. Not a playfield:
    # no layout at all, and the window lists every switch (clickable) beside
    # the live light grid, as for a Spike 2 title without positions.
    if image and not is_playfield_picture(image):
        print("[s3pf] %s places nothing on its playfield (only on %s): the "
              "window lists the switches instead" % (title, image), flush=True)
        recs = [dict(r, image="") for r in recs]
        image = None
    size = (0, 0)
    pics = {}
    for name in sorted({r["image"] for r in recs if r["image"] and r["x"]}):
        p = find_picture(card_root, title, name)
        if p:
            pics[name] = p
    if image and image in pics:
        shutil.copyfile(pics[image], os.path.join(out, "playfield.png"))
        try:
            from PIL import Image
            size = Image.open(pics[image]).size
        except Exception:                                  # noqa: BLE001
            pass
    pdir = os.path.join(out, "pictures")
    os.makedirs(pdir, exist_ok=True)
    for name, p in pics.items():
        dst = os.path.join(pdir, name.replace("/", "__") + ".png")
        shutil.copyfile(p, dst)
    with open(os.path.join(out, "device_xy.txt"), "w") as f:
        f.write(device_xy(title, recs, image, size))
    with open(os.path.join(out, "group_node_exact.txt"), "w") as f:
        f.write("# group node - Spike 3: a device's group is its board's place in the node directory\n")
        for i, (nid, _code, _fl) in enumerate(drows):
            f.write("%d %d\n" % (i + 1, nid))
    with open(os.path.join(out, "node_ident.txt"), "w") as f:
        f.write("# node directory (Spike 3, s3pf.py)\n")
        for i, (nid, code, _fl) in enumerate(drows):
            typ = (cat.get(code - 2, (None, 0, None, None))[2]) or "unknown"
            f.write("node=%d type=%s group=%d name=%s\n" % (nid, typ, i + 1, typ))
    if switch_list and os.path.isfile(switch_list):
        shutil.copyfile(switch_list, os.path.join(out, "switch_list.txt"))
    placed = sum(1 for r in recs if r["image"] == image)
    print("[s3pf] %s: %d devices, %d on %s%s" % (
        title, len(recs), placed, image or "(no layout)",
        (" (%s, %dx%d)" % (os.path.basename(pics[image]), size[0], size[1]))
        if image in pics else (" - no picture on the card" if image else "")), flush=True)
    return image, pics.get(image)


def main():
    a = sys.argv[1:]
    if len(a) < 4:
        print(__doc__)
        return 2
    build(a[0], a[1], a[2], a[3], a[4] if len(a) > 4 else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
