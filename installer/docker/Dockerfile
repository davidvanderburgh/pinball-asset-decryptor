# The app in a container you reach over VNC (PAD-837): the Linux release on
# a virtual screen, with a VNC server (port 5900) and the same screen in a
# browser through noVNC (port 6080).  Every manufacturer's tools are
# installed, so the prerequisites row is green from the first start.
#
#   docker build -f installer/docker/Dockerfile -t pinball-asset-decryptor installer
#   docker build -f installer/docker/Dockerfile --build-arg PAD_VERSION=v1.289.0 -t pinball-asset-decryptor installer
#
# PAD_VERSION picks the release; "latest" (the default) asks GitHub at build
# time, so rebuilding the image is how it updates.  See docs/guide/docker.md.

FROM ubuntu:24.04

ARG PAD_VERSION=latest
ARG PAD_REPO=davidvanderburgh/pinball-asset-decryptor
ENV DEBIAN_FRONTEND=noninteractive

# The screen, the VNC servers, a window manager, and what the app's own
# window (Qt WebEngine) needs from the system.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget jq tzdata locales sudo \
        xvfb x11vnc openbox novnc python3-websockify xterm \
        fonts-dejavu-core fonts-noto-color-emoji \
        libegl1 libgl1 libgl1-mesa-dri libxkbcommon-x11-0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
        libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
        libnss3 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2t64 \
        libxtst6 libxshmfence1 libdbus-1-3 libfontconfig1 libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/*

# Every manufacturer's prerequisites: the apt column of
# installer/install_prerequisites_linux.sh, all of them picked.  With their
# recommends, as that script installs them: the ARM compiler's C headers
# (libc6-dev-armhf-cross) come only that way, and the emulator's hardware
# shim does not build without them.
RUN apt-get update && apt-get install -y \
        e2fsprogs gnupg ffmpeg partclone zstd python3-zstandard tar unzip \
        webp xorriso pigz gcc libc6-dev xxd \
        qemu-user-static gcc-arm-linux-gnueabihf make fuse3 python3-gi \
        gir1.2-webkit2-4.1 busybox-static \
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

# Stern Emulate's save states need criu, which no Ubuntu publishes: the
# app's own build script makes it once here instead of on first use.  Its
# last step, `criu check`, needs capabilities a build never has, so the
# binary it built is installed anyway; a --privileged container passes it.
RUN (bash /opt/pad/usr/bin/_internal/tools/spike2_emu/getcriu.sh \
        || install -m 755 /var/tmp/pad-criu/criu/criu/criu /usr/local/bin/criu) \
    && rm -rf /var/tmp/pad-criu /var/lib/apt/lists/*

# The app's window fills the screen; the emulators' windows open as usual.
RUN sed -i 's#^<applications>#<applications><application class="pinball-decryptor"><decor>no</decor><maximized>yes</maximized></application>#' \
        /etc/xdg/openbox/rc.xml

COPY docker/start.sh /usr/local/bin/pad-start
RUN chmod +x /usr/local/bin/pad-start

# /config is the app's home (settings, projects, logs); /data is where your
# game files live.  PUID / PGID default to Unraid's nobody:users.
# PAD_FORCE_NATIVE: Docker Desktop's kernel says "microsoft", but this is
# not WSL.
ENV PUID=99 PGID=100 RESOLUTION=1600x900 TZ=Etc/UTC \
    HOME=/config XDG_CONFIG_HOME=/config/.config DISPLAY=:1 \
    LANG=C.UTF-8 PAD_UI_NO_UPDATE_CHECK=1 \
    PAD_FORCE_NATIVE=1
# Xvfb has no GPU: Qt draws in software and its web view skips the GPU.
# Docker's 64 MB /dev/shm is too small for the web view, so it uses /tmp.
ENV QT_XCB_GL_INTEGRATION=none QT_QUICK_BACKEND=software \
    QTWEBENGINE_DISABLE_SANDBOX=1 \
    QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --disable-dev-shm-usage"
VOLUME ["/config", "/data"]
EXPOSE 5900 6080
ENTRYPOINT ["/usr/local/bin/pad-start"]
