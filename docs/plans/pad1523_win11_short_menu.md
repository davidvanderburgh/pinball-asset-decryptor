# PAD-1523: Write / Compact with PAD on the Windows 11 short menu

## Why it was missing

Windows 11's first right-click menu lists no static registry verb except the
file type's default one. "Write to a card with PAD" showed there only because
it is the ProgID's default verb, and "Compact with PAD" (PAD-1522) was only
under "Show more options". The PAD-1522 proof shots built the classic menu
through IContextMenu, so they never showed this. Entries such as "Edit in
Notepad" and "Open with Code" reach the short menu because a package declares
an IExplorerCommand handler for them.

## What this adds

- `tools/padmenu/padmenu.c` builds `pinball_decryptor/shell/padmenu64.dll`.
  It holds two IExplorerCommand classes, Write and Compact. Each one is a
  bridge to the app's registry verb: it reads the label, the icon and the
  command from `SystemFileAssociations\<ext>\shell\<verb>`. An entry is hidden
  when the app has no verb for the file. Compact is also hidden on a card
  already stored compact (padicon's `takes_less` rule). Invoke runs the verb's
  own command, with the desktop-app breakaway attribute, so it runs outside
  the package.
- `tools/padmenu/AppxManifest.xml` is the sparse package that gives the
  handler an identity. Its `desktop4:FileExplorerContextMenus` lists Write on
  .raw, .img and .iso, and Compact on .raw and .img, which matches
  open_image's two extension lists. `com:SurrogateServer` holds the two
  classes.
- `tools/padmenu/build.py` does the build. It runs Zig for the DLL, packs the
  package itself (a zip with a SHA-256 block map, stored entries and fixed
  times), signs it with signtool, and writes the stamp. Every output is
  committed, so a release needs no compiler and no key.
- `webui/shell_menu.py` runs per user, beside the association that
  `open_image.register_association` writes at startup. It stages the DLL to
  `%LOCALAPPDATA%\pinball_decryptor\shell_menu\<hash>`, so the surrogate
  never holds a file in the install folder. It then adds the package with
  that folder as its external location. It skips Windows 10, ARM64, and any
  machine that does not trust the certificate. `unregister` takes it all away
  again.
- The installer runs elevated. On Windows 11 it puts `padmenu.cer` in the
  machine's Trusted People. The uninstaller removes the package, the staged
  copy and the certificate.

## Signing: what it costs

| Route | Outcome |
| --- | --- |
| Unsigned package (OID publisher) | Refused per user: "an unsigned package cannot include Executable activations". Without an Executable it is "not a valid unsigned package". Microsoft allows such a package only for all users, elevated. |
| Self-signed and trusted in the user's own TrustedPeople | Refused: 0x800B0109, the root must be trusted. Windows reads only the machine stores. |
| Self-signed and trusted in the machine's Trusted People | This is the one the installer uses. It costs nothing. The key, "CN=Pinball Asset Decryptor", RSA 3072, valid to 2056, lives only in the maintainer's `Cert:\CurrentUser\My`. |
| A commercial code-signing certificate | Not needed, and it costs money every year. |

## Found on the real menu (after the certificate was trusted)

- Windows adds the package per user without elevation, and does not need
  `padmenu.exe` (the manifest's Executable) to exist. Explorer shows the
  entry straight away; it does not need a restart.
- Windows folds EVERY entry that one package offers for a file into a
  single flyout named after the package. Putting each entry in its own
  Application did not change that. Packaged entries are also sorted by
  name, so Write and Compact could never sit side by side. So the package
  declares only Compact, which shows as a flat entry with its icon. "Write
  to a card with PAD" is a .raw's default verb, which Windows 11 already
  lists first. An `Icon` value on that default verb does not show on the
  short menu, so none is written.
- Windows also lists packaged entries under Show more options, so Compact
  appeared there twice. While the package is registered,
  `shell_menu.hide_classic` marks the classic Compact verb
  `ProgrammaticAccessOnly`: it is off every menu, but still readable by the
  handler. It is visible again wherever the package is not registered.
- End to end: clicking Compact on the short menu opened the installed app's
  Compact window and compacted the card. On the card it compacted, Compact
  is then hidden.

## Proof

`scripts/shot_pad1523.py` captures each menu with a real mouse right-click.
`--classic` gives Show more options, and `--hover/--click` opens or chooses
an entry. The shots are in pad-triage `work/artifacts/PAD-1523`.

Tests: `tests/test_pad1523_short_menu.py` checks the build stamp, the
signature and block map, the manifest against the C code, the app verbs and
the installer. It also checks registration and the classic-verb hiding, and
drives the real DLL through COM.
