# PAD-1508 proof: Spike 2's rules on Wonka 03.03

Wonka's Sentinel key attached (`usbipd attach --wsl --hardware-id 0529:0001`), then as root in Ubuntu:

    export PAD_HIDDEN=1 PAD_LABEL=PAD-1508 JJP_ISO=/mnt/d/Pinball/images/JJP/Wonka-v03.03.iso
    export JJP_MODS_SO=/var/tmp/pad1508_jjpmodes.so JJP_MODS_DIR=<this folder>/modes JJP_MODS_TRACE_LAMPS=1 \
           JJP_MODS_TEST_GAMEMODE=cl_mode JJP_MODS_TEST_SWITCH=switch_target_captiveball
    bash ../../buildmods.sh && bash ../../watch.sh
    python3 ../../jjpdrive.py steps.txt      # rc 0 = every wait met

The four modes exercise every rule (MODES.md "Spike 2's rules"); RULES D takes Candy Lane's place
when the test switch starts it.
