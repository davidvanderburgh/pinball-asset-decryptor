"""PAD-552 round 5: make computer B's project replace the battle scene's game pictures with his
own art (the V1.97 card's pictures of the same nodes), and the real 70th file with the states of
the card B wrote (so it is made on top of B's edits).

usage: python bcase_replaced.py <worktree> <bcase dir> <v197 proj> <real 70th zip> <out dir>
"""
import json
import os
import shutil
import sys
import zipfile

sys.path.insert(0, sys.argv[1])
from pinball_decryptor.core import staged_changes  # noqa: E402
from pinball_decryptor.plugins.stern import scene_edit as X, scene_share as S  # noqa: E402

bcase, v197, real, out = sys.argv[2:6]
CARD = "/godzilla_le/assets/lcd/auto_loaded/cac32730af42b9d26d26c4bb6e667b07da53113e/scene.radium"
if os.path.exists(out):
    shutil.rmtree(out)
shutil.copytree(os.path.join(bcase, "B"), os.path.join(out, "B"))
proj = os.path.join(out, "B")
stock = X.trees_of(proj)[CARD]
mine = X.trees_of(v197)[CARD]
by_node = {}
for pic, nodes in S.manifest_drawers(mine).items():
    for n in nodes:
        by_node[tuple(n)] = pic
art = os.path.join(out, "B art")
os.makedirs(art)
picks = {}
for pic, nodes in S.manifest_drawers(stock).items():
    theirs = next((by_node[tuple(n)] for n in nodes if tuple(n) in by_node), None)
    if theirs and theirs != pic:
        src = os.path.join(v197, "images", *theirs.split("/"))
        dst = os.path.join(art, os.path.basename(theirs))
        shutil.copy(src, dst)
        picks["images/" + pic] = dst
data = staged_changes.load(proj) or {}
data["image"] = picks
staged_changes.save(proj, data)
print("B replaced", len(picks), "battle pictures with its own art")

with zipfile.ZipFile(os.path.join(bcase, "70th on 1.99a.zip")) as z:
    st = json.loads(z.read("pad_scene_edits.json"))["states"]
with zipfile.ZipFile(real) as zin, zipfile.ZipFile(os.path.join(out, "70th BETA 1.zip"), "w") as zo:
    for item in zin.infolist():
        blob = zin.read(item.filename)
        if item.filename == "pad_scene_edits.json":
            doc = json.loads(blob)
            doc["states"] = dict(doc.get("states") or {}, **st)
            blob = json.dumps(doc).encode("utf-8")
        zo.writestr(item, blob)
print("wrote", out)
