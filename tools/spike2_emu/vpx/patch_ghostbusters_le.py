#!/usr/bin/env python3
"""Fit ninuzzu/tom tower/djrobx's original-layout Ghostbusters LE 1.2 to PAD.

    python patch_ghostbusters_le.py "<Ghostbusters LE 1.2.vpx>" <output dir>

The author's table, physics and mechanisms stay intact. Replace its SPA
controller, map its existing legacy numbers, bound its lamp-array reads and
keep mechanical audio while the emulator supplies the machine soundtrack.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vpxfile  # noqa: E402
import vpxsounds  # noqa: E402

MAP = os.path.join(HERE, "ghostbusters_le_replica.vpxmap.json")


def patch_script(src, m):
    src = src.replace("\r\n", "\n").replace("\r", "\n")
    report = []

    def replace(old, new):
        nonlocal src
        if src.count(old) != 1:
            raise ValueError("not the Ghostbusters LE 1.2 script: expected one %r" % old)
        src = src.replace(old, new, 1)

    replace('Const cGameName = "spagb_100"', 'Const cGameName = "%s"' % m["title"])
    replace('Const B2ScGameName = "spagb_100b2s"',
            'Const B2ScGameName = "%s"' % m.get("b2s_name", "spagb_100b2s"))
    replace('Dim UseVPMDMD:UseVPMDMD = DesktopMode', 'Dim UseVPMDMD:UseVPMDMD = False')
    loader = '''Sub LoadSPAController()
    Set Controller = CreateObject("PAD.Controller")
    B2SOn = False : B2SOnALT = False
    On Error Resume Next
    Set B2SController = CreateObject("B2S.Server")
    B2SController.B2SName = B2ScGameName
    B2SController.Run
    B2SOnALT = (Err.Number = 0)
    Err.Clear
    On Error Goto 0
End Sub'''
    src, n = re.subn(r"(?ms)^Sub LoadSPAController\(\).*?^End Sub", lambda _: loader, src)
    if n != 1:
        raise ValueError("not the Ghostbusters LE 1.2 controller loader")
    for old, new in ((0, 9011), (-1, 9010), (-2, 9009), (-3, 9008)):
        src = re.sub(r"(?i)Controller\.Switch\(\s*%d\s*\)" % old,
                     "Controller.Switch(%d)" % new, src)
    replace('Sub Table1_Exit:Controller.Stop:End Sub',
            'Sub Table1_Exit:Controller.Stop:On Error Resume Next:B2SController.Stop:End Sub')
    replace('For ii = 0 To UBound(chgLamp)',
            'For ii = 0 To UBound(chgLamp)\n'
            '            If chgLamp(ii, 0) >= 0 And chgLamp(ii, 0) <= 300 Then')
    replace('        Next\n        if vid then', '            End If\n        Next\n        if vid then')
    report.append("SPA replaced by PAD.Controller; B2S stays optional and closes with the table")
    report.append("CPU service buttons use 9008..9011; ChangedLamps stays inside the legacy 0..300 arrays")
    return src, report


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    map_path = MAP
    if "--map" in args:
        at = args.index("--map")
        if at + 1 >= len(args):
            raise SystemExit("--map needs a map file")
        map_path = args.pop(at + 1)
        args.pop(at)
    if not 1 <= len(args) <= 2:
        raise SystemExit(__doc__)
    source = os.path.abspath(args[0])
    outdir = os.path.abspath(args[1]) if len(args) == 2 else os.path.dirname(source)
    with open(map_path, encoding="utf-8") as f:
        m = json.load(f)
    table = vpxfile.VpxTable(source)
    try:
        script, report = patch_script(table.script(), m)
        script, streams = vpxsounds.quiet(script, table.ole, report)
    finally:
        table.ole.close()
    os.makedirs(outdir, exist_ok=True)
    output = os.path.join(outdir, m["output"])
    vpxfile.write_patched(source, output, script=script, streams=streams)
    sidecar = os.path.splitext(output)[0] + ".script.vbs"
    with open(sidecar, "w", encoding="utf-8", newline="\n") as f:
        f.write(script)
    print("\n".join(report))
    print("wrote " + output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
