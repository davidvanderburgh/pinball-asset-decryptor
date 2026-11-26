# PAD-1605 proof: Try it on JJP (Modes tab -> Emulate tab)

Wonka 03.03, Wonka's own key, hidden and muted, 2026-11-25. The start Try it hands the Emulate tab
(`launch_iso(iso, modes=(runtime, folder))` -> `JJP_MODS_SO` / `JJP_MODS_DIR` passed to watch.sh),
with the runtime `mkjjpmodes.py runtime` built for the ISO and the starter mode folder:

    bash run.sh /mnt/c/Users/<you>/AppData/Roaming/pinball_decryptor/jjp_modes/.runtime/<Wonka>.so \
                /mnt/c/Users/<you>/AppData/Roaming/pinball_decryptor/jjp_modes/Wonka-v03.03

Result (`jjpmodes.log`): both modes loaded from /tmp/padmodes/modes; a game started on credits;
`switch_target_tv` started "PAD Mode" (its panel over the game's screen, 20 s); five scoring shots
scored 1,000,000 each and COMPLETED it (+5,000,000, mode total 10,000,000). rc 0.
