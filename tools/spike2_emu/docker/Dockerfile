# The Spike 2 emulator in a container, so it runs on macOS.
#
# WHY A CONTAINER AT ALL, AND WHY THIS IS NOT A PORT. `qemu-user` translates
# LINUX syscalls, and `unshare`, user namespaces and `chroot` into an ELF root
# filesystem are Linux kernel features. None of them exist on Darwin. So macOS
# support is not a matter of effort on the rig - it is "run Linux there", and
# this is that Linux.
#
# THE DISPLAY, which is the part that decides whether any of this is worth
# having. The container runs its OWN X server (Xvfb) and exports it over VNC.
# Everything X does stays inside Linux at full speed and only the finished
# framebuffer leaves, compressed and damage-tracked. The obvious alternative -
# forwarding X to XQuartz on the Mac - pushes every frame across the VM boundary
# as uncompressed X protocol, about 4 MB a frame at 1360x768, and needs xhost
# and DISPLAY plumbing on top.
#
# VNC also means NOTHING TO INSTALL ON THE MAC: macOS Screen Sharing speaks VNC,
# so `open vnc://localhost:5900` is the whole client story.
#
# MEASURED BEFORE THIS WAS WRITTEN, on a headless Xvfb with software rendering
# forced (GALLIUM_DRIVER=llvmpipe), which is exactly what a container with no
# GPU gets: the renderer held 60.4 fps and averaged 58.6 fps over 180 s, and
# scraping that framebuffer at 30 fps kept up in real time at 1.0x. Software
# rasterisation is NOT the bottleneck here and never was - the 1 fps number this
# project remembers is `glraster.c` running inside the emulated ARM guest, which
# the GL bridge replaced and which this never uses.
FROM ubuntu:24.04

# qemu-user-static        runs the machine's 32-bit ARM game binary
# gcc-arm-linux-gnueabihf builds the LD_PRELOAD hardware shim
# e2fsprogs               rootfs.sh, which needs no root to extract a card
# fuse3                   fusermount3, so a card mounts read-only without root
# python3-tk              the virtual playfield window
# xvfb + x11vnc           the display, per the header
# libegl1 + mesa dri      llvmpipe, the software rasteriser padglhost renders on
# ffmpeg                  the host-side H.264 decode the guest cannot do itself
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash coreutils procps psmisc util-linux \
        qemu-user-static gcc-arm-linux-gnueabihf libc6-dev \
        `# BOTH compilers, and the native one is easy to forget. The shim is` \
        `# cross-compiled for the ARM guest (gcc-arm-linux-gnueabihf), but` \
        `# padglhost is a NATIVE binary - the whole GL bridge exists to get the` \
        `# rendering out of the emulated guest - so buildbridge.sh needs plain` \
        `# gcc as well, and fails with "gcc: command not found" without it.` \
        gcc \
        `# fuse2fs INSTALLED, not downloaded. cardmount.sh can fetch it into a` \
        `# private prefix with apt-get download, which is how it works on a` \
        `# machine with no root - but this image drops apt's package lists, so` \
        `# that path has nothing to resolve against and the run died at` \
        `# "could not get fuse2fs" on a box that could simply have had it.` \
        e2fsprogs fuse2fs fuse3 \
        python3 python3-tk python3-pil python3-pil.imagetk \
        xvfb x11vnc x11-utils \
        libegl1 libgl1-mesa-dri libx11-6 libgles2 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# NOT root, because the rig is built around not having root and says so
# everywhere: cardmount.sh fetches fuse2fs into a private prefix rather than
# installing it, and rootfs.sh extracts with debugfs rather than a loop mount.
# Running as root here would let those paths rot untested.
#
# UID 1000 SPECIFICALLY, and it has to be taken rather than requested: Ubuntu
# 24.04 ships a stock `ubuntu` user already sitting on it, so `useradd -u 1000`
# fails with "UID 1000 is not unique". The UID matters because on a Linux host
# the bind-mounted checkout and the named volumes belong to the first real user,
# which is 1000 nearly everywhere - a mismatch shows up as permission errors
# that read like rig bugs rather than like a container detail.
RUN userdel -r ubuntu 2>/dev/null || true; \
    useradd -m -u 1000 -s /bin/bash pad
WORKDIR /pad

# /pad/rig     the rig itself, mounted from the checkout
# /pad/cards   card images, mounted READ ONLY
# /pad/home    $HOME - the shim build directory, logs, the card cache
# /pad/rootfs  $PAD_ROOT, the guest filesystem rootfs.sh builds from a card
ENV PAD_ROOT=/pad/rootfs \
    HOME=/pad/home \
    DISPLAY=:99 \
    GALLIUM_DRIVER=llvmpipe \
    PAD_FORCE_NATIVE=1
RUN mkdir -p /pad/rig /pad/cards /pad/home /pad/rootfs \
    && chown -R pad:pad /pad
VOLUME ["/pad/home", "/pad/rootfs"]

# The VNC display. 5900 is the port macOS Screen Sharing expects by default.
EXPOSE 5900

USER pad
COPY --chown=pad:pad entrypoint.sh /pad/entrypoint.sh
ENTRYPOINT ["/bin/bash", "/pad/entrypoint.sh"]
CMD ["watch.sh", "30"]
