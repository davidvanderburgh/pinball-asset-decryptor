#!/bin/bash
# The container's start (PAD-837): a virtual screen, a window manager, VNC
# on 5900, noVNC on 6080, and the app on that screen as PUID:PGID.  Closing
# the app starts it again, so the container stays reachable.
set -eu

PUID=${PUID:-99}
PGID=${PGID:-100}
RESOLUTION=${RESOLUTION:-1600x900}

# The user the app runs as: your share's owner, so files it writes into
# /data and /config are yours.  It may sudo (loop devices, mounts) - it is
# the only user in the container.
if ! getent group "$PGID" >/dev/null; then groupadd -g "$PGID" pad; fi
if ! getent passwd "$PUID" >/dev/null; then
    useradd -u "$PUID" -g "$PGID" -d /config -s /bin/bash -M pad
fi
USER_NAME=$(getent passwd "$PUID" | cut -d: -f1)
usermod -d /config -s /bin/bash "$USER_NAME" 2>/dev/null || true
echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/pad
chmod 0440 /etc/sudoers.d/pad
mkdir -p /config/.config /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
chown "$PUID:$PGID" /config /config/.config

# Stern Emulate runs 32-bit ARM game programs through qemu, which the kernel
# has to know about.  The kernel is the server's, shared by every container,
# so this needs --privileged and is left alone when the server already has
# one.  The F flag makes it work from inside this container.
BINFMT=/proc/sys/fs/binfmt_misc
if [ ! -e "$BINFMT/register" ]; then
    mount -t binfmt_misc binfmt_misc "$BINFMT" 2>/dev/null || true
fi
if [ -w "$BINFMT/register" ] && [ ! -e "$BINFMT/qemu-arm" ]; then
    if cat /usr/lib/binfmt.d/qemu-arm.conf > "$BINFMT/register" 2>/dev/null
    then
        echo "Registered qemu-arm with the kernel for Stern Emulate."
    fi
elif [ ! -e "$BINFMT/qemu-arm" ]; then
    echo "Not privileged: Stern Emulate needs --privileged (see the guide)."
fi

rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xvfb :1 -screen 0 "${RESOLUTION}x24" -nolisten tcp &
for _ in $(seq 50); do [ -e /tmp/.X11-unix/X1 ] && break; sleep 0.1; done

as_user() { setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$@"; }

as_user openbox &

VNC_ARGS=(-display :1 -forever -shared -rfbport 5900 -noxdamage -quiet)
if [ -n "${VNC_PASSWORD:-}" ]; then
    x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vncpass >/dev/null
    VNC_ARGS+=(-rfbauth /tmp/vncpass)
else
    VNC_ARGS+=(-nopw)
fi
x11vnc "${VNC_ARGS[@]}" &
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &
ln -sf vnc.html /usr/share/novnc/index.html

echo "Pinball Asset Decryptor $(cat /opt/pad/VERSION): VNC on 5900," \
     "browser on http://<server>:6080/"
cd /data 2>/dev/null || cd /config
while true; do
    as_user env HOME=/config /opt/pad/AppRun || true
    sleep 2
done
