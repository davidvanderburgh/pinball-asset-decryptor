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

## The grow mechanism, proven on ELG (2026-11-15)

The exact transformation above was carried out by hand on Star Wars ELG 1.10 and PROVEN, as the
spike that de-risks the generic code. For a +1 record (111 -> 112, size 0x534 -> 0x540):

- the 112-record table is appended page-aligned at EOF and mapped by repurposing PT_GNU_STACK as a
  read-only PT_LOAD at vaddr 0x7c7000 (just above .bss, so last in vaddr order; p_offset/p_vaddr
  page-congruent). A PIE adds the same load base to every segment, and the copy is reached by a
  PC-relative `adrp`/`add`, so an absolute p_vaddr is correct at runtime.
- nine instruction words patched: `adrp x1`/`add x1` -> 0x7c7000; `movz x2`/`movz x0` -> 0x540;
  `add x21,x0` -> 0x540; and the frame grown `sub sp`/`add sp` 0x540 -> 0x550 with the saved-arg
  `str`/`ldr [sp,#1336]` -> `[sp,#1352]` (so the longer copy doesn't clobber the saved register).

Proven three static ways: our own reader parses the 112-record table at 0x7c7000 and reports the
menu now lists id 31 as `{11,3,31}`; `aarch64-linux-gnu-objdump` confirms all nine patches; the
descriptor reads back MUSIC MODE / row Music Mode / range 1-2.

Proven on the machine: the patched program boots on the Spike 3 rig and runs at 55 fps through
GAME SETUP, attract and the coin-door screen with NO crash (frames in
work/artifacts/PAD-1321/). Reaching attract means the start-up constructor's copy OUT of the new
segment succeeded (else a boot-time fault), so the segment, the repointed copy and the resized
frame all work live. The operator-menu page itself was not captured: opening the coin door (needed
to reach Adjustments) hangs this title's service/connect path in the emulator under heavy rig load
(load 16+, other sessions), and the harness SIGKILLs the hung game (137, never a SIGSEGV). A
calmer rig should let the menu page be captured.

## Shipped: the generic grow (menu_settings.grow_wide_program)

The spike above is now shipping code. `wide_copy_sites(table, cat)` reads the copy site, the three
size constants, the stack-buffer frame and - the hazard the spike exposed - the stack canary at the
buffer top (`[sp, #F-8]`, written at the prologue and re-checked on the normal return AND the
exception landing pad). `grow_wide_program(table, cat, *settings)` appends the grown table in a
read-only segment, re-points the copy, raises the sizes, and grows the frame so the longer copy
clears the canary, moving every canary access together. A build whose menu-copy does not match this
compiler's pattern, or that keeps any other local in the bytes the longer copy would cover, is
refused with a sentence (`offered()` returns it) rather than mis-patched.

Proven on all three row-taking builds (Star Wars ELG 1.10, Fallout 0.82, Transformers 0.96): the
grown program re-reads with the row listed, `check()` clean (descriptor, captions, help AND the
menu page), the canary's str and both ldr checks shift as one, the disassembly is self-consistent.
The patched ELG program boots and runs to attract on the rig at 55 fps with no crash.
`tests/test_pad1321_spike3_menu_rows.py`.

## For the consumers (the menu-based family tickets)

PAD-1321 delivers the capability; PAD-1324 (music modes), PAD-1325 (editions), PAD-1326 (co-op /
handicaps) USE it. When they do:

- **pick the category per game, by name.** (PAD-1324: `menu_settings.wide_category_names` / `wide_category` read
  the page table, and `plan()` uses it for every 64-bit row: MUSIC MODE -> Audio Content 13, EDITION -> Attract Mode 16
  on all three row-taking builds. An empty page shows once a row is listed on it: proven for Audio Content on ELG.) `grow_wide_program` places the row on the category it is
  given; `SETTINGS` carries the Spike 2 numbers (13 = Audio Content, ...), but a Spike 3 build's
  category numbers differ (on ELG, 13 is unused and 11/16/... are its own pages). Resolve each
  setting's page from the game's category-NAME table, or place the row on an existing populated
  category, so it lands on a real, navigable page. A record on an unused category number is listed
  but may show on no page.
- **wire it into the Spike 3 Write** (`spike3_modes` / `engine`) so the row lands on the card.
- **capture the visible row in the emulator per build.** On 2026-11-15 the ELG operator-menu page
  could not be shot: reaching Adjustments needs the coin door open, and ELG's door-open service /
  connect path hangs the emulator under heavy concurrent rig load (SIGKILL, never a program fault;
  work/artifacts/PAD-1321). A calmer rig should let it be captured; whether the hang is purely load
  or inherent to ELG's Insider connect under emulation is still open.

## PAD-1325: the first consumer (EDITION)

- The page is found per game by its name (`menu_settings.wide_category`, PAD-1324): EDITION on
  Attract Mode (16 on ELG, Fallout, Transformers), MUSIC MODE on Audio Content.
- With music modes on the card, their grown copy (`game.pad`, run by the modes' hook) carries
  EDITION too: `spike3_music.menu_program` grows the project's `spike3_menu.rows_wanted` beside
  MUSIC MODE in the same pass.
- The Write step is `plugins/stern/spike3_menu.py`: `grow(raw, wanted)` takes the
  `plan_many` list, so the other rows join EDITION's one grow (one category table for them all).
- The visible row: on 2026-11-16 the rig (load under 1) reached Adjustments > Machine Settings >
  Attract Mode without a hang, but no setting page opens on SELECT, on the stock ELG card too
  (control run): an emulator gap, not the grow. The row is checked from the program instead.
  PAD-1360 found it: the rig's autoguide took every settings page for Guided Setup and pressed BACK
  ~2 s after it opened. Fixed (it knows Guided Setup by its title now): on the rig the setting pages
  open, stay, and a value set there is saved, so a grown row can be shown and set in the emulator.
  Shown on PAD-1325's editions card: the Edition row on Attract Mode, set to 2 in the menu, saved,
  and the next boot chose edition 2 (DARK SIDE).
