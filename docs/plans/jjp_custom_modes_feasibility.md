# Custom modes on JJP games — feasibility (PAD-586)

> **Question:** can we add custom game modes to Jersey Jack (JJP) titles the way
> we did for Stern Spike 2? **Answer: not in the near term, and not as the same
> kind of feature.** The reverse-engineering that modes need has not been done
> for JJP, and the one technique that made Spike 2 modes work — preload a small
> library and hook the game's own code — **does not port to JJP's dongle-encrypted
> binary**. There is a single conceivable route (de-envelope the binary to a
> key-free copy first), but it rests on an unproven draft tool and carries a much
> bigger IP exposure than anything we ship today. This file records why, so the
> question does not have to be re-litigated from scratch.

This is a desk study. Nothing was changed in the game code of any JJP title, and
no claim here is of a mode running on JJP — that is exactly the thing that does
not exist. Everything below is cross-checked against the repo as it stands on
`ticket/PAD-586` (2026-10-15).

## What "modes like Spike 2" actually requires

The Spike 2 modes feature (≈140 PAD tickets, ≈100k lines across
`plugins/stern` + `tools/spike2_emu/modes`) stands on four pillars. To add modes
to JJP you need all four again, for JJP:

1. **A map of the game's rules.** On Spike 2 that is `MODE_API.md` (1,512 lines),
   the RTTI-derived class models (`cmode_manager`, `crule_manager`), and **70
   per-build "ports"** in `sdk/ports/` — one file per title/version listing each
   hooked function's address and its first two instructions, plus the globals,
   shots, lamps, events and callouts. This is the bulk of the effort.
2. **A way to get our code running inside the game.** On Spike 2: the card's
   `/etc/init.d/game_monitor` is edited to **preload `mode.so`** into the game
   process, and `mode.so` installs **in-memory prologue trampolines**
   (`pad_mode_runtime.c`, 10,107 lines) over the game's own functions.
3. **The game's own output APIs to call** — score, lights, display/text, clips,
   sounds, coils — reached through those hooks (`pad_mode.h`, 686 lines).
4. **An emulator rig to prove it** without the physical machine
   (`tools/spike2_emu`, qemu-user + `hwshim.c`, `rigbatch.sh`).

JJP has **pillar 4 and nothing else.** Pillars 1–3 are empty, and pillar 2's
technique is actively blocked by how JJP ships.

## What JJP already has (and it is a lot)

- **A working emulator rig.** `tools/jjp_emu/` (~12k lines) boots the real
  x86-64 game natively under WSL: overlay jail (`jail.sh`), dongle pass-through
  (`dongle.sh` — the key is the AES key for the code, not just a check),
  Xephyr display, and a hardware shim (`jjphwshim.c` + CUSE `jjpcuse.c`) that
  presents real `/dev/jjp*` nodes. Wonka v03.03 boots to attract and a commit
  (`f0e741de`, 2026-08-20) reports a game starting and playing (serve, plunge,
  drain); switches/lamps/coils are live over shared memory. This is a genuine
  asset.
- **Symbol recovery.** `jjpelf.py` rebuilds the dynamic symbol table from
  `PT_DYNAMIC` even though section headers are stripped; ~6,456 plaintext C++
  `_Z` names survive (`Switch::realtime`, `Lamp::get_x`, …) and several device
  tables are statically named (`switch_table`, `hook_lamp_table`,
  `hook_coil_override_table`). So we can *name* functions — we cannot yet *read*
  most of them (see below).
- **Asset modding end to end.** Extract/Write already decrypt and re-encrypt
  images, sounds, video and text (CRC32 forgery against `fl.dat`), and multiboot
  install sticks are built (`mkjjpmulti.py`). The game binary is **not** in
  `fl.dat`, so writing a modified binary back to an image is already
  mechanically supported — nothing checks its asset CRC.

## Why Spike 2's mechanism does not port — the two hard blockers

### Blocker 1 — the binary is encrypted at rest, so there is nothing to hook statically

The retail JJP `game` is wrapped in **Sentinel LDK Envelope**. On disk,
**7,086 of 8,566 sized functions are ciphertext**; each is fronted by a 5-byte
`call` into a decrypt-and-tail-jump trampoline, and string literals are
encrypted too (`tools/jjp_emu/README.md`). The AES key that decrypts the code
comes from the per-title purple HASP dongle (`0529:0001`).

Spike 2 modes work by overwriting a function's first two instructions with a
jump to a trampoline. On JJP **you cannot see or edit those first two
instructions in the file** — for 83% of functions they are ciphertext until the
dongle decrypts them, on demand, at call time. The static target the Spike 2
technique depends on is simply not present.

### Blocker 2 — you cannot get a library inside the process the Spike 2 way

- **`LD_PRELOAD` cannot reach the game's internal calls.** The envelope resolves
  libc for itself (it imports `dl_iterate_phdr`, `dladdr`, `dlsym`, `dlvsym`)
  instead of going through the PLT/GOT the loader points at a preloaded object.
  Measured: a mapped `LD_PRELOAD` shim logged **zero** `open`/`fopen` over a 40 s
  run while the game opened thousands of files. The hooks never fire
  (`README.md`, "the boards WERE being opened").
- **`hasp_*` and friends are statically-linked internal symbols** reached by
  direct rel32 calls with zero relocations — there is no PLT slot to shadow.
- **`ptrace` is tripwired.** Attaching a debugger raises `Debugger detected
  (E2011)` and the game deliberately `SIGSEGV`s itself. So runtime code
  injection via a ptrace launcher is out too.

So neither of the two ways we insert code on Spike 2 (preload; or patch the
on-disk prologue) is available on an Envelope-protected JJP binary.

## The only conceivable route, and why it is not ready

There is one lead: **de-envelope the binary first**, then treat the result as an
ordinary x86-64 C++ program and do Spike-2-style static hooks / an ext-segment.

`tools/jjp_emu/unpack.py` is a draft that does exactly this: with the game
running (started *with* its key), ~99.9% of functions are already plaintext in
RAM (measured: 9 of 7,091 still trampolined), so it dumps every `PT_LOAD` out of
`/proc/<pid>/mem`, writes them over a copy of the on-disk ELF, and repoints the
entry at the game's own `_start` (0x5bd480) — a binary that never enters the
envelope and never asks for the key. Its own docstring frames it as the "run it
once with your own key to make a key-free copy of your own game" case.

Why this is not a foundation to build on today:

- **It is unproven.** It is an untracked draft (`f0e741de`); there is **no
  recorded evidence the de-enveloped binary boots**, and 9 functions are still
  ciphertext after warm-up (any one of them on a rules path would crash it).
- **Runtime self-integrity is unknown.** We do not know whether the game or the
  envelope checks its own code at runtime; a de-enveloped, then hook-patched,
  binary might trip that.
- **Per-title gate.** Even for development, each title's own physical dongle is
  required to produce the plaintext in the first place; we hold keys for only
  ~4 of the titles.
- **IP exposure.** Shipping a fully de-enveloped JJP game binary is categorically
  different from the asset retheme and multiboot we ship now — it is the game's
  protected code in the clear. That is a call for David, not a technical detail.

Even if `unpack.py` matured into a proven, key-free binary, **pillars 1 and 3
are still unbuilt**: JJP has had *no* reverse engineering of its mode/rules
classes, scoring, event dispatch or display/sound command path. That is the
multi-month, ~100k-line part of Spike 2, and it would start from zero on a C++
codebase we can only read once it is decrypted.

## Recommendation

**Do not open a JJP custom-modes feature now.** The honest scope is: a *research
spike*, gated on David's yes for the IP question, with one narrow goal —

1. Prove or kill `unpack.py`: does a de-enveloped Wonka (the rig's dev title)
   **boot to attract and start a ball** on the rig? (1 title, 1 dongle, no new
   code — pure verification.)

Only if that passes is there any point costing pillars 1/3. If it fails, JJP
custom modes are off the table until someone defeats the envelope another way,
and this file is the record of why.

What *is* already feasible and shippable on JJP, for contrast: image/sound/video
/text retheme (done) and multiboot sticks (done). "Modes" is the one class of
change that needs the game's *code*, and that is the wall.

## One-line verdict for the dashboard

JJP modes are **not feasible as a Spike-2-style feature today**: no rules RE
exists, and the preload+trampoline mechanism is blocked by the Sentinel envelope
(code encrypted at rest, `LD_PRELOAD` can't reach it, `ptrace` tripwired). The
only opening is the unproven `unpack.py` de-envelope path — worth a small,
IP-gated spike to prove-or-kill on Wonka, nothing more.
