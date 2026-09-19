#!/usr/bin/env python3
"""roster_entry.py - item 146: give a battle-roster slot of Godzilla its own name and art.

    roster_entry.py map   --scene scene.radium
    roster_entry.py build --scene stock.radium --out ours.radium --art picture.png --name MOTHRA
                          [--katakana <text>] [--font font.ttc] [--portrait-box x0,y0,x1,y1]
                          [--tile-box x0,y0,x1,y1] [--previews DIR]
    roster_entry.py card  --card CARD_COPY.raw --scene ours.radium --stock-scene stock.radium
                          [--game godzilla_pro] [--allow MD5 ...]

Godzilla's battle roster is a FIXED table of seven slots in the game's code (MODE_SDK.md, "A monster
in the roster"), so a monster of your own REPLACES a slot: a mode file with `roster_slot 0` runs
instead of the slot's battle, and this tool redraws the slot on the BATTLE SELECTION screen, the
auto_loaded scene cac32730af42b9d26d26c4bb6e667b07da53113e. Everything is done IN PLACE: every image
keeps its size and offset (BC3 re-encoded) and the name is renamed at the same length, so the scene
keeps its size and `card` rewrites it into its own blocks with the `.sidx` record refreshed.

Slot 0 (EBIRAH) on Godzilla Pro 1.15, measured by item 146 (`map` prints the rest):
  img26  220x234  the colour tile (selected)        img28  530x726  the portrait
  img27  156x70   the katakana name banner          img29  444x740  the GREY SHEET: all seven
                                                                    unselected tiles in one image
The grey sheet is shared by the seven slots, so only the 4x4 BC3 blocks that slot 0's tile touches
are replaced; the other six grey tiles stay byte-identical (the tool checks it).

EMULATOR-PROVEN on Godzilla Pro 1.15 and Premium 1.16 (item 146, MOTHRA; run4 and run5): the renamed,
redrawn entry showed on the glass, selected and unselected. Premium 1.16's stock scene is byte-identical
to Pro 1.15's (md5 fceccfeb), so the same built scene goes onto either card (`card --game godzilla_le`).
Any other build: run `map` and compare before trusting these indexes. The spoken name is not in the
scene: the runtime makes a claimed slot's callout silent (`roster_callout` in the mode file sets one).
The rig never runs the card's own validation. The art is yours: a film frame never goes into the
repository.
"""
import argparse
import collections
import hashlib
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from pinball_decryptor.plugins.stern import dds, engine, radium  # noqa: E402

SCENE_ID = "cac32730af42b9d26d26c4bb6e667b07da53113e"
N_IMAGES = 31
SLOT0 = dict(tile=26, banner=27, portrait=28, sheet=29, sheet_seed=(100, 100), old_name="EBIRAH")
FONTS = (r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\msgothic.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
ORIGINALS = ("pinball\\images", "pinball/images", "images\\stern", "images/stern", "kaiju_premium")


def md5(b):
    return hashlib.md5(b).hexdigest()


def box_arg(s):
    v = [int(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("a box is x0,y0,x1,y1")
    return tuple(v)


# ---- map -----------------------------------------------------------------------------------------
def cmd_map(a):
    data = open(a.scene, "rb").read()
    imgs = engine.parse_radium_images(data)
    print("%s: %d B, md5 %s, %d images" % (a.scene, len(data), md5(data), len(imgs)))
    for k, im in enumerate(imgs):
        print("  img%02d off=%#x fmt=%d disp=%dx%d len=%d near=%s" % (
            k, im["data_off"], im["fmt"], im["disp_w"], im["disp_h"], im["length"],
            engine._nearest_element_name(data, im["data_off"] - 36)))
    texts = [e for e in radium.enumerate_strings(data) if e["kind"] == "display-text"]
    print("  display texts: %s" % ", ".join(sorted({e["text"] for e in texts})))
    return 0


# ---- build ---------------------------------------------------------------------------------------
def center_box(fw, fh, w, h):
    """The largest box of the target's aspect centred in the picture."""
    if fw * h > fh * w:
        cw = fh * w // h
        return ((fw - cw) // 2, 0, (fw - cw) // 2 + cw, fh)
    ch = fw * h // w
    return (0, (fh - ch) // 2, fw, (fh - ch) // 2 + ch)


def inner_mask(opaque, grow):
    """Pixels at least `grow` px inside the opaque region: the stock frame and bevel are kept."""
    m = Image.fromarray((opaque * 255).astype(np.uint8), "L").filter(ImageFilter.MinFilter(2 * grow + 1))
    return np.array(m) == 255


def component(alpha, seed, limit=128):
    h, w = alpha.shape
    comp = np.zeros((h, w), bool)
    comp[seed[1], seed[0]] = True
    dq = collections.deque([(seed[1], seed[0])])
    while dq:
        y, x = dq.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and not comp[ny, nx] and alpha[ny, nx] > limit:
                comp[ny, nx] = True
                dq.append((ny, nx))
    return comp


def splice_blocks(stock_raw, new_raw, pad_w, pad_h, changed):
    """stock_raw with ONLY the 16-byte BC3 blocks that hold a changed pixel taken from new_raw."""
    bx, by = (pad_w + 3) // 4, (pad_h + 3) // 4
    full = np.zeros((by * 4, bx * 4), bool)
    full[:changed.shape[0], :changed.shape[1]] = changed
    touched = full.reshape(by, 4, bx, 4).any(axis=(1, 3))
    out = bytearray(stock_raw)
    for j, i in zip(*np.nonzero(touched)):
        o = (int(j) * bx + int(i)) * 16
        out[o:o + 16] = new_raw[o:o + 16]
    return bytes(out), touched


def cmd_build(a):
    data = bytearray(open(a.scene, "rb").read())
    stock = bytes(data)
    imgs = engine.parse_radium_images(stock)
    if len(imgs) != N_IMAGES:
        sys.exit("%s has %d images, not the %d of the measured scene %s - run `map` and compare first"
                 % (a.scene, len(imgs), N_IMAGES, SCENE_ID))
    old, new = SLOT0["old_name"], a.name.upper()
    if len(new) != len(old):
        sys.exit("the name must be %d letters, the length of %s: it is renamed in place" % (len(old), old))
    frame = Image.open(a.art).convert("RGB")
    if a.previews:
        os.makedirs(a.previews, exist_ok=True)

    def decoded(k):
        im = imgs[k]
        return dds.decode_bc3(stock[im["data_off"]:im["data_off"] + im["length"]], im["pad_w"], im["pad_h"]).copy(), im

    def put(k, raw):
        im = imgs[k]
        assert len(raw) == im["length"], (k, len(raw), im["length"])
        data[im["data_off"]:im["data_off"] + im["length"]] = raw
        if a.previews:
            Image.fromarray(dds.decode_bc3(raw, im["pad_w"], im["pad_h"]), "RGBA").crop(
                (0, 0, im["disp_w"], im["disp_h"])).save(os.path.join(a.previews, "img%02d.png" % k))

    def art(box, w, h, mode="RGB"):
        box = box or center_box(frame.width, frame.height, w, h)
        return np.array(frame.crop(box).resize((w, h), Image.LANCZOS).convert(mode))

    # the portrait (a ~12 px frame kept) and the colour tile (a ~5 px bevel kept)
    for key, grow, box in (("portrait", 12, a.portrait_box), ("tile", 5, a.tile_box)):
        rgba, im = decoded(SLOT0[key])
        w, h = im["disp_w"], im["disp_h"]
        m = inner_mask(rgba[:h, :w, 3] == 255, grow)
        pic = art(box, w, h)
        rgba[:h, :w, :3][m] = pic[m]
        put(SLOT0[key], dds.encode_bc3(rgba))

    # the grey sheet: slot 0's tile only, block-spliced
    rgba, im = decoded(SLOT0["sheet"])
    w, h = im["disp_w"], im["disp_h"]
    alpha = rgba[:h, :w, 3]
    comp = component(alpha, SLOT0["sheet_seed"])
    ys, xs = np.nonzero(comp)
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    if x1 >= 230 or y1 >= 260:
        sys.exit("the grey sheet's slot 0 tile ran into another tile (box x %d-%d y %d-%d): not the measured sheet"
                 % (x0, x1, y0, y1))
    m = inner_mask(comp, 6)
    pic = art(a.tile_box, x1 - x0, y1 - y0, "L").astype(np.float32)
    pic = np.clip((pic - 128) * 1.15 + 118, 0, 255).astype(np.uint8)
    grey = rgba.copy()
    for c in range(3):
        ch = grey[y0:y1, x0:x1, c]
        ch[m[y0:y1, x0:x1]] = pic[m[y0:y1, x0:x1]]
    changed = np.zeros(grey.shape[:2], bool)
    changed[:h, :w] = m
    stock_raw = stock[im["data_off"]:im["data_off"] + im["length"]]
    spliced, touched = splice_blocks(stock_raw, dds.encode_bc3(grey), im["pad_w"], im["pad_h"], changed)
    before = dds.decode_bc3(stock_raw, im["pad_w"], im["pad_h"])
    after = dds.decode_bc3(spliced, im["pad_w"], im["pad_h"])
    diff = (before != after).any(axis=2)
    others = (before[..., 3] > 0) & ~np.pad(comp, ((0, before.shape[0] - h), (0, before.shape[1] - w)))
    outside = diff.copy()
    outside[y0:y1, x0:x1] = False
    print("grey sheet: slot 0 tile box x %d-%d y %d-%d; %d of %d blocks replaced; changed pixels outside the box %d,"
          " in the other tiles %d" % (x0, x1, y0, y1, int(touched.sum()), touched.size, int(outside.sum()),
                                      int((diff & others).sum())))
    if outside.any() or (diff & others).any():
        sys.exit("the grey sheet splice touched pixels outside slot 0's tile - refusing")
    put(SLOT0["sheet"], spliced)

    # the katakana banner: white glyphs, a soft dark shadow, on transparent
    if a.katakana:
        im = imgs[SLOT0["banner"]]
        w, h = im["disp_w"], im["disp_h"]
        font_path = a.font or next((f for f in FONTS if os.path.exists(f)), None)
        if not font_path:
            sys.exit("no font with katakana found: pass --font")
        font = ImageFont.truetype(font_path, 50)
        canvas = Image.new("RGBA", (im["pad_w"], im["pad_h"]), (0, 0, 0, 0))
        bb = ImageDraw.Draw(canvas).textbbox((0, 0), a.katakana, font=font)
        tx, ty = (w - (bb[2] - bb[0])) // 2 - bb[0], (h - (bb[3] - bb[1])) // 2 - bb[1]
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text((tx + 3, ty + 3), a.katakana, font=font, fill=(0, 0, 0, 230))
        canvas = Image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2)), canvas)
        ImageDraw.Draw(canvas).text((tx, ty), a.katakana, font=font, fill=(255, 255, 255, 255))
        put(SLOT0["banner"], dds.encode_bc3(np.array(canvas)))

    # the name: every display-text run of the old name, same length, in place
    hits = [e for e in radium.enumerate_strings(stock) if e["kind"] == "display-text" and e["text"] == old]
    for e in hits:
        off = e["offset"]
        assert stock[off:off + len(old)] == old.encode(), e
        data[off:off + len(new)] = new.encode()

    out = bytes(data)
    assert len(out) == len(stock)
    after_imgs = engine.parse_radium_images(out)
    assert [(x["data_off"], x["length"]) for x in after_imgs] == [(x["data_off"], x["length"]) for x in imgs]
    same = [k for k in range(len(imgs)) if k not in (SLOT0["tile"], SLOT0["banner"], SLOT0["portrait"], SLOT0["sheet"])
            and out[imgs[k]["data_off"]:imgs[k]["data_off"] + imgs[k]["length"]]
            == stock[imgs[k]["data_off"]:imgs[k]["data_off"] + imgs[k]["length"]]]
    open(a.out, "wb").write(out)
    print("%s -> %s: md5 %s -> %s, %d B; %s renamed %s x%d; images byte-identical: %d of %d others" % (
        a.scene, a.out, md5(stock), md5(out), len(out), old, new, len(hits), len(same), len(imgs) - 4))
    return 0


# ---- card ----------------------------------------------------------------------------------------
def cmd_card(a):
    from pinball_decryptor.plugins.stern import sidx
    from pinball_decryptor.plugins.stern.explorer import CardImage
    low = os.path.abspath(a.card).lower()
    if any(o in low for o in ORIGINALS):
        sys.exit("refusing %s: it looks like an original image or a flashed card - write a COPY" % a.card)
    rel = "/%s/assets/lcd/auto_loaded/%s/scene.radium" % (a.game, SCENE_ID)
    want, stock = open(a.scene, "rb").read(), open(a.stock_scene, "rb").read()
    tmp = a.card + ".scene.tmp"
    with CardImage(a.card) as ci:
        ci.extract_file(2, rel, tmp)
        cur = open(tmp, "rb").read()
        os.unlink(tmp)
        print("on the card: %s (stock %s, ours %s)" % (md5(cur), md5(stock), md5(want)))
        if cur == want:
            print("already written")
        else:
            if cur != stock and md5(cur) not in set(a.allow or ()):
                sys.exit("the card's scene is neither the stock scene nor an --allow'ed build - refusing")
            n, refreshed = ci.replace_file(2, rel, a.scene)
            print("wrote %d B, .sidx record refreshed: %s" % (n, refreshed))
    with CardImage(a.card) as ci:
        ci.extract_file(2, rel, tmp)
        back = open(tmp, "rb").read()
        os.unlink(tmp)
        r = ci._reader(2)
        _path, node = sidx.find_sidx(r)
        man = r.read_file_bytes(node)
        recs, _crc, fmt = sidx.parse_records(man)
        hm, dg = sidx.digests(back)
        ok = all(man[o:o + len(b)] == b for o, b in sidx.record_field_writes(recs[rel.lstrip("/")], hm, dg, fmt,
                                                                              size=len(back)))
    print("read back: md5 %s %s ours; .sidx record %s" % (md5(back), "==" if back == want else "!=",
                                                          "right" if ok else "WRONG"))
    return 0 if back == want and ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="list the scene's images and display texts")
    m.add_argument("--scene", required=True)
    b = sub.add_parser("build", help="rename and redraw slot 0 into a copy of the scene")
    b.add_argument("--scene", required=True, help="the stock scene.radium")
    b.add_argument("--out", required=True)
    b.add_argument("--art", required=True, help="a picture for the portrait and the tiles")
    b.add_argument("--name", required=True, help="the new name, as long as EBIRAH")
    b.add_argument("--katakana", help="the name banner's text (left stock when absent)")
    b.add_argument("--font", help="a font with katakana for the banner")
    b.add_argument("--portrait-box", type=box_arg, help="crop of --art for the portrait (default: centred)")
    b.add_argument("--tile-box", type=box_arg, help="crop of --art for the tiles (default: centred)")
    b.add_argument("--previews", help="write the redrawn images as PNGs here")
    c = sub.add_parser("card", help="write the scene onto a card COPY, .sidx record refreshed, and verify")
    c.add_argument("--card", required=True)
    c.add_argument("--scene", required=True)
    c.add_argument("--stock-scene", required=True)
    c.add_argument("--game", default="godzilla_pro")
    c.add_argument("--allow", action="append", help="md5 of an earlier build of ours that may be replaced")
    a = p.parse_args(argv)
    return {"map": cmd_map, "build": cmd_build, "card": cmd_card}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
