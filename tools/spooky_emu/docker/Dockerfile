# The Spooky emulator in a container, so it runs on macOS (PAD-953).
#
# WHY A CONTAINER. The rig is Linux through and through: the games are native
# x86-64 Linux programs (Unity, Godot, and Alice Cooper's / Rick and Morty's
# Python 2.7 beside a Unity player), and run_game.sh gives each its own mount,
# UTS and network namespace and binds the build where the machine keeps it.
# None of that exists on Darwin, so on a Mac this is the Linux it runs in -
# the same answer tools/spike2_emu/docker gives the Stern rig.
#
# WHY linux/amd64, EVEN ON APPLE SILICON. The games are Intel binaries, and
# so is the Python 2.7 environment tools/ap_emu/setup.sh downloads (conda-
# forge's py27 builds exist for linux-64 only). spkbox.sh builds and runs this
# image as linux/amd64 everywhere, and an Apple-silicon engine translates it:
# Docker Desktop through Rosetta, colima through the amd64 handler it
# registers in its VM at start ("installing: ... amd64 OK", PAD-884's log).
# On an Intel Mac it is native.
#
# THE PACKAGES ARE PAD-RUNTIME'S (tools/runtime/Dockerfile), the Linux every
# Spooky title was proven on, minus what only the Stern rigs use, plus what a
# box with no desktop needs:
#   xvfb x11vnc openbox   the display, exported over VNC on 5900 (macOS Screen
#                         Sharing is the client; see the Spike 2 box for why
#                         VNC and not XQuartz)
#   pulseaudio            the sound server WSLg gives the rig on Windows; the
#                         box serves its output raw on a loopback TCP port and
#                         spkbox.sh plays it on the Mac
#   python3-gi + webkit   the virtual playfield (spkpf.py -> appf.py -> pfweb),
#                         a web page in a GTK WebKit window in the box
#   mesa (llvmpipe)       the games' OpenGL; a container has no GPU
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash coreutils procps psmisc util-linux ca-certificates curl \
        python3 gnupg tar gzip xz-utils \
        xvfb xauth x11vnc x11-utils openbox \
        libgl1 libglx-mesa0 libgl1-mesa-dri libegl1 libgles2 \
        libx11-6 libxcursor1 libxrandr2 libxi6 libxinerama1 libxss1 \
        libasound2t64 libpulse0 pulseaudio pulseaudio-utils \
        python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 fonts-ibm-plex \
    && rm -rf /var/lib/apt/lists/*

# The account the games run as: the rig never runs a game as root (they shell
# out for their housekeeping), and spkpath.sh takes the first ordinary
# account, so uid 1000 is taken from Ubuntu's stock user as on the Spike 2 box.
RUN userdel -r ubuntu 2>/dev/null || true; \
    useradd -m -u 1000 -s /bin/bash pad

# /pad/app     the app's folder, read only: tools/spooky_emu, the rigs it
#              borrows from (proc_emu, ap_emu, spike2_emu's pfweb) and the
#              Spooky plugin's games.py (the update files' keys)
# /pad/files   the folder holding the update file, mounted read only
# /pad/ctl     the app's Volume / Mute file's folder, read only
# /var/tmp     a named volume: the unpacked builds (several GB each), the
#              games' Python, settings and high scores - kept between runs
ENV DISPLAY=:99 \
    GALLIUM_DRIVER=llvmpipe \
    PAD_PULSE_SOCK=/run/pad-pulse/native
RUN mkdir -p /pad/app /pad/files /pad/ctl
VOLUME ["/var/tmp"]

EXPOSE 5900

# ROOT, unlike the Spike 2 box: watch.sh refuses anything else, because
# run_game.sh makes namespaces and bind mounts and drops each game to pad
# itself - on Windows the app runs it as `wsl -u root` for the same reason.
COPY entrypoint.sh /pad/entrypoint.sh
ENTRYPOINT ["/bin/bash", "/pad/entrypoint.sh"]
