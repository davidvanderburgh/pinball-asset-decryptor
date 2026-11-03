"""Merge several vpx_play_each.py reports into one table: the LAST run of
each table counts (a retest replaces a first pass's row).

    python scripts/vpx_play_each_merge.py out.md pass1.json [pass2.json ...]
"""
import json
import sys


def main(argv):
    out = argv[0]
    rows = {}
    for path in argv[1:]:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in d.get("tables") or []:
            r["run"] = path
            rows[r["name"]] = r
    lines = ["| table | title | platform | attach s | balls | verdict | notes |", "|---|---|---|---|---|---|---|"]
    counts = {"ok": 0, "partial": 0, "FAIL": 0}
    for name in sorted(rows, key=str.lower):
        r = rows[name]
        counts[r.get("verdict") or "FAIL"] = counts.get(r.get("verdict") or "FAIL", 0) + 1
        note = "; ".join((r.get("errors") or []) + (r.get("notes") or []))
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            name.replace("|", "/"), r.get("title") or "", r.get("platform") or "",
            r.get("attached_s") if r.get("attached_s") is not None else "-", r.get("balls", 0),
            r.get("verdict") or "", note.replace("|", "/")))
    lines.append("")
    lines.append("%d tables: %d played every asked ball, %d one ball, %d failed." % (
        len(rows), counts.get("ok", 0), counts.get("partial", 0), counts.get("FAIL", 0)))
    open(out, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
