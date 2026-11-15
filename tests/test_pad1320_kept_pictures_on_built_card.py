"""PAD-1320 round 3 (DragonRR, "no change at all"): his 2.3 card was built with his Battle
Select file, its cards and grid pictures kept at their own size.  A Write keeps such a picture
at twice the box it shows in (PAD-1200) and fits it into that box inside the node that draws it
(PAD-865, :func:`radium_grow.keep_boxes`), so an extract of the card reads those nodes at half
the size the file's edits left them.  Loading the file again took each for a node shown smaller
and put a resize of 200 % on every one: 15 edits, the grid and cards doubled again.  Now the fit
is taken out before a node is compared with the file's edits."""
import json
import zipfile

from pinball_decryptor.plugins.stern import (
    radium_grow, scene_edit as X, scene_eval as E, scene_tree as T)
from tests.test_pad403_edits_already_on_card import _project
from tests.test_pad857_fill_keep_size import ICON, _scene

CARD = "/godzilla_le/assets/lcd/demand_loaded/def/scene.radium"
# the file as the card was built with it: the icon moved and resized
FILE = [{"op": "move", "node": 52, "dx": 20.0, "dy": 6.0},
        {"op": "scale", "node": 52, "s": 1.5, "px": 2.0, "py": 3.0},
        {"op": "move", "node": 51, "dx": 4.0, "dy": 0.0}]
# ... and after he dragged the icon on: the drag folds into its edit
DRAGGED = [dict(FILE[0], dx=30.0)] + FILE[1:]


def _stock():
    return E.manifest(T.parse(_scene()[0]))


def _card(ops, kept=(2 * ICON[0], 2 * ICON[1])):
    """The scene a Write builds with *ops*, the icon's picture kept at *kept* (twice its box):
    the picture grown, the edits applied, then the fit (as :func:`engine` orders them)."""
    data, _fill, icon = _scene()
    payload = bytes(radium_grow.image_block_len(kept[0], kept[1], 5))
    grown = radium_grow.regrow(data, images={icon: (kept[0], kept[1], payload)})["data"]
    sc = T.parse(grown)
    X.apply_scene(sc, ops)
    out, n_fit, _s, _l = radium_grow.keep_boxes(data, T.serialize(sc), [icon])
    assert n_fit == 1
    return E.manifest(T.parse(out))


def _look(man, st):
    b = X._Base.of_manifest(man)
    return {n: X._seen(b, n, st) for n in (51, 52)}


def _lands(man, ops, st):
    """Whether the scene *man* with *ops* shows each node as the file *st* leaves it."""
    got = _look(X.apply_manifest(man, ops)[0], st)
    want = {}
    for i, op in enumerate(st["ops"]):
        want[op["node"]] = st["after"][i]
    return all(X._close(got[n], want[n]) for n in want)


def test_the_card_reads_its_kept_picture_at_half_the_size():
    st = X.states_of(_stock(), FILE)
    card = _card(FILE)
    bid = X._Base.of_manifest(_stock()).pic(52)[0]
    assert st["pics"] == {str(bid): list(ICON)}
    # what went wrong: as read, the icon is half the size the file left it
    old = {k: v for k, v in st.items() if k != "pics"}
    assert X.shown_count(X._Base.of_manifest(card), FILE, old) == 0
    fix = X.rebased(card, FILE, old)
    assert any(op["op"] == "scale" and abs(op["s"] - 2.0) < 0.01 for op in fix)
    # with the fit taken out, the card shows every edit of the file
    assert X.shown_count(X._Base.of_manifest(card), FILE, st) == len(FILE)
    assert not X.starts_elsewhere(card, FILE, st)


def test_a_changed_file_gets_its_change_and_no_resize():
    st = X.states_of(_stock(), DRAGGED)
    card = _card(FILE)
    assert X.starts_elsewhere(card, DRAGGED, st)
    ops = X.rebased(card, DRAGGED, st)
    assert [op["op"] for op in ops] == ["move"] and ops[0]["node"] == 52
    assert abs(ops[0]["dx"] - 10.0) < 0.01 and abs(ops[0]["dy"]) < 0.01
    assert _lands(card, ops, st)


def test_a_resize_changed_lands_inside_the_fit():
    resized = [FILE[0], dict(FILE[1], s=1.8), FILE[2]]
    st = X.states_of(_stock(), resized)
    card = _card(FILE)
    ops = X.rebased(card, resized, st)
    assert {op["node"] for op in ops} == {52}
    assert all(op["op"] != "scale" or abs(op["s"] - 1.2) < 0.01 for op in ops)
    assert _lands(card, ops, st)


def _file(tmp_path, ops, name):
    """A file saved before states kept the pictures' sizes: its replaced picture named as the
    extract names it, its texture's size in the name."""
    st = {k: v for k, v in X.states_of(_stock(), ops).items() if k != "pics"}
    bid = X._Base.of_manifest(_stock()).pic(52)[0]
    zp = tmp_path / "battle.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr(X.SHARE_MANIFEST, json.dumps({
            "scenes": {CARD: ops}, "states": {CARD: st},
            "pictures": {"images/scene_textures/" + name: {
                "drawn": [[CARD, str(bid)]], "file": "replaced/0/a.png", "keep": True}}}))
    return str(zp)


def test_a_file_saved_before_has_the_sizes_in_its_pictures_names(tmp_path):
    zp = _file(tmp_path, DRAGGED, "radimg_Icon_%dx%d_0a1b2c3d.png" % (ICON[0] + 2, ICON[1] + 1))
    st = X.read_states(zp)[CARD]
    assert st["pics_named"] and list(st["pics"].values()) == [[ICON[0] + 2, ICON[1] + 1]]
    card = _card(FILE)
    # the name is a few pixels over the box: the scale is read off the card, so the dragged
    # icon gets a move alone, as near where a build with the file puts it as the name tells
    ops = X.rebased(card, DRAGGED, st)
    assert [op["op"] for op in ops] == ["move"]
    got = X._Base.of_manifest(X.apply_manifest(card, ops)[0]).fp(52)["m"][0]
    want = X._Base.of_manifest(_card(DRAGGED)).fp(52)["m"][0]
    assert all(abs(x - y) < 1e-3 for x, y in zip(got[:4], want[:4]))
    assert abs(got[4] - want[4]) <= 1.5 and abs(got[5] - want[5]) <= 1.5
    # named right, it lands exactly
    st = X.read_states(_file(tmp_path, DRAGGED, "radimg_Icon_%dx%d_0a1b2c3d.png" % ICON))[CARD]
    ops = X.rebased(card, DRAGGED, st)
    assert [op["op"] for op in ops] == ["move"] and _lands(card, ops, st)
    st = X.read_states(_file(tmp_path, FILE, "radimg_Icon_%dx%d_0a1b2c3d.png" % ICON))[CARD]
    assert X.shown_count(X._Base.of_manifest(card), FILE, st) == len(FILE)


def test_a_picture_the_card_shows_unfitted_is_left_as_it_is():
    # the same picture drawn as the file left it (no fit on the card): nothing to take out
    st = X.states_of(_stock(), FILE)
    built = X.apply_manifest(_stock(), FILE)[0]
    assert X.shown_count(X._Base.of_manifest(built), FILE, st) == len(FILE)
    assert X._fit_of(X._Base.of_manifest(built), 52, st, st["after"][1]) is None


def test_a_project_the_old_load_doubled_takes_the_file_again(tmp_path):
    st = X.states_of(_stock(), DRAGGED)
    card = _card(FILE)
    # the 200 % resizes the old load put on (it could not see the fit)
    doubled = X.rebased(card, DRAGGED, {k: v for k, v in st.items() if k != "pics"})
    assert any(op["op"] == "scale" and abs(op["s"] - 2.0) < 0.01 for op in doubled)
    # loading the file again: not taken as made on top of those (it replaces them) ...
    assert X.on_top_of(card, doubled, DRAGGED, st) is None
    # ... and gets the drag alone
    assert [op["op"] for op in X.rebased(card, DRAGGED, st)] == ["move"]


def test_a_project_of_the_kept_card_writes_none_of_the_files_edits_again(tmp_path):
    st = X.states_of(_stock(), FILE)
    card = _card(FILE)
    a = _project(tmp_path, {CARD: FILE}, {CARD: card})
    X.note_shown(a, {CARD: card}, states={CARD: st})
    assert X.to_apply(a, CARD, card) == []
