# The app in a container you use from a web browser (PAD-837): the Linux
# release on linuxserver.io's Selkies desktop, which streams the screen AND
# the sound to the browser (port 3000, or 3001 for HTTPS), uses the server's
# GPU when /dev/dri is passed in, and runs as PUID:PGID.  Every
# manufacturer's tools are installed, so the prerequisites row is green from
# the first start.
#
#   docker build -f installer/docker/Dockerfile -t pinball-asset-decryptor installer
#   docker build -f installer/docker/Dockerfile --build-arg PAD_VERSION=v1.292.0 -t pinball-asset-decryptor installer
#
# PAD_VERSION picks the release; "latest" (the default) asks GitHub at build
# time, so rebuilding the image is how it updates.  See docs/guide/docker.md.

FROM lscr.io/linuxserver/baseimage-selkies:ubuntunoble

ARG PAD_VERSION=latest
ARG PAD_REPO=davidvanderburgh/pinball-asset-decryptor
ENV DEBIAN_FRONTEND=noninteractive

# What the app's own window (Qt WebEngine) needs from the system, beyond
# what the desktop already has.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl jq \
        libegl1 libgl1 libgl1-mesa-dri libxkbcommon-x11-0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
        libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
        libnss3 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2t64 \
        libasound2-plugins libxtst6 libxshmfence1 libdbus-1-3 \
        libfontconfig1 libglib2.0-0t64 fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Every manufacturer's prerequisites: the apt column of
# installer/install_prerequisites_linux.sh, all of them picked.  With their
# recommends, as that script installs them: the ARM compiler's C headers
# (libc6-dev-armhf-cross) come only that way, and the emulator's hardware
# shim does not build without them.  fuse2fs too: Emulate fetches it with
# apt on first use, and the image keeps no package lists to fetch it from.
RUN apt-get update && apt-get install -y \
        e2fsprogs gnupg ffmpeg partclone zstd python3-zstandard tar unzip \
        xvfb webp xorriso pigz gcc libc6-dev xxd \
        qemu-user-static gcc-arm-linux-gnueabihf make fuse3 fuse2fs \
        python3-gi gir1.2-webkit2-4.1 busybox-static sudo \
    && rm -rf /var/lib/apt/lists/*

# Barrels of Fun's old Godot 3 packs need GDRE Tools.
COPY install_gdre.sh /tmp/install_gdre.sh
RUN bash /tmp/install_gdre.sh && rm /tmp/install_gdre.sh

# The release itself.  An AppImage cannot mount itself in a container (no
# FUSE), so it is unpacked once here and run from the unpacked tree.
RUN set -eu; \
    tag="$PAD_VERSION"; \
    if [ "$tag" = latest ]; then \
        tag=$(curl -fsSL "https://api.github.com/repos/$PAD_REPO/releases/latest" | jq -r .tag_name); \
    fi; \
    url="https://github.com/$PAD_REPO/releases/download/$tag/Pinball_Asset_Decryptor_${tag}_Linux_x86_64.AppImage"; \
    echo "Fetching $url"; \
    cd /opt && curl -fL -o pad.AppImage "$url" && chmod +x pad.AppImage; \
    ./pad.AppImage --appimage-extract >/dev/null; \
    mv squashfs-root pad && rm pad.AppImage && chmod -R a+rX /opt/pad; \
    echo "$tag" > /opt/pad/VERSION

# criu, which the Emulate tab's setup check asks for (save states) and no
# Ubuntu publishes: the app's own build script makes it once here.  Its
# last step, `criu check`, needs capabilities a build never has, so the
# binary it built is installed anyway.
RUN (bash /opt/pad/usr/bin/_internal/tools/spike2_emu/getcriu.sh \
        || install -m 755 /var/tmp/pad-criu/criu/criu/criu /usr/local/bin/criu) \
    && rm -rf /var/tmp/pad-criu /var/lib/apt/lists/*

# Save states (PAD-871): criu can only freeze a game booted as root, and the
# app runs as abc. The app reaches root only through a sudo that asks no
# password (a desktop app has nowhere to type one), so abc gets that here.
# It is root inside this container only; what the container itself may do
# is still whatever `docker run` gave it (docs/guide/docker.md).
RUN printf '%s\n' 'abc ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/pad-savestates \
    && chmod 0440 /etc/sudoers.d/pad-savestates

# Only the app's own window is maximized.  The desktop maximizes every
# window, which would stack the emulator's game, controls and playfield
# windows on top of each other.
RUN sed -i 's#<application class="\*"><maximized>yes</maximized></application>#<application class="pinball-decryptor"><decor>no</decor><maximized>yes</maximized></application>#' \
        /etc/xdg/openbox/rc.xml \
    && grep -q 'class="pinball-decryptor"' /etc/xdg/openbox/rc.xml

# The app starts with the desktop (/defaults/autostart) and again whenever
# it is closed (RESTART_APP); pad-register-arm is the one-off privileged
# helper Stern Emulate needs on a server with no ARM handler yet
# (docs/guide/docker.md).  pad-seccomp.json is the seccomp profile the run
# line names (PAD-872): Docker's default (moby/profiles seccomp/default.json
# at 6fe7deb, 2026-09-17) with namespaces and mounts allowed, so Emulate
# mounts the card in its own user namespace and the container needs no
# SYS_ADMIN.  Docker reads it on the server, so the guide copies it out.
COPY docker/root/ /
RUN chmod 755 /usr/local/bin/pad-app /usr/local/bin/pad-register-arm \
    && chmod 644 /defaults/autostart /usr/share/pad/pad-seccomp.json

# /config is the app's home (settings, projects, logs, the emulator's
# working files); /data is where your game files live.
# PAD_FORCE_NATIVE: Docker Desktop's kernel says "microsoft", but this is
# not WSL.  START_DOCKER: the desktop would otherwise start a Docker daemon
# of its own whenever the container is privileged.
ENV TITLE="Pinball Asset Decryptor" RESTART_APP=true START_DOCKER=false \
    PAD_UI_NO_UPDATE_CHECK=1 PAD_FORCE_NATIVE=1
VOLUME ["/config", "/data"]
EXPOSE 3000 3001
