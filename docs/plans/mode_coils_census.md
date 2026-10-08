# Mode coils on the other Spike 2 titles: a census (PAD-394)

David, 2026-10-05, on PAD-381: *"do these tickets have implications for the other supported spike 2 games (and are
they generically covered?)"*. PAD-381 built the magnet grab, the held coils and the scoop hold on Godzilla Pro and
Premium/LE 1.16 only. This is what the other 34 supported builds have, how much of PAD-381 reaches them, and what
was proven here.

## What is generic and what is not

PAD-381's runtime (`pad_mode_runtime.c` "the magnet", "held coils", "the scoop") needs three kinds of port line:

| part | lines | whose |
|---|---|---|
| sending one bounded command, from a process of ours that controls the coil | `coil_fire`, `proc_exists`, `proc_create`, `proc_sleep`, `coil_take`, `coil_give`, `value magnet_proc` | the FRAMEWORK's: `adjustment` and the process calls drafted by `port_tool.py` by signature on all 34 other builds, `coil_fire` on 26, `coil_take`/`coil_give` on 2 (the shape below finds them on 7 more) |
| which coil | `<name>_get` (the game's getter for its ControlCoil object), `<name>_dev` | the TITLE's: found from the class's vtable (below) |
| the coil object's own virtuals the runtime calls: v[29] pulse power, v[30] pulse ms, v[31] hold power, v[36] on-time, v[40] disabled, +44 the controlling process | none: compiled into the runtime | the GENERATION's: the same functions at the same slots only where ControlCoil is Godzilla's |
| the Godzilla magnet part (Mode > Magnet) | `magnet_get`, `adjustment` + ids 363-366/343, `magnet_shot`, `magnet_procs` | Godzilla's alone |
| the scoop hold | `scoop_handler`, `data scoop_slot`, `value scoop_event` (2, the framework ball device's settled-ball event) | the handler is the TITLE's; the slot is placed by `port_tool.py` from it (below) |

The coil frame on the node bus (cmd 0x40, byte 7 the hold power; cmd 4d OFF) is the framework's, and `[coildrive]`
reads it on every title.

## The coil classes, by generation (RTTI, `rtti_tree.py`)

**A. Godzilla's ControlCoil** (`ControlCoil -> HookListener`, 59-61 virtuals; slots 29-31, 36, 40, 54-58 the same
functions): Godzilla Pro 1.15/1.16, Premium/LE 1.16, **Jaws LE 1.02** (60), **King Kong LE 0.97** (61). The whole
held-coil route applies unchanged.

**A'. ControlCoil with 47 virtuals**: Avengers Infinity Quest LE 1.09 (TowerMagnet dev 12, TowerUpPost dev 11),
Jurassic Park LE 1.16 (TRexMagnet dev 17; ControlRoom 14, LeftInlane 8, Orbit 13 and Raptor 15 up posts; TRexJaw
18). Getters and devices found (below), but NOT ONE of the runtime's slots lines up with Godzilla's: the runtime
would call the wrong virtuals. Needs the slots as port values first.

**B. `spike::ControlCoil`** (a namespaced rewrite): Deadpool LE 1.14 / Pro 1.16, Iron Maiden LE 1.16 (LeftUpPost,
RightUpPost, TombLockGate), Led Zeppelin LE/Pro 1.22 (ElectricMagicDiverter/Magnet), Star Wars ELG 1.10
(RightControlGate), Sword of Rage LE 1.18 (MagnaSaveMagnet, ShieldDiverter). Its take/give have the same shape
(found at the addresses in the table); its vtable has not been aligned with A's yet.

**C. The older `Device` framework** (`Diverter -> Device`, `ControlGate -> Device`, no ControlCoil): Elvira 3,
James Bond LE 1.06, Stranger Things LE 1.12, Star Wars LE 1.30, and (by its adjustment names) Aerosmith, Batman,
Beatles, Guardians, John Wick, Rush, Metallica, Munsters, Mando, Turtles, Venom, Foo Fighters, D&D, Jurassic Park
the Pinball, James Bond 60th. A different object and command path: PAD-381's route does not reach them at all.

**D. Uncanny X-Men LE 0.98**: its own `Singleton<Magnet>`, `Singleton<Ramp_Diverter>`, `Singleton<Right_Return_Post>`.

## Per build: what is worth a mode holding, and what never

"Worth holding" = a magnet, a diverter, a gate or an up post: a coil the game itself holds as pulse-then-hold, which
a mode holding for seconds changes where the ball goes and nothing else. **Never exposed, on any title**: flippers,
slingshots, pop bumpers, the trough eject and the auto plunger, every scoop/VUK/eject kicker (the scoop hold leaves
the kick to the game), kickbacks, lock posts that hold locked balls (King Kong's TrainLock, the lock posts of
Deadpool, John Wick, Star Wars LE, Sword of Rage), motors and steppers (Godzilla's shield and building, turntables,
discs, toy boxes - the shield has its own part, PAD-379), and magnets the game uses to FLING (Metallica's electric
chair and grave marker: "FLING POWER").

| build | magnet | diverter / gate / post | scoop (from its labels) | generation | here |
|---|---|---|---|---|---|
| godzilla_pro-1.15 | Godzilla magnet | - | right scoop | A | **magnet + scoop PROVEN** (PAD-394) |
| godzilla_pro-1.16 | Godzilla magnet | - | right scoop | A | proven (PAD-381) |
| godzilla_le-1.16 | Godzilla + Mechagodzilla magnets | bridge | right scoop | A | proven (PAD-381) |
| king_kong_le-0.97 | spider magnet (dev 10) | log diverter (13), center ramp diverter (15) | cave / gong VUKs | A | **three held coils PROVEN** (PAD-394) |
| jaws_le-1.02 | - | left (14) and right (13) inlane up posts | - | A | **two held coils PROVEN** (PAD-394) |
| avengers_infinity_le-1.09 | tower magnet (12) | tower up post (11) | subway VUK | A' | getters found; slots differ |
| jurassic_park_le-1.16 | T-Rex magnet (17) | 4 up posts | - | A' | getters found; slots differ |
| deadpool_le-1.14 / pro-1.16 | - | control gates | Hellhouse scoop | B | take/give found |
| iron_maiden_le-1.16 | - | left/right up posts, tomb lock gate | center, underworld scoops | B | take/give found |
| led_zeppelin_le-1.22 | Electric Magic magnet | Electric Magic diverter, control gates | left eject | B | take/give found |
| led_zeppelin_pro-1.22 | - | control gates | left eject | B | take/give found |
| star_wars_elg-1.10 | - | right control gate | - | B | take/give found |
| sword_of_rage_le-1.18 | Magna-Save magnet | shield diverter, gates | castle / shield VUKs | B | take/give found (two) |
| aerosmith_le-1.15 | toy box magnet | toy box diverter, upper orbit gate | left/right scoops | C | - |
| batman-1.13 | turntable magnet | turntable diverter, left gate | penguin VUK | C | - |
| beatles-1.29 | top magnet, disc magnet | - | - | C | - |
| elvira3-1.13 | - | trunk diverter, house ramp diverter, left gate | crypt/cellar VUKs | C | - |
| guardians_le-1.14 | orb magnet | orbit gates | right scoop | C | - |
| james_bond_le-1.06 | jet pack magnet | center lane diverter, back ramp / bottom lane up posts, top gate | left eject | C | - |
| james_bond_60th_le-1.11 | - | left/right control gates | left/right scoops | C | - |
| john_wick_le-1.01 | - | crate diverter, ramp diverter | left scoop, right VUK | C | - |
| jurassic_park_the_pin-1.05 | - | left control gate | - | C | - |
| metallica_spike-1.03 / 1.04 | coffin magnet (grave marker / electric chair FLING: never) | loop diverter, loop up post | right eject | C | - |
| munsters_le-1.28 | Herman magnet | ramp diverter, top up post | lower PF VUK | C | - |
| mando_le-1.44 | - | ramp diverter, top post | left/right scoops, up-down scoop | C | - |
| rush_le-1.18 | time machine magnet | ramp diverter, double up post | main / side scoops | C | - |
| stranger_things_le-1.12 | - | left ramp diverter, left ramp up post | left eject | C | - |
| star_wars_le-1.30 | 4 accelerator magnets | exit diverter, up / reflexing posts, gates | right eject | C | - |
| turtles_le-1.59 / pro-1.58 / 1.59 | pizza magnet (Pro 1.58) | van diverter, up post | - | C | - |
| venom_le-1.07 | - | top post, up post | center / 180 scoops | C | - |
| foo_fighters_le-1.04 | Overlord magnet | upper PF diverter, outlane up post | - | C | - |
| dungeons_and_dragons_le-1.00 | magnet | diverter, up post | dragon / top VUKs, left eject | C | - |
| uncanny_xmen_le-0.98 | magnet | ramp diverter, right return post | - | D | - |

(Labels read from each program's adjustment and lamp names; a "-" is "none named", not proof of none.)

## How the lines were found (port_tool and the finders)

- **Framework calls by signature**: `port_tool.py` with Godzilla Pro 1.16 as the reference places `adjustment`
  and the three process calls on all 34 other builds, `coil_fire` on 26 (not Aerosmith, Batman, Guardians, Iron
  Maiden, Mando, Stranger Things, Sword of Rage, Turtles Pro 1.58), and `coil_take`/`coil_give` on King Kong and
  Jaws only.
- **Take/give by shape** (where the signature does not reach): give begins `cmp r1,#0; push {r3,r4,r5,lr}; mov
  r5,#0; mov r4,r0; strh r5,[r0,#0x2c]`, take is the function before it reading `ldrh r3,[r0,#0x2c]` (+44, the
  controlling process). Found that way on every A, A' and B build it was run on (all but Deadpool Pro and Led Zeppelin Pro).
- **A coil's getter by its class**: the class's vtable+8 sits in exactly one getter's literal pool beside a call
  to the ControlCoil constructor, whose r1 is the device (`mov r1,#dev`). Checked on Godzilla Premium 1.16, where it
  gives back the port's three getters and devices exactly; the tests check each port's getter passes its device.
- **The scoop's slot** (new in `portgen.py`, `SLOT_DATA`): no code loads it (the framework walks its ball device
  records), so a draft places it as the one writable word holding the placed handler's address. Godzilla Pro 1.15:
  `0x744728`.
- **Title values** (new in `portgen.TITLE_VALUES`): `magnet_shot`, `magnet_dev`, `magnet_proc` and the Premium's
  coil devices are one title's machine, left out of another title's draft rather than copied; `magnet_shot` is a
  mask, not an address, so a draft within the title keeps it.

## Proven here (emulator, rig 2, muted, hidden; the stock cards; `[coildrive]` from the rig's gzwatch.log)

- **Godzilla Pro 1.15** (`magnet 2000`, `scoop_hold 4000`, started on the Godzilla target): two grabs held to their
  end (255 for 350 ms then 50 for 1650, node 9 coil 6, the game's OFF 2017 / 2000 ms on); a hit 1 s into a grab
  refused with no OFF from the game; a mode stop let go 115 ms early. The scoop: no mode, kicked 1829 ms after
  landing; in the mode 5850 ms (held 4016); a mode stop 3 s into a hold let go (the kick 912 ms later); after the
  mode, 1832 ms. No abort.
- **King Kong LE 0.97** (`coil_hold` spider_magnet, log_diverter, ramp_diverter 2000 as the mode starts): one
  command each at the object's own powers (255/500 then 30; 180/200 then 48; 255/64 then 48; node 9 coils 0, 1, 7),
  the game's OFF 2016 ms on; a mode stop 1.5 s into a second hold let all three go with 490-500 ms left. No abort.
- **Jaws LE 1.02** (`coil_hold` left_post, right_post 2000): 255 for 128 ms then 51 (node 9 coils 6 and 7), OFF
  2015 ms on; a mode stop let both go with 489 ms left. No abort.

Not run on these three: a drain or tilt mid-hold (the runtime's unwind path, proven on both 1.16 builds, is the
same code), a hit mid-hold on King Kong / Jaws (refused by the same `pm_coil_hold` the Premium proved). No machine.

## Next (each its own ticket)

1. **A' (Avengers, Jurassic Park LE)**: name the ControlCoil slots in the port (`value coil_v_pulse_power` ...),
   default Godzilla's, and align their vtables; then the T-Rex magnet and the tower magnet are the same route.
2. **B (`spike::ControlCoil`)**: align its vtable with A's; if the slots match, Deadpool, Iron Maiden, Led
   Zeppelin, Star Wars ELG and Sword of Rage follow with getters found as above.
3. **The scoop on other titles**: find each title's scoop handler (the framework ball device's records, walked by
   the device process); the slot then drafts itself. Only Godzilla, King Kong, Avengers, Venom and D&D name their
   handlers as strings.
4. **C and D**: a different coil object entirely; a census of their Device/Diverter calls first.

## PAD-420: held by the board address (the newest builds)

PAD-420 built the mechanisms helper's route: a coil held by its BOARD ADDRESS (`text <name>_drive <node> <coil>
<pulse power> <pulse ms> <hold power>`) through the framework's own `coil_fire` and coil table, with the coil's object
taken while it holds where the game would otherwise switch it off (`value <name>_ctl`, the title's take/give, and
`site <name>_get` or `data <name>_obj`), and the operator's "disabled" asked of the object (`value <name>_off_slot`).
The powers are always the GAME's own for that coil, read off the program:

| generation | class | its "on" | control | disabled | object |
|---|---|---|---|---|---|
| B, Iron Maiden 1.18 | `spike::ControlCoil` subclasses `LeftUpPost`, `RightUpPost` | v[42]: 200 for 64 ms, then 64 (up to 20 s) | +0x1c | v[30] | guarded singleton getters |
| B, Deadpool 1.16, Led Zeppelin 1.22, Sword of Rage 1.19, Star Wars ELG 1.10 | `OrbitControlGates`, `RightControlGate` | v[42]: 255 for 64 ms, then 96 for 6 s (Star Wars ELG: 128) | +0x20 | v[30] | built by a STATIC INITIALIZER, no getter (`data <name>_obj`); calling the initializer builds them again and the game dies (Deadpool Pro, exit 4) |
| A', Avengers 1.10, Jurassic Park 1.16 | `ControlCoil` (47 virtuals) subclasses: tower magnet and post, T-Rex magnet, raptor / orbit / control room / left inlane posts | v[44] fires the object's own fields: pulse power +0xa, pulse ms +0xc, hold power +0xe (the getter's constants: T-Rex magnet 255 for 300 ms then 128; tower magnet 255 / 300 then 100; posts 255 / 64 or 128 then 64) | +0x28 | v[31] | guarded singleton getters |

Left out on purpose: Iron Maiden's tomb lock gate (holds locked balls), Deadpool LE's up/down ramp (pulse only), Jurassic
Park LE's T-Rex jaw (its own mechanism). Scratch tools in `C:/tmp/PAD-420/coils` (bderived.py, aderived.py, offslot.py,
bobj.py, takegive.py, mkstage_b.py, coil_job.sh, coil_verdict.py, coil_land.py).

**C (the Device framework)**: each class has its own take/give at its own offset (Aerosmith LE: +0x18 for its gate and
diverter classes, +0x14 for its toy box magnet), but the gates are driven through another service (ControlGate v[28]:
a byte at +4, a time and a callback), not `coil_fire`, so their powers are not in the code. Do not hold a C gate by
`coil_fire` until that service's powers are read. Its magnets do call `coil_fire` (Aerosmith LE's toy box magnet: 255
for 1 s, then 16).
