# Spike 3: 64-bit operator-menu rows (PAD-1321)

The operator-menu rows (MUSIC MODE, EDITION, CO-OP PLAY, HANDICAP, the picture rows) go on a
Spike 2 game by taking over a DEPRECATED adjustment: its descriptor, captions and help rewritten
in place (same size), and the menu's category table grown by one record `{category, kind, id}`,
placed in an appended program segment with the code that reads it re-pointed. On Spike 3 the game
program is 64-bit ARM (a PIE), which the reader refused.

## Done (committed): the 64-bit reader and same-size writes

`AdjustmentTable(raw, wide_ok=True)` reads the 64-bit table. A Spike 3 program's settings table is
the same shape as Spike 2's with 8-byte pointers:

- settings-section record `{live, table, count, elem, 0, node}` in 8-byte words (Star Wars ELG
  1.10 at file 0x6a0008: table 0x6b4510, 195, elem 64, "SYS").
- a 64-byte descriptor: value address @0, default/min/max/step (i32) @0x08/0x0c/0x10/0x14,
  caption ptr @0x20, row-caption line ptr @0x28, help ptr @0x30, display kind (u16) @0x38, feature
  category (u16) @0x3a. `table.fields` names the offsets, `table.ptr`/`table.wide` the width.
- the row caption is the five-language line (`char*[5]` + 0) the descriptor points at @0x28
  (Spike 2 found it by index in a big table; Spike 3 points straight at it).
- the three DEPRECATED settings are ids 31/33/35 (GI / INSERT / FLASHER LED MAX BRIGHTNESS) on the
  cards whose program still carries them (Fallout, Transformers, ELG); Pokemon, both SW 2025 and
  Walking Dead read the siblings as live and refuse, exactly as a Spike 2 program without a spare.

`menu_settings`: `wide_consts(table)` builds `{va: [file offsets]}` for every address the code
forms as `adrp xd` + `add xd,xd,#lo12` (how a PIE names a string or table). `WideCategoryTable`
is the menu's `{category, kind, id}` records, found by the address loaded into x1 before a
`movz x2, #size` copy (ELG: 111 records at 0x5b0258, size 0x534). `plan()` returns the same
same-size writes as Spike 2; `_refs` leaves out the PIE's relocation tables (DT_RELA / DT_JMPREL
ranges from PT_DYNAMIC: every relocated pointer is repeated there as an addend).

Proven on all seven Spike 3 library cards' programs (read off the card):
`tests/test_pad1321_spike3_menu_rows.py`.

## Remaining: grow the program so the row shows, and prove it in the emulator

`WideCategoryTable.writes` refuses today (`WIDE_GROW_REFUSAL`), and `offered()` returns that, so a
planned row reads back right in every field but "no menu page lists it". To finish:

1. **Place the grown category table** (N+1 records) in an appended read-only PT_LOAD, as Spike 2's
   `engine._append_extension_segment` does, but for a 64-bit PIE: reuse the PT_NOTE or PT_GNU_STACK
   advisory header, map the appended bytes at an unclaimed vaddr in the read-only/read-write gap
   (every Spike 3 program has a free page there; `readelf -l`), and keep the PT_LOAD headers in
   ascending vaddr order (a PIE's loader is stricter than ET_EXEC).
2. **Re-point the reader** (ELG, function at 0x129548): the pointer the code builds into x1 for the
   copy (the `adrp`/`add` pair at 0x1298e0/0x1298e8) to the new table's vaddr; the copy size
   `movz x2,#0x534` (0x1298ec) and the heap-alloc size `movz x0,#0x534` (0x1298f4) and the vector
   end `add x21,x0,#0x534` (0x129908) to the new byte size. NB the table is assembled lit -> stack
   buffer (`sub sp,sp,#0x540` at 0x129560, memcpy into x22=sp) -> heap: one more record is 0x540,
   which exactly fills the 0x540 stack buffer and would clobber the saved x1 at [sp,#1336]=0x538,
   so the stack frame must grow too (sub/add and the str/ldr offset). `adrp`/`add`/`movz`/`add imm`
   codecs are in `progreloc` (Spike 2) as a starting point; none assumes 32-bit.
3. **Emulator proof** (hidden, muted, a PAD-1321 rig): boot the patched ELG 1.10 program under
   s3run.sh, open Adjustments > Audio Content, read the MUSIC MODE row and its help off a frame
   capture, set it, confirm it stored (NVM mirror). The rig's s3press.py has `guided` and `sw`;
   the menu is reached from attract through the coin-door service buttons (byte 0 bits 0-3).
   This visible change is a GUI proof: before/after shots of the operator-menu page.
4. Then wire it into the Spike 3 Write (`spike3_modes` / `engine`) so a project's MUSIC MODE etc.
   land on a Spike 3 card, and lift the refusal in the family census for the menu-row parts.
