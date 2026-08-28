"""Editable display strings inside the Spike 2 game program (the ARM ELF).

Not every string the machine shows lives in a ``.radium`` scene.  Mode titles,
battle names, award lines and status text are C strings in the game binary's
data segments, composed at runtime by game code — the scene's own Text node is
just a placeholder the code overwrites.  Godzilla's battle intro is the proving
case: the tester edited every radium occurrence of EBIRAH and the machine kept
showing EBIRAH, because the intro title is drawn from the ELF's string table.

Two structures matter (validated on Godzilla 1.15 Pro):

* **String spans** — plain NUL-terminated ASCII in the PT_LOAD file ranges.
  Patched IN PLACE like radium text: replacement must fit the original's byte
  length and is NUL-padded (a C string ends at the first NUL, so unlike the
  radium patch there is no visible space padding).

* **Name groups with interior pointers** — the UI references strings through
  groups of five identical ``char*`` (one per UI language, all pointing at the
  same English text; the same shape :mod:`.spike2.sfx_names` mines).  Some
  groups point INTO a longer string: Godzilla shows the bare battle name via
  ``"GODZILLA VS EBIRAH" + 12`` — ``"GODZILLA VS "`` is exactly 12 bytes, so
  there is no standalone ``EBIRAH`` string at all.  Those tails are surfaced
  as their own editable rows, and the Write plan repoints the group pointers
  so the tail can move inside the (possibly shorter) replacement title:
  editing the title to ``"GZ VS BIOLLANTE"`` with the name row set to
  ``"BIOLLANTE"`` lands the pointers on ``+6``.  A tail row's byte budget is
  therefore its HOST string's length, not its own.

Only words that sit inside a run of >= 5 identical dwords are ever treated as
(or patched as) name-group pointers — a lone data word that happens to equal a
string's address is left alone, so a false positive cannot corrupt code or
data.  Everything here is best-effort: an ELF that doesn't parse yields no
rows, and any edit that can't be resolved safely is skipped with a warning
rather than partially applied.
"""

import re
import struct

from .radium import _has_letter, _is_identifier_like

# Longest string offered for editing.  Longer runs are EULA / service-menu
# paragraphs and engine diagnostics — not the display text a modder retitles.
MAX_EDIT_LEN = 96
# Spans shorter than this with no spaces are too ambiguous to expose (raw
# tokens, file stems, enum words).
MIN_BARE_LEN = 4

# NUL-terminated printable-ASCII runs (preceded by a NUL, i.e. string starts).
# Newlines are real content: multi-line titles exist ("GODZILLA, MOTHRA, AND
# RODAN\nVS.\nKING GHIDORAH" is the battle-select card, and its KING GHIDORAH
# tail is what the name-group pointers reference).
_SPAN_RE = re.compile(rb"(?<=\x00)[\x20-\x7e\n]{2,%d}(?=\x00)" % (MAX_EDIT_LEN,))
_HEX_RE = re.compile(r"^[0-9a-fA-F]{16,}$")


def encode_text(s):
    r"""Manifest form of a program string: real newlines become the two-char
    sequence ``\n`` so the string stays on one TSV line and can be typed in a
    single-line entry.  Program strings never contain a literal backslash
    (:func:`is_display_string` rejects them), so the escape is unambiguous."""
    return s.replace("\n", "\\n")


def decode_text(s):
    r"""Inverse of :func:`encode_text` (``\n`` -> newline)."""
    return s.replace("\\n", "\n")


def _fmt_tokens(s):
    """The '%'-token fingerprint of *s* — the characters following each '%'
    (``$`` for a trailing one).  A replacement must keep this identical so a
    printf-style consumer keeps its arguments lined up."""
    return tuple(re.findall(r"%(.|$)", s))


def is_display_string(s):
    """Would a modder recognise *s* as player-facing text?  Deliberately
    permissive (search narrows the list in the GUI); the hard exclusions are
    strings whose EDIT could break a lookup rather than a label:

      * identifier-shaped bare tokens (snake_case / dotted / CamelCase)
      * ``SE ``-prefixed sound-event names (the firmware finds sounds by them)
      * path / hash / option-flag shapes
    """
    if not _has_letter(s):
        return False
    if len(s.strip()) < 2:
        return False
    if "_" in s or "/" in s or "\\" in s:
        return False
    if s.startswith(("SE ", "-", "--")):
        return False
    has_space = " " in s or "\n" in s
    if not has_space:
        if len(s) < MIN_BARE_LEN:
            return False
        if _is_identifier_like(s):
            return False
        if _HEX_RE.match(s):
            return False
    return True


def _load_ranges(raw):
    """``[(file_lo, file_hi)]`` of the PT_LOAD segments, or ``None`` when the
    ELF doesn't parse (callers then yield nothing)."""
    try:
        from .spike2.elf import parse_elf
        segs, _relocs = parse_elf(raw)
    except Exception:
        return None
    out = [(o, o + fs) for (_v, o, fs, _m) in segs if fs > 0]
    return sorted(out) or None


def _seg_funcs(raw):
    """(off2va, va2off) closures over the PT_LOAD segments."""
    from .spike2.elf import parse_elf
    from .spike2.sfx_names import _seg_maps
    segs, _relocs = parse_elf(raw)
    return _seg_maps(segs)


def _display_spans(raw, ranges):
    """Every display-candidate string span: ``[(file_off, text)]``, file order.
    *ranges* is the sorted PT_LOAD list from :func:`_load_ranges`."""
    out = []
    for m in _SPAN_RE.finditer(raw):
        off = m.start()
        if not any(lo <= off < hi for lo, hi in ranges):
            continue
        s = m.group().decode("latin1")
        if is_display_string(s):
            out.append((off, s))
    return out


def _group_pointer_words(raw):
    """Word offsets that are members of a run of >= 5 identical non-zero
    dwords (the five-language name-group shape), as ``{word_off: value}``."""
    import numpy as np
    n = len(raw) // 4
    if n < 5:
        return {}
    a = np.frombuffer(raw[: n * 4], dtype="<u4")
    same = np.concatenate(([False], a[1:] == a[:-1]))
    # run id per position, then run lengths
    run_id = np.cumsum(~same)
    counts = np.bincount(run_id)
    member = (counts[run_id] >= 5) & (a != 0)
    idx = np.flatnonzero(member)
    return {int(i) * 4: int(a[i]) for i in idx}


def _tail_map(raw, spans):
    """``{host_off: [(delta, tail_text, [ptr_word_offsets])]}`` for every
    display span that a name-group points INTO (delta > 0)."""
    try:
        off2va, va2off = _seg_funcs(raw)
    except Exception:
        return {}
    ptr_words = _group_pointer_words(raw)
    if not ptr_words:
        return {}
    import bisect
    starts = [o for o, _s in spans]
    by_target = {}                      # target file_off -> [word_off]
    for woff, val in ptr_words.items():
        fo = va2off(val)
        if fo is not None:
            by_target.setdefault(fo, []).append(woff)
    tails = {}
    for tgt, woffs in by_target.items():
        i = bisect.bisect_right(starts, tgt) - 1
        if i < 0:
            continue
        host_off, host_text = spans[i]
        delta = tgt - host_off
        if delta <= 0 or delta >= len(host_text):
            continue
        tails.setdefault(host_off, []).append(
            (delta, host_text[delta:], sorted(woffs)))
    for v in tails.values():
        v.sort()
    return tails


def enumerate_program_strings(raw):
    """The editable program-text rows for the manifest:
    ``[{"text", "budget", "tail_of"}]`` in file order, deduped by text.

    ``budget`` is the byte length a replacement must fit (a tail row's budget
    is its host's length — the tail can move within the host).  ``tail_of``
    names the host text for tail rows, ``None`` for plain strings.  ``text`` /
    ``tail_of`` are in manifest form (:func:`encode_text`); ``budget`` counts
    the raw on-card bytes."""
    ranges = _load_ranges(raw)
    if not ranges:
        return []
    spans = _display_spans(raw, ranges)
    tails = _tail_map(raw, spans)
    by_off = dict(spans)
    rows = []
    seen = {}
    for off, text in spans:
        if text not in seen:
            seen[text] = {"text": encode_text(text), "budget": len(text),
                          "tail_of": None}
            rows.append(seen[text])
    for host_off, tinfos in sorted(tails.items()):
        host_text = by_off.get(host_off)
        for _delta, ttext, _ptrs in tinfos:
            if not is_display_string(ttext):
                continue        # '.'-style fragment: not worth a row of its own
            r = seen.get(ttext)
            if r is None:
                r = {"text": encode_text(ttext), "budget": len(host_text),
                     "tail_of": encode_text(host_text)}
                seen[ttext] = r
                rows.append(r)
            elif r["tail_of"] is None:
                # Also exists standalone: keep the standalone budget (an edit
                # patches both forms; the smaller budget is the safe one).
                pass
    return rows


def _settings_captions(table, mode, buf):
    """``{adjustment_id: caption text}`` read through *buf* (the ELF bytes,
    possibly with pending writes applied) at the descriptor offsets *table*
    found in the pristine bytes.

    Mirrors :func:`adjustments._caption_at` / :func:`adjustments.menu_label`,
    but takes the bytes to read TEXT from as a parameter so a planned edit
    shows the caption it would leave on the card.  The descriptor and pointer
    layout always comes from the pristine *table* — a text edit never moves a
    descriptor — except the five-language indirection word, which IS a name
    group and can be repointed by the very writes being checked, so it is
    re-read from *buf*."""
    from .adjustments import OFF_MENU_LABEL, _is_caption

    def cstr(va):
        o = table._off(va)
        if o is None:
            return None
        e = buf.find(b"\x00", o, o + 96)
        if e < 0:
            return None
        try:
            s = bytes(buf[o:e]).decode("latin1")
        except Exception:
            return None
        return s if s.isprintable() else None

    out = {}
    for idx in range(table.count):
        doff = table._off(table.table_va + idx * table.elem)
        if doff is None or OFF_MENU_LABEL + 4 > table.elem:
            continue
        va = struct.unpack_from("<I", buf, doff + OFF_MENU_LABEL)[0]
        if not va:
            continue
        direct = cstr(va)
        indirect = None
        inner = table._off(va)
        if inner is not None and inner + 4 <= len(buf):
            w = struct.unpack_from("<I", buf, inner)[0]
            if w:
                indirect = cstr(w)
        order = (indirect, direct) if mode == "indirect" else (direct, indirect)
        for c in order:
            if _is_caption(c):
                out[idx] = c
                break
    return out


def _drop_caption_collisions(captions, edits, log):
    """Remove every edit that would leave two operator settings with the SAME
    caption, and say why.  Returns the pruned copy of *edits*.

    The firmware hashes each adjustment's menu caption when it builds its
    settings store; two captions with the same text is ``** FATAL: error 249
    (NVMigration: ADJUSTMENT hash is NOT UNIQUE)`` at every boot — on a
    machine an endless flash between the loading screen and "initializing"
    (Godzilla 1.16 Heisei retheme, 2026-08-26: two champ-score captions were
    renamed to the same text and the write boot-looped real hardware).
    Display-string duplicates stay allowed — that same mod merges three award
    lines into one on purpose, and a card fixed ONLY in its captions boots —
    so this prunes nothing outside the settings captions, and tolerates
    whatever caption sharing the stock build itself carries (its boot is the
    proof the firmware accepts it).

    When two EDITS claim one name, the first setting in the operator menu's
    own order keeps it and the rest are skipped."""
    new = {idx: edits.get(text, text) for idx, text in captions.items()}
    groups = {}
    for idx in sorted(new):
        groups.setdefault(new[idx], []).append(idx)
    pruned = dict(edits)
    for txt, idxs in groups.items():
        if len(idxs) < 2 or len({captions[i] for i in idxs}) < 2:
            continue
        unedited = [i for i in idxs if captions[i] == txt]
        keep = unedited or [idxs[0]]
        for i in idxs:
            orig = captions[i]
            if i in keep or orig == txt or orig not in pruned:
                continue
            if unedited:
                why = ('another operator setting is already named "%s"'
                       % encode_text(txt))
            else:
                why = ('the edit renaming "%s" already takes that name'
                       % encode_text(captions[keep[0]]))
            log('Program text: "%s" -> "%s" is skipped: %s, and a machine '
                "with two identically-named settings REFUSES TO BOOT (it "
                "flashes between the loading screen and initializing "
                "forever). Pick a name no other setting uses."
                % (encode_text(orig), encode_text(txt), why), "warning")
            del pruned[orig]
    return pruned


def _new_caption_collisions(captions, final):
    """Caption texts that *final* (post-edit) duplicates across settings whose
    pristine captions in *captions* were distinct.  Settings that already
    shared one caption (or one caption string) in the pristine build stay
    exempt — see :func:`_drop_caption_collisions`."""
    groups = {}
    for idx, txt in final.items():
        if idx in captions:
            groups.setdefault(txt, []).append(idx)
    return sorted(txt for txt, idxs in groups.items()
                  if len(idxs) > 1 and len({captions[i] for i in idxs}) > 1)


def plan_writes(raw, edits, log=None):
    """Resolve *edits* (``{original: replacement}``) against the ELF *raw*
    and return ``(writes, n_applied)`` where *writes* is a flat
    ``[(file_offset, bytes)]`` patch list.

    Rules per host span (see the module docstring):

      * plain span, edit fits -> in-place overwrite, NUL-padded.
      * span with pointer tails: the (possibly edited) tail text must be a
        suffix of the (possibly edited) full text; the group pointers move to
        the suffix position.  A tail-only edit rewrites the host as
        ``prefix + new_tail`` when that fits.
      * any conflict (too long, tail not a suffix, '%'-tokens changed) skips
        the whole span with a warning — never a partial patch.
      * an edit that would leave two operator settings with the same caption
        is skipped (:func:`_drop_caption_collisions` — the machine refuses to
        boot such a card), and if a collision still arrives sideways (e.g. a
        standalone-name rename inside a caption) the WHOLE plan is withheld
        rather than shipped.
    """
    log = log or (lambda *a, **k: None)
    ranges = _load_ranges(raw)
    if not ranges:
        log("Program text: the game binary didn't parse as an ELF; "
            "no program strings patched.", "warning")
        return [], 0
    # Manifest rows arrive in encoded form (\n escapes); resolve raw-vs-raw.
    edits = {decode_text(k): decode_text(v) for k, v in edits.items()}
    # The settings-caption census, for the duplicate-name boot guard.  Builds
    # that don't parse (no AD_ table) simply aren't checked — same best-effort
    # stance as the rest of this module.
    table = mode = None
    captions = {}
    if edits:
        try:
            from .adjustments import AdjustmentTable, _caption_mode
            table = AdjustmentTable(raw)
            mode = _caption_mode(table)
            captions = _settings_captions(table, mode, raw)
        except Exception:
            captions = {}
    if captions:
        edits = _drop_caption_collisions(captions, edits, log)
    spans = _display_spans(raw, ranges)
    tails = _tail_map(raw, spans)
    try:
        off2va, _va2off = _seg_funcs(raw)
    except Exception:
        return [], 0

    applied = set()
    writes = []

    enc = encode_text                        # newline-safe form for the log

    def _fmt_ok(old, new, where):
        if _fmt_tokens(old) == _fmt_tokens(new):
            return True
        log('Program text: "%s" -> "%s" changes the %%-placeholders; skipped '
            "(%s). Keep every %% token from the original."
            % (enc(old), enc(new), where), "warning")
        return False

    for off, text in spans:
        full_new = edits.get(text)
        tinfos = tails.get(off, [])
        tail_edits = [(d, tt, ptrs, edits.get(tt)) for (d, tt, ptrs) in tinfos]
        if full_new is None and not any(tn is not None
                                        for (_d, _t, _p, tn) in tail_edits):
            continue
        budget = len(text)

        new_full = full_new
        if new_full is None:
            # tail-only edit: rebuild the host around the renamed tail
            edited = [(d, tt, ptrs, tn) for (d, tt, ptrs, tn) in tail_edits
                      if tn is not None]
            if len(edited) > 1:
                log('Program text: "%s" has several standalone-name pointers '
                    "with conflicting edits; skipped." % enc(text), "warning")
                continue
            d, tt, _ptrs, tn = edited[0]
            new_full = text[:d] + tn
            if len(new_full) > budget:
                log('Program text: renaming "%s" to "%s" makes "%s" %d bytes '
                    "but only %d fit. Edit the full line too (any text ending "
                    'in "%s", e.g. shorten the part before the name).'
                    % (enc(tt), enc(tn), enc(new_full), len(new_full),
                       budget, enc(tn)), "warning")
                continue
        if len(new_full) > budget:
            log('Program text: "%s" -> "%s" is %d bytes but the original is '
                "only %d; skipped. Use a shorter replacement."
                % (enc(text), enc(new_full), len(new_full), budget),
                "warning")
            continue
        if not _fmt_ok(text, new_full, "full line"):
            continue

        # Every pointer tail must land on a suffix of the new text.
        ptr_moves = []
        ok = True
        for d, tt, ptrs, tn in tail_edits:
            want = tn if tn is not None else tt
            if tn is not None and not _fmt_ok(tt, tn, "standalone name"):
                ok = False
                break
            if not new_full.endswith(want):
                log('Program text: "%s" is also shown on its own (the machine '
                    'points %d bytes into the line). The new line "%s" must '
                    'END with the new name "%s" — edit one of the two so it '
                    "does; skipped."
                    % (enc(text), d, enc(new_full), enc(want)), "warning")
                ok = False
                break
            new_delta = len(new_full) - len(want)
            if new_delta != d:
                va = off2va(off)
                if va is None:
                    ok = False
                    break
                old_ptr = struct.pack("<I", va + d)
                new_ptr = struct.pack("<I", va + new_delta)
                for w in ptrs:
                    if raw[w:w + 4] == old_ptr:
                        ptr_moves.append((w, new_ptr))
        if not ok:
            continue

        if new_full != text:
            writes.append((off, new_full.encode("latin1", "replace")
                           .ljust(budget, b"\x00")))
        writes.extend(ptr_moves)
        applied.add(text if full_new is not None else None)
        for d, tt, _p, tn in tail_edits:
            if tn is not None:
                applied.add(tt)
        if new_full != text:
            log('Program text: "%s" -> "%s"%s.'
                % (enc(text), enc(new_full),
                   " (standalone-name pointer moved)" if ptr_moves else ""),
                "info")

    applied.discard(None)
    for original in edits:
        if original not in applied:
            log('Program text: "%s" wasn\'t found in the game program; '
                "skipped." % original, "warning")

    # Backstop for the caption guard: a collision can arrive SIDEWAYS — a
    # standalone-name (tail) rename rewrites its host string, and when that
    # host is a settings caption the pre-plan check above never saw the
    # caption's text in the edit keys.  Re-read every caption through the
    # planned writes; if two settings would end up sharing a name, withhold
    # the whole plan rather than ship a card the machine refuses to boot.
    if writes and captions:
        buf = bytearray(raw)
        for off, b in writes:
            buf[off:off + len(b)] = b
        clashes = _new_caption_collisions(
            captions, _settings_captions(table, mode, buf))
        if clashes:
            log("Program text: these edits would leave two operator settings "
                'named "%s", and a machine with two identically-named '
                "settings REFUSES TO BOOT (it flashes between the loading "
                "screen and initializing forever). The collision comes from "
                "a standalone-name rename inside a setting caption, so NO "
                "program-text edit was applied. Rename one of the colliding "
                "settings and Write again." % encode_text(clashes[0]),
                "warning")
            return [], 0
    return writes, len(applied)
