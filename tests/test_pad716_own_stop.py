"""PAD-716: game modes that run their own stop logic, taken by a mode of ours (after PAD-710).

- Jurassic Park's STOP reaches the mode's stopped byte through two of the mode's own virtuals - "stopped?" v[32]
  (mode, player) and "mark stopped" v[55] (mode, value, player) - and JP Pro's chase, Ctrl Room and T-Rex classes
  override both, keeping the byte off the framework's +0xc3 (Trex Chase +0x137, Virus Attack +0x11f). The finder
  writes `value mode_slot_stopped_get / _set`; the take clears the stopped state through the setter as the game's
  START does, so a second take's STOP is not skipped (rig: C:\\tmp\\PAD-716\\rig).
- Iron Maiden's Soul Shard Hurry Up's own stop tells the song that started it how it went and sets itself back
  (stopped 0 again): the runtime's log says so instead of reading it as nothing recorded.
"""
import os
import re

from pinball_decryptor.plugins.stern import mode_framework as MF
from pinball_decryptor.plugins.stern import portgen

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu", "modes", "sdk")


def _read(*parts):
    with open(os.path.join(SDK, *parts), encoding="utf-8") as f:
        return f.read()


#: Jurassic Park Pro 1.16's cmode STOP (0x101674), as capstone reads it: the guarded calls of v[31] / v[32] before
#: the stopped byte is read, of v[54] / v[55] before it is written
JP_STOP = """\
ldr ip, [r0]
movw r3, #0x2ae8
push {r4, r5, r6, lr}
movt r3, #0x10
ldr r5, [ip, #0x7c]
mov r4, r0
mov r6, r1
cmp r5, r3
bne #0x101794
ldr r5, [ip, #0x80]
bl #0x22c214
movw r3, #0x2a38
movt r3, #0x10
cmp r5, r3
mov r1, r0
bne #0x1017a4
bl #0x22c104
add r0, r4, r0
ldrb r0, [r0, #0xc3]
cmp r0, #0
popne {r4, r5, r6, pc}
ldr r2, [r4]
movw r3, #0x2a98
movt r3, #0x10
ldr ip, [r2, #0xd8]
cmp ip, r3
bne #0x10180c
ldr r5, [r2, #0xdc]
bl #0x22c214
movw r3, #0x2a54
movt r3, #0x10
cmp r5, r3
mov r2, r0
bne #0x10181c
bl #0x22c104
mov r3, #1
add r0, r4, r0
strb r3, [r0, #0xc3]"""

#: Iron Maiden 1.18's (0x60534): the byte itself, no virtuals
IM_STOP = """\
push {r3, r4, r5, r6, r7, lr}
mov r4, r0
mov r6, r1
bl #0x30496c
add r0, r4, r0
ldrb r5, [r0, #0x17]
cmp r5, #0
popne {r3, r4, r5, r6, r7, pc}
bl #0x30496c
mov r7, #1
add r3, r4, r0
mov r0, #0x1e
strb r7, [r3, #0x17]"""


def _ins(text):
    out = []
    for i, line in enumerate(text.splitlines()):
        m, _, o = line.partition(" ")
        out.append((0x1000 + 4 * i, m, o.strip(), 0))
    return out


def _k(ins, stopped):
    """the index of the `bl` before the stopped byte's read (stop_shape's k)"""
    i = next(n for n, x in enumerate(ins) if x[1] == "ldrb" and x[2].endswith("#0x%x]" % stopped))
    return i - 2


def test_jurassic_parks_stop_reads_and_marks_stopped_through_the_modes_own_virtuals():
    ins = _ins(JP_STOP)
    assert MF.stopped_virtuals(ins, "r4", _k(ins, 0xc3), 0xc3) == (32, 55)


def test_a_stop_that_writes_the_byte_itself_has_none():
    ins = _ins(IM_STOP)
    assert MF.stopped_virtuals(ins, "r4", _k(ins, 0x17), 0x17) == (None, None)


def test_the_lines_are_written_and_each_builds_own():
    found = MF.Found()
    found.update(mode_player=0x22c214, mode_slot_stop=24, mode_stopped_at=0xc3, mode_starts_at=0xd8,
                 mode_slot_stopped_get=32, mode_slot_stopped_set=55)
    text = "\n".join(MF.port_lines(found))
    assert "value mode_slot_stopped_get  32" in text and "value mode_slot_stopped_set  55" in text
    for line in ("value mode_slot_stopped_get 32", "value mode_slot_stopped_set 55"):
        key, rest = line.split(" ", 1)
        assert portgen.generated(key, rest), line


def test_a_port_with_pad710s_section_is_read_again_only_for_them():
    had = "value mode_slot_stop 24\nvalue mode_stopped_at 0xc3\n"
    assert MF.lines_for(b"not an elf", had) == []                       # an odd program: none, never an error
    assert MF.lines_for(b"", had + "value mode_slot_stopped_get 32\n") == []   # it has them: nothing read


def test_the_jurassic_park_ports_name_them_and_no_other_generation_does():
    ports = os.path.join(SDK, "ports")
    for name in os.listdir(ports):
        if not name.endswith(".port"):
            continue
        text = _read("ports", name)
        jp = name in ("jurassic_park_le-1.16.port", "jurassic_park_pro-1.16.port")
        assert bool(re.search(r"^value mode_slot_stopped_get\s+32\b", text, re.M)) == jp, name
        assert bool(re.search(r"^value mode_slot_stopped_set\s+55\b", text, re.M)) == jp, name


def test_the_take_clears_and_the_end_reads_stopped_through_them():
    rt = _read("pad_mode_runtime.c")
    begin = rt[rt.index("static void place_begin(unsigned obj, unsigned id, unsigned up)"):]
    begin = begin[:begin.index("\n}\n")]
    assert "place_set_stopped(obj, p, 0);" in begin
    assert "mode_stopped_at" not in begin                 # never the framework's byte directly
    end = rt[rt.index("static int place_end(unsigned p, int won)"):]
    end = end[:end.index("\n}\n")]
    assert end.index("stopped_was = place_stopped(obj, p)") < end.index("(obj, won ? 1u : 0u, 1u);") \
        < end.index("stopped_now = place_stopped(obj, p);")
    assert '" (its own stop set it back)"' in end
    for want in ('place_vfn(obj, "mode_slot_stopped_get")', 'place_vfn(obj, "mode_slot_stopped_set")',
                 "((void (*)(unsigned, unsigned, unsigned))(unsigned long)f)(obj, v, p);",
                 "((unsigned (*)(unsigned, unsigned))(unsigned long)f)(obj, p) & 0xffu"):
        assert want in rt, want
