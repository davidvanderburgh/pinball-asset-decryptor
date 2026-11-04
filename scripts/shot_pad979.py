"""PAD-979 proof shot: what the Spike 1 switch / LED window is given for
Ghostbusters LE, drawn by the rig's own renderer (s1view.render_png).

    python scripts/shot_pad979.py <tools root> <wire log> <game ELF> <out.png>

Plays a node-bus log the rig wrote (start.sh S1_NB_LOG, every REQ line)
through <tools root>/tools/spike1_emu's responder exactly as nodebus.py
does - each switch read (cmd 0x11) into the block, every no-reply frame
into DmdFrames - then reads s1hw.state back the way the app does and draws
it. <tools root> is a `git archive` of main for the before shot and this
checkout for the after one; the log is the same for both.
"""
import importlib.util
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "spike1_emu"))
import s1view  # noqa: E402
from pinball_decryptor.plugins.stern.spike1_emulate import StateBlock  # noqa: E402


def _load(root, name):
    d = os.path.join(root, "tools", "spike1_emu")
    sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(name + "_shot", os.path.join(d, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.path.remove(d)
    return mod


def main():
    root, log, elf, out = sys.argv[1:5]
    nodebus, s1early = _load(root, "nodebus"), _load(root, "s1early")
    path = os.path.join(tempfile.mkdtemp(prefix="pad979-"), "s1hw.state")
    now = [0.0]
    hw = s1early.HwStateWriter(path, clock=lambda: now[0])
    dmd = nodebus.DmdFrames(hw)
    if hasattr(nodebus, "LED2_SENDER"):
        dmd.led2 = _load(root, "s1elf").has_symbol(elf, nodebus.LED2_SENDER)
    req = re.compile(r"REQ addr=0x.. node=(\d+) cmd=0x(..) (?:data=(\S+) \(no reply\)|resp_len)")
    with open(log) as f:
        for line in f:
            m = req.match(line)
            if not m:
                continue
            node = int(m.group(1))
            if m.group(3):
                dmd.frame(node, bytes.fromhex(m.group(3)))
            elif m.group(2) == "11":
                try:
                    hw.set_switches(node, [])
                except ValueError:
                    pass
    now[0] = 1e9          # the log has no times: its coil pulses are over by the end
    hw.flush(force=True)
    with open(path, "rb") as f:
        data = f.read()
    state, _, _ = StateBlock.unpack(data)
    s1view.render_png(state, out)
    lit = {}
    for slot in range(len(state.lamps) // 3):
        if any(state.lamps[slot * 3:slot * 3 + 3]):
            lit[slot // 64] = lit.get(slot // 64, 0) + 1
    print("%s: block %d bytes (format %d), lamps lit per node %s"
          % (out, len(data), StateBlock.SIZE, dict(sorted(lit.items()))))


if __name__ == "__main__":
    main()
