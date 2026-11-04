# PAD-980 research: multi-boot on Spooky's pinHeck DMD games

Scope: America's Most Haunted (AMH), Rob Zombie's Spookshow International (RZ),
Domino's Spectacular Pinball Adventure (DOM), Jetsons (JET). Read-only
research; scratch files in `C:\tmp\PAD-980\pinheck` (extracted PRG/BIN under
`bin\`, public sources cloned to `amh_src\` = github.com/benheck/AMH and
`pinheck_hw\` = github.com/LonghornEngineer/Pinheck_Pinball_System).

## 1. What each update holds and how the machine takes it

| zip | files (root of the card) | game CPU (PIC32) | A/V (Propeller) | media, unpacked |
|---|---|---|---|---|
| AMH_SD_V023.zip | `DMD/`, `SFX/`, `VERSION.TXT` ("CODE REVISION 23 / A/V REVISION 23") | **none** | `DMD/PROP_023.BIN` (32 KB) | 1.28 GB, 2270 files |
| rzupdate_V26.zip | `RZO_V026.PRG` (308 048 B), `PRP_V008.BIN`, `WHATSNEW.TXT`, `DMD/`, `SFX/` | RZO_V026.PRG | PRP_V008.BIN | 0.94 GB, 1674 files |
| DOM_v6.zip | `DOM_V006.PRG` (203 152 B), `PRP_V008.BIN` (not the RZ image: 13 403 bytes differ), `DMD/`, `SFX/` (+ stray `System Volume Information`) | DOM_V006.PRG | PRP_V008.BIN | 0.80 GB, 1059 files |
| Jetsons_Code.zip | `Jetsons/` folder = card root: `JET_V004.PRG` (196 448 B), `PRP_V002.BIN`, `WHATSNEW.txt`, `DMD/`, `SFX/` | JET_V004.PRG | PRP_V002.BIN | 0.70 GB, 458 files |

- **One SD card**, read only by the Propeller. Schematic (`pinheck_hw/Hardware/Pinheck Main Board/PinHeck.sch`): only `SD0`, on Propeller P0-P3; the PIC32 has no SD. AMH kernel `av_kernel_23.spin:251` starts only `sd0` (a second card's pins are commented out).
- **Card format**: the kernel turns a cluster into a sector as `(cluster-2) << 6` (`av_kernel_23.spin` getFileSector/BuildFolderList; the same `38 06 e3` shift is in PRP_V008 method 0x32 at 0x2401). That hard-codes FAT32 with 64-sector (32 KB) clusters. It also never follows the FAT chain, so every file must be in one unbroken piece (already noted in `plugins/spooky/games.py` PINHECK_INSTALL).
- **Media lookup** (AMH source plus the same byte-code in PRP_V008 at 0x35f/0x36b): the first root entry whose first 3 characters are `SFX` / `DMD`; inside it, folders `_FA.._FZ` / `_DA.._DZ`; inside those, files matched on name characters 1-2 (`FindSFXEntry`, `av_kernel_23.spin:964`). The names are fixed, and there is no prefix or path that could pick a build.
- **Propeller self-update**: the kernel looks for a root (colour games) or `DMD/` (AMH) entry named `PRP…`/`PROP…`, reads the version from name characters 5-7, and copies 64 sectors into its boot EEPROM ("A/V UPDATING", `flashEEPROM`, `av_kernel_23.spin:2423`). AMH flashes only when the file is newer (`g > AVversion`). In PRP_V008 (method 0x36 at 0x285c) the PRP is reprogrammed during the code-update flow whenever the file is present, with no version test.
- **PIC32 update (colour-era kernels only, PRP_V002/V008)**: the Propeller flashes the PIC. Strings at DOM PRP 0x2895..0x2937 read "FLASHING TO: / CONNECT PIC32: / UPDATE IN 5 SECONDS / PROGRAM FLASH SECTOR n OF / VERIFY FLASH / CODE UPDATE COMPLETE / PLEASE RESTART". Method 0x36 (0x262b):
  - It finds the PRG with method 0x33 (0x247b). That method matches **directory-entry bytes 8-10 = `PRG`, the extension only**. The first match in directory order wins, and deleted (0xE5) entries are not skipped.
  - Method 0x38 prints the file name and method 0x34 reads the version from name characters 5-7 (`XXX_Vnnn.PRG`).
  - It opens a serial object with `(24, 25, …, 115200)` (`3a 01 c2 00`). P24/P25 are the existing PIC link pins COMM_IN_TX/COMM_CLK_RX = PIC RF13/RF12 (U3B), so the PIC side has to be a **bootloader in PIC boot flash** that answers on UART3B. That bootloader is in no update file: the PRG is program flash from 0x9D000000 only, its first 0x180 bytes are 0xFF, and `_reset` is at 0x9D001000.
- **When the PIC gets flashed**. In the boot method (DOM 0x380, JET 0x3c0): `if m35() → update(1)`, then `if EEPROM long 1 == $ABBA0001 → update(0)`. m35 (DOM 0x2527, JET m25 0x21ab) returns true when EEPROM long 0's low word is not `$BAFA` (a blank or foreign EEPROM) **or** Propeller pin 13 is low at power-up. Pin 13 is PROP_PROGRAM, the PROP_CONFIG header (R1 pulls it up to 3.3 V, and the header has a GND pin). EEPROM long *n* = Propeller EEPROM byte 0x8000+4n (m48 at 0x2ee9).
  - The game sets the request itself. Each PRG writes `0xABBA0001` to long 1 (`lui a2,0xabba … addiu a2,a2,1`: DOM 0x17f48/0x17fa4, JET 0x196fc, RZ 0x1f9e8), from the service-menu item **UPDATE CODE** (string at DOM 0xec7c).
  - So the owner's path is: put the new files on the card, choose Service → UPDATE CODE, restart. The Propeller then flashes the first `*.PRG` and the `PRP*` file, and shows PLEASE RESTART. The game then sees `version<<24|BAFA` change, stores defaults and asks for another restart (the emulator's `KAC` "System has been updated").
  - There is **no version comparison** that would block a downgrade.
- **AMH is different**. PROP_023.BIN has no PIC flasher (no "CONNECT PIC32" strings, and `av_kernel_23.spin` only reflashes the Propeller). The zip carries no PRG. The PIC was programmed with a PICkit or the chipKIT USB/UART bootloader: the public board has `PICKIT3`, `USB_PROG`, `PIC32_UART` (DTR → MCLR via R26) and `PIC_PROGRAM_SW` (RG9) (schematic nets). On the public AMH board, **the SD card cannot update AMH's game code**.
- **Version naming**: `<3-letter game>_V<3 digits>.PRG` (version = characters 5-7) and `PRP_V<3 digits>.BIN` (AMH `PROP_<3>.BIN` inside DMD). The game keeps its version in the top byte of Propeller-EEPROM long 0 (`version<<24 | 0xBAFA`, AMH `.pde:17194`, emulator "600BAFA"/"1A00BAFA").
- **Settings live in the Propeller EEPROM's upper half**. When the game boots with a different version it writes default settings and keeps only games-played (`amh_pic32_ver023.pde:17194-17205`).

## 2. Could the machine hold several builds and pick one at boot?

- **Game code: one at a time.** The PIC32MX795 has 512 KB of program flash. Every PRG is linked to the same addresses (0x9D000000, `_reset` 0x9D001000), and RZ alone is 301 KB. A different build means a full reflash by the Propeller: about 200-300 KB at 115 200 baud plus a verify, so roughly 30-60 s by estimate. Each reflash uses one of the flash's limited erase/write cycles (PIC32MX datasheet minimum is on the order of 1 000).
- **Media: one set per card with the stock kernel.** `DMD`/`SFX` are matched on the first 3 characters of the first root entry. A second set (`DMD2`…) is only "whichever comes first in directory order", and the Propeller cannot rename anything. Space is not the problem: a set is 0.7-1.3 GB, and a 32 GB FAT32 card with 32 KB clusters holds 20+.
- **Nobody at power-up can read the flippers except the game program.** Flippers, START and the menu buttons go through the cabinet shift registers U11/U12 into PIC RF0 (nets `L_FLIP`/`R_FLIP`/`ST_BU` → U12/U11 → `CAB_SWITCH_IN`). The Propeller sees only the SD card, its EEPROM, the DMD, audio, the link and the pin-13 header. So a flipper/START menu has to be PIC code, and the PIC holds only the current game.
- **Where a menu could run** (all need new firmware):
  - (a) **Patch each game PRG** (MIPS, per title and per version): holding a flipper at boot opens a menu drawn with the game's own link text commands. The choice goes into Propeller-EEPROM spare longs, and the patch sets `0xABBA0001` and asks for a restart.
  - (b) **A custom Propeller kernel (PRP)** that honours that choice: it flashes the *chosen* PRG instead of the first `*.PRG`, and points `SFX`/`DMD` at that build's folders. There is no public source for the colour-era kernel; only AMH rev23 Spin is public, so this means patching PRP_V008/V002 Spin byte-code or rewriting the kernel. The UART flash protocol to the unknown PIC boot-flash bootloader would have to be kept exactly.
  - Alternatively, (a') a separate **menu PRG** flashed between games. That costs two reflashes per switch (1-2 min) and doubles flash wear.
  - Or (a'') replace the PIC **boot-flash bootloader** via the ICSP header. That needs a PICkit and the existing bootloader is not dumped anywhere.
  - Every switch would still reset operator settings, because the version test writes defaults.
  - AMH cannot take part without a PICkit, since its PIC cannot be flashed from the card.
- **What the emulator can prove** (`tools/pinheck_emu`): it runs a PRG unmodified on Unicorn and stands in for the Propeller at the packet level (`proplink.py`: link packets plus an 8192-long EEPROM; `pic32.py` maps the boot flash only for an ISR trampoline and models UART1 RX only). It could show a **PIC-side** menu: the menu screen, flipper/START handling, and the `0xABBA0001`/selection writes into the stand-in EEPROM. It can **not** prove the Propeller half. It has no Spin interpreter, no UART3B link, no PIC boot-flash bootloader and no model of the PIC reflash. Proving that would need a Propeller emulator (spinsim-class) added, or a real machine.

## 3. Verdict

**A real power-up boot menu is not feasible as an app-built file copied to the SD card.**
- The stock Propeller always takes the first `*.PRG` and the first `DMD`/`SFX`.
- The game CPU holds one program at a time, and only the game program can read the flippers.
- AMH cannot even update its game code from the card.

**Feasible only with substantial firmware work.** That would be:
- a patched or rewritten colour-era Propeller kernel (select PRG and media folders by an EEPROM choice, keep the PIC-flash protocol);
- a boot-time menu hook binary-patched into every supported PRG (RZ, DOM, JET, each version);
- about 30-60 s of reflash on every switch, settings reset to defaults each time, and flash wear;
- AMH excluded unless the owner has a PICkit.

Rough estimate: several weeks of reverse engineering and Spin/MIPS work (the Spin decompile of PRP_V008/V002, the UART flash protocol, three titles' patch points). It cannot be proven without a real board (bricking risk; recovery needs a Prop Plug / PICkit). I do not recommend it.

**What files alone can do today (not a menu): one card per build.**
- RZ/DOM/JET: power off, swap to the other build's card, then Service → UPDATE CODE → restart. The Propeller reflashes PIC and PRP from that card; restart again, and settings go to defaults.
- AMH: card swap changes media only, the game code stays.
- The app already builds one card's worth per output (freshly formatted FAT32 32 KB clusters, copied in one go). A "multi-boot" here could only be "N card folders plus these swap steps".
