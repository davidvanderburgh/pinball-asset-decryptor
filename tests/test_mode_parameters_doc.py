"""``tools/spike2_emu/modes/sdk/MODE_PARAMETERS.md`` names every parameter a mode has (item 141).

David asked "what are all the parameters we have access to?", and the answer is that doc.
It stays the answer only while it keeps up with the code, so this reads the code: every key
``mode_file.c``'s parser takes, every call ``pad_mode.h`` declares with its capability flags
and ``struct pm_mode`` members, and every ``ModeSpec`` field. A key, call or field added
without a row in the doc fails here, named. Desk only.
"""

import dataclasses
import pathlib
import re

from pinball_decryptor.plugins.stern import mode_project as MP

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
DOC = SDK / "MODE_PARAMETERS.md"


def _doc():
    return DOC.read_text(encoding="utf-8")


def _named(name, text):
    """The name appears in backticks - as `name`, or at the start of `name <args>` /
    `name(args)` - so a key that is a prefix of another is not found inside it."""
    return re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), text) is not None


def mode_file_keys():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    keys = set(re.findall(r'\b(?:TEXT|NUM|NUM64)\("([a-z_]+)"', src))
    keys |= set(re.findall(r'key_is\(line, "([a-z_]+)"\)', src))
    return keys


def header_calls():
    src = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return set(re.findall(r"\b(pm_[a-z_]+)\s*\(", code))


def test_the_parser_is_read_right():
    """A guard on the reader itself: the keys every mode file has used since item 126,
    and the three item 141 added, are all found."""
    keys = mode_file_keys()
    for k in ("name", "trigger", "seconds", "shots", "award", "callout_at", "sound_key",
              "clip_start", "clip_end", "clip_label", "clip_layer",
              "shot_award", "end_shot", "award_ladder"):
        assert k in keys, k
    assert len(keys) >= 29
    calls = header_calls()
    assert len(calls) >= 40 and "pm_score_add" in calls and "pm_snprintf" in calls


def test_every_mode_file_key_is_in_the_doc():
    doc = _doc()
    missing = sorted(k for k in mode_file_keys() if not _named(k, doc))
    assert not missing, "MODE_PARAMETERS.md does not name these mode-file keys: %s" % missing


def test_every_sdk_call_flag_and_callback_is_in_the_doc():
    doc = _doc()
    src = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    names = header_calls() | set(re.findall(r"#define (PM_(?:CAN|STOCK)_[A-Z_]+)", src))
    struct = re.search(r"struct pm_mode \{(.*?)\};", src, flags=re.S).group(1)
    names |= set(re.findall(r"\(\*([a-z_]+)\)\(", struct)) | {"name"}
    missing = sorted(n for n in names if not _named(n, doc))
    assert not missing, "MODE_PARAMETERS.md does not name these pad_mode.h names: %s" % missing


def test_every_mode_json_field_is_in_the_doc():
    doc = _doc()
    fields = {f.name for f in dataclasses.fields(MP.ModeSpec)} | {"format"}
    missing = sorted(f for f in fields if not _named(f, doc))
    assert not missing, "MODE_PARAMETERS.md does not name these ModeSpec fields: %s" % missing


def _calls_heading(doc):
    """The call table's lead-in, "The N calls.", whose N must be how many pad_mode.h declares
    (item 140's two stock-mode calls made it 42)."""
    m = re.search(r"The (\d+) calls\.", doc)
    assert m, "MODE_PARAMETERS.md has no 'The N calls.' line before the call table"
    assert int(m.group(1)) == len(header_calls()), \
        "the doc says %s calls; pad_mode.h declares %d" % (m.group(1), len(header_calls()))
    return m.group(0)


def _table_names(doc, heading):
    """The backticked names in the first cell of every row of the first table after
    ``heading`` (``pm_can(what)`` gives ``pm_can``)."""
    section = doc.split(heading, 1)[1]
    names, rows = set(), 0
    for line in section.splitlines():
        if line.startswith("|"):
            rows += 1
            if rows > 2:
                first = line.split("|")[1]
                names |= {re.split(r"[ (]", n, maxsplit=1)[0] for n in re.findall(r"`([^`]+)`", first)}
        elif rows:
            break
    return names


def test_a_key_or_field_that_landed_has_its_own_row():
    """Naming a key in prose is not enough: a key the parser takes has a row in the key
    table, a ModeSpec field a row in the mode.json table, a call a row in the call table.
    And a key another item RESERVED leaves the reserved table the day it lands (item 139's
    `starts` and `cooldown` were the first), so that table never lies about the runtime."""
    doc = _doc()
    keys, fields = mode_file_keys(), {f.name for f in dataclasses.fields(MP.ModeSpec)} | {"format"}
    missing = sorted(keys - _table_names(doc, "### The keys"))
    assert not missing, "no row in MODE_PARAMETERS.md's key table for: %s" % missing
    missing = sorted(fields - _table_names(doc, "## 2. `mode.json`"))
    assert not missing, "no row in MODE_PARAMETERS.md's mode.json table for: %s" % missing
    missing = sorted(header_calls() - _table_names(doc, _calls_heading(doc)))
    assert not missing, "no row in MODE_PARAMETERS.md's call table for: %s" % missing
    landed = sorted(_table_names(doc, "## 5. Keys other items reserve") & (keys | fields))
    assert not landed, "these reserved keys are in the code now - move them to sections 1-2: %s" % landed


def test_every_row_says_where_it_is_measured():
    """The key and call tables carry a Measured column, and no row leaves it empty."""
    doc = _doc()
    for heading in ("### The keys", _calls_heading(doc)):
        section = doc.split(heading, 1)[1]
        rows = []
        for line in section.splitlines():
            if line.startswith("|"):
                rows.append(line)
            elif rows:
                break
        header, body = rows[0], rows[2:]
        assert header.rstrip(" |").endswith("Measured"), heading
        for row in body:
            last = row.rstrip().rstrip("|").rsplit("|", 1)[1].strip()
            assert last, "no Measured entry: %s" % row
