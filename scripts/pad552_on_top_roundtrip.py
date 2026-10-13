"""PAD-552 round trip on the real battle scene.

B: the stock scene with B's edits (his earlier file's 36 battle-scene edits, a hidden line, an
added picture).  The Write puts them on a card (apply_scene + serialize), A's project reads
that card back (parse + manifest), A makes his real 70th edits there and saves them with
states.  Loaded on B: does on_top_of see A's edits as made on top of B's?

usage: python roundtrip.py <worktree> <stock scene.radium> <B file.zip> <A file.zip> <scratch>
"""
import copy
import json
import os
import sys
import zipfile

sys.path.insert(0, sys.argv[1])
from PIL import Image  # noqa: E402
from pinball_decryptor.plugins.stern import scene_edit as X, scene_eval as E, scene_tree as T  # noqa: E402,E501

CARD = "/godzilla_le/assets/lcd/auto_loaded/cac32730af42b9d26d26c4bb6e667b07da53113e/scene.radium"
stock_bytes = open(sys.argv[2], "rb").read()
b_ops = json.loads(zipfile.ZipFile(sys.argv[3]).read("pad_scene_edits.json"))["scenes"][CARD]
a_ops = json.loads(zipfile.ZipFile(sys.argv[4]).read("pad_scene_edits.json"))["scenes"][CARD]
scratch = sys.argv[5]
os.makedirs(os.path.join(scratch, "images", "scene_textures", "added"), exist_ok=True)
Image.new("RGBA", (64, 32), (200, 40, 40, 255)).save(
    os.path.join(scratch, "images", "scene_textures", "added", "Logo_1.png"))

man0 = E.manifest(T.parse(stock_bytes))
index = X._man_index(man0)
parent = None                          # the scene's top level
texts = [nid for nid, (n, _k) in index.items() if n["name"].startswith("Line")]
b_ops = list(b_ops) + [{"op": "visible", "node": texts[0], "on": False}]
if True:
    b_ops.append({"op": "add_picture", "parent": parent, "index": 1 << 20,
                  "id": X.FIRST_ADDED_ID + 1, "name": "PAD_Logo",
                  "image": "scene_textures/added/Logo_1.png", "w": 64, "h": 32,
                  "x": 10, "y": 10})
print("B ops", len(b_ops), "kinds", sorted({o["op"] for o in b_ops}), "parent", parent)

tree = T.parse(stock_bytes)
res = X.apply_scene(tree, copy.deepcopy(b_ops), assets_dir=scratch)
print("apply_scene ->", res if not isinstance(res, tuple) else [type(r).__name__ for r in res])
built = tree
print("applied", res[0], "notes", res[1])
man_a = E.manifest(T.parse(T.serialize(built)))

st = X.states_of(man_a, a_ops)
print("A ops", len(a_ops))
print("stock starts elsewhere:", X.starts_elsewhere(man0, a_ops, st))
man_b, notes = X.apply_manifest(man0, b_ops)
print("B preview notes", notes)
print("B preview starts elsewhere:", X.starts_elsewhere(man_b, a_ops, st))
print("differences on B preview:", X.start_differences(man_b, a_ops, st)[:5])
rest = X.on_top_of(man0, b_ops, a_ops, st)
print("on_top_of ->", None if rest is None else "%d ops, same as A's: %s" % (len(rest), rest == a_ops))
again = X.on_top_of(man0, b_ops + a_ops, a_ops, st)
print("loaded again ->", again)

# the B project and A's file for the shots: B = a copy of a stock project with b_ops, A's file
# = his 70th edits with the states of the card B wrote
if len(sys.argv) > 7:
    import shutil
    from PIL import ImageDraw
    src, out = sys.argv[6], sys.argv[7]
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(src, os.path.join(out, "B"))
    proj = os.path.join(out, "B")
    added = os.path.join(proj, "images", "scene_textures", "added")
    os.makedirs(added, exist_ok=True)
    pic = Image.new("RGBA", (420, 90), (150, 20, 20, 255))
    ImageDraw.Draw(pic).text((20, 30), "B'S OWN ADDED BANNER", fill=(255, 255, 255, 255))
    pic.save(os.path.join(added, "Logo_1.png"))
    b_ops[-1].update(w=420, h=90, x=470, y=20)
    X.save(proj, {CARD: b_ops})
    with zipfile.ZipFile(os.path.join(out, "70th on 1.99a.zip"), "w") as z:
        z.writestr("pad_scene_edits.json", json.dumps(
            {"format": 1, "kind": "pad-scene-edits", "scenes": {CARD: a_ops},
             "states": {CARD: st}}))
    print("wrote", out)
