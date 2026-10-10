"""PAD-508 (DragonRR): "When we are in a list pane the up and down arrows act like a mouse
wheel.  Can we have them step through the list instead."  The Scenes tab's Layers and
Contents lists were plain rows nothing could focus, so the arrows fell through to the
browser and scrolled the list; every Table-based list (Images, Video, Audio, Text, the
scene list) already stepped.  Now both lists take the focus when clicked and Up / Down
pick the row above or below (Shift extends a run of layers, as Shift-click does), one
pick on its way to Python at a time.  And a Table with several rows selected went back
to its top row on an arrow; it goes on from the row last clicked or stepped to."""

import json
import os
import re
import shutil
import subprocess

import pytest

_JS = os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor",
                   "webui", "static", "js")


def _read(*parts):
    with open(os.path.join(_JS, *parts), encoding="utf-8") as f:
        return f.read()


_RUN = r"""
const { stepRow, useStepper } = await import("./tabs/text_scenes.js");
const ids = [10, 11, 12, 13];
const out = {
  down: stepRow(ids, 11, "ArrowDown"), up: stepRow(ids, 11, "ArrowUp"),
  top: stepRow(ids, 10, "ArrowUp"), bottom: stepRow(ids, 13, "ArrowDown"),
  none: stepRow(ids, null, "ArrowDown"), noneUp: stepRow(ids, null, "ArrowUp"),
  gone: stepRow(ids, 99, "ArrowDown"), other: stepRow(ids, 11, "Enter"),
  empty: stepRow([], null, "ArrowDown"),
  strings: stepRow(["img::a", "txt::1", "txt::2"], "img::a", "ArrowDown"),
};
// a held arrow: the first pick goes at once, the ones behind it wait, and only the last
// of them is sent when the first is answered
const sent = [];
let answer;
const send = (...a) => { sent.push(a); return new Promise((r) => { answer = r; }); };
const st = useStepper(send, 10);
out.idle = st.from(ids);
st.go(11, "");
out.first = sent.length;
out.at = st.from(ids);
st.go(12, ""); st.go(13, "range");
out.queued = sent.length;
out.ahead = st.from(ids);
out.notInList = st.from([1, 2]);
answer(true);
await new Promise((r) => setTimeout(r, 0));
out.after = sent.slice();
answer(true);
await new Promise((r) => setTimeout(r, 0));
st.go(12, "");
out.again = sent.length;
console.log(JSON.stringify(out));
"""

# hooks that run outside Preact: a ref is a box, an effect is skipped
_UI_HOOKS = {"useRef": "(v) => ({ current: v })", "useEffect": "() => {}"}


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_arrows_step_one_row_and_a_held_key_sends_the_last(tmp_path):
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    src = _read("tabs", "text_scenes.js")
    (tmp_path / "tabs" / "text_scenes.js").write_text(src, encoding="utf-8")
    stubs = {}
    for m in re.finditer(r"import \{([^}]*)\} from \"\.\./core/(\w+)\.js\"", src):
        stubs.setdefault(m.group(2), set()).update(
            n.strip() for n in m.group(1).split(",") if n.strip())
    for mod, names in stubs.items():
        (tmp_path / "core" / (mod + ".js")).write_text(
            "".join("export const %s = %s;\n" % (n, _UI_HOOKS.get(n, "() => null"))
                    for n in sorted(names)), encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "run.js").write_text(_RUN, encoding="utf-8")
    run = subprocess.run([shutil.which("node"), str(tmp_path / "run.js")],
                         capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert (got["down"], got["up"]) == (12, 10)
    # nothing above the top or below the bottom: the pick stays where it is
    assert got["top"] is None and got["bottom"] is None
    # nothing picked yet (or the row went away): the first row
    assert got["none"] == 10 and got["noneUp"] == 10 and got["gone"] == 10
    assert got["other"] is None and got["empty"] is None
    assert got["strings"] == "txt::1"
    # idle, the arrows go from Python's selection; once one is asked for, from that one
    assert got["idle"] == 10
    assert got["first"] == 1 and got["at"] == 11
    assert got["queued"] == 1 and got["ahead"] == 13
    # a list that no longer has the row asked for goes by Python's selection again
    assert got["notInList"] == 10
    # 12 was overtaken by 13 while 11 was on its way: 11, then 13 alone, with its Shift
    assert got["after"] == [[11, ""], [13, "range"]]
    # with both answered, the next arrow goes straight out again
    assert got["again"] == 3


def _component(src, name):
    body = src[src.index("function %s(" % name):]
    return body[:body.index("\n}\n")]


def test_layers_and_contents_take_the_focus_and_the_arrows():
    src = _read("tabs", "text_scenes.js")
    for name, send in (("TreeLayers", 'call("text_scenes.tree_select", id, how)'),
                       ("Contents", 'call("text_scenes.select_item", id)')):
        body = _component(src, name)
        # a click on a row focuses the list (the rows are not focusable), so its keys
        # reach it instead of scrolling it
        assert 'tabindex="0" onKeyDown=${onKey}' in body, name
        assert "useStepper((id" in body and send in body, name
        assert "stepRow(ids, at, e.key)" in body and "e.preventDefault()" in body, name
    layers = _component(src, "TreeLayers")
    # Shift+arrow takes in a run from the anchor, as Shift-click does
    assert 'e.shiftKey && at != null ? "range" : ""' in layers
    # a Shift-click (its mousedown is cancelled, so no text gets selected) still focuses
    assert "e.preventDefault(); listRef.current.focus({ preventScroll: true });" in layers
    contents = _component(src, "Contents")
    # an arrow's step scrolls its row into view without centring it each time
    assert 'stepped.current === s.item ? "nearest" : "center"' in contents
    # Ctrl / Alt and text boxes are left to themselves
    arrow = src[src.index("const listArrow"):]
    arrow = arrow[:arrow.index(";\n")]
    assert "!e.altKey && !e.ctrlKey && !e.metaKey" in arrow and "input, textarea, select" in arrow


def test_a_table_with_several_rows_selected_steps_from_the_last_one():
    src = _read("core", "ui.js")
    body = src[src.index("export function Table("):]
    body = body[:body.index("\n}\n")]
    assert "const atRef = useRef(null);" in body
    assert ("const from = selected instanceof Set && selected.has(atRef.current) ? atRef.current"
            " : selKey;") in body
    assert "rows.findIndex((r, i) => rowKey(r, i) === from)" in body
    # both a click and a step move it
    assert "atRef.current = rowKey(rows[idx], idx);" in body
    assert "onClick=${(e) => { atRef.current = id; if (onSelect) onSelect(r, i, e); }}" in body
