# Running it in Docker, from a browser

[← Back to Installing](install.md)

The app can run on a server (Unraid, a NAS, any Linux box with Docker) and
be used from a web browser on any PC. It sees the server's own drives, so
card images and projects never leave it, and every PC you connect from
shares one install, one set of settings and the same projects.

The image is the Linux release on [linuxserver.io's Selkies
desktop](https://docs.linuxserver.io/images/docker-baseimage-selkies/),
with every manufacturer's tools installed. The browser gets the picture
**and the sound**: the Audio tab's previews and the emulators' game sound
play on the PC you sit at.

## Build it

From a copy of this repository:

```bash
docker build -f installer/docker/Dockerfile -t pinball-asset-decryptor installer
```

It takes the newest release. `--build-arg PAD_VERSION=v1.292.0` picks
another. The app's own update check is off in the container: building the
image again is how it updates.

## Run it

Copy the image's seccomp profile out once (Stern Emulate needs it, below):

```bash
mkdir -p /mnt/user/appdata/pinball-asset-decryptor
docker run --rm --entrypoint cat pinball-asset-decryptor \
  /usr/share/pad/pad-seccomp.json > /mnt/user/appdata/pinball-asset-decryptor/pad-seccomp.json
```

Then start it:

```bash
docker run -d --name pinball-asset-decryptor \
  --device /dev/fuse --shm-size 1g \
  --security-opt seccomp=/mnt/user/appdata/pinball-asset-decryptor/pad-seccomp.json \
  --device /dev/dri \
  -p 3001:3001 \
  -e PUID=99 -e PGID=100 -e PASSWORD=choose-one \
  -v /mnt/user/appdata/pinball-asset-decryptor:/config \
  -v /mnt/user/pinball:/data \
  pinball-asset-decryptor
```

Then open `https://<server>:3001/` and log in as `abc` with that password.
The certificate is the container's own, so the browser asks once whether to
trust it. Use HTTPS even on your own network: browsers only decode the
stream on a secure page.

| Setting | What it is |
|---|---|
| `/config` | The app's home: settings, the log, and the Stern emulator's working files. Give it room: Emulate keeps a copy of each card it runs here (about 5 GB for a Spike 2 card). |
| `/data` | Your game files and projects. Browse to them under `/data` in the app. |
| `3001` | The app in a browser (HTTPS). |
| `PASSWORD` | Asked for when you connect. Leave it out and anyone who can reach the port can use the app. |
| `PUID` / `PGID` | Who the files the app writes belong to. On Unraid, `99` / `100` (`nobody:users`). |
| `--device /dev/dri` | The server's GPU (Intel, AMD), as Jellyfin or Plex use it. The desktop encodes the stream with it and the emulator draws the game with it. Leave it out and both run on the CPU. |
| `--device /dev/fuse`, `--security-opt seccomp=...` | Only Stern Emulate needs these (below). |
| `--shm-size 1g` | Room for the desktop's shared memory. |
| `TZ` | Time zone for the log, e.g. `America/Chicago`. |

On Unraid, copy the profile out as above (from a terminal), add a container
with these as its paths, port and variables, add `/dev/dri` as a Device, and
put `--device /dev/fuse --shm-size 1g --security-opt
seccomp=/mnt/user/appdata/pinball-asset-decryptor/pad-seccomp.json` in
**Extra Parameters**. **Privileged** stays off.

### What Stern Emulate needs, and why

The container does not need `--privileged`, or any added capability. Stern
Emulate needs two things from the server; everything else (extracting,
replacing, building cards, every other manufacturer) needs neither.

- **Mounting the card.** The emulator reads the card image without copying
  6 GB out of it, through a FUSE mount (`--device /dev/fuse`). It makes
  that mount inside a user namespace of its own, which changes only what
  the emulator itself sees. Docker's standard seccomp profile refuses
  namespaces to a container, so the image ships `pad-seccomp.json`: the
  same profile with namespaces and mounts allowed. The kernel still
  decides what may be mounted in them.
- **Running 32-bit ARM programs.** The game is one, and the server's kernel
  runs it through qemu once qemu is registered with it. That is the one
  step that needs privileges, so it is a separate container that runs once
  and exits:

  ```bash
  docker run --rm --privileged --entrypoint pad-register-arm pinball-asset-decryptor
  ```

  It does nothing on a server that already has a handler (Docker's own
  multi-platform setup registers one). The registration lasts until the
  server restarts. On Unraid, put that line in a **User Scripts** script set
  to run **At Startup of Array**.

On a host that uses AppArmor (Ubuntu, Debian), also add
`--security-opt apparmor=unconfined`, or the FUSE mount is refused. Unraid
does not use AppArmor. Ubuntu 23.10 and later also restrict user namespaces
on the host itself; there, use `--cap-add SYS_ADMIN` in place of the
seccomp profile (that still works on any host). With neither, the
emulator's log says what to add.

## What to expect

- **Emulators run on the server.** Their speed is the server's CPU and GPU,
  not the network. Only the picture and sound travel, so a slow link
  (Tailscale from outside, say) makes the stream less smooth but does not
  slow the game.
- **Save states** need more than Emulate does, because freezing a running
  game and bringing it back is something a container is not allowed by
  default. Add `--cap-add SYS_ADMIN --cap-add SYS_PTRACE --cap-add NET_ADMIN
  --cap-add SYS_TIME --security-opt seccomp=unconfined --security-opt
  systempaths=unconfined` to the line above (the unconfined seccomp takes
  the place of `pad-seccomp.json`), or run the container `--privileged`.
  The freeze needs `SYS_ADMIN` even though Emulate alone no longer does.
  Each Start checks by freezing and thawing a small test program; without
  these every game still runs, the playfield shows no Save or Load buttons,
  and the log says what was missing. Docker Desktop cannot give them at all.
- **Writing to an SD card** needs the card reader on the server. Building a
  card image into `/data` and flashing it from the PC you sit at works
  anywhere.
- **Closing the app** starts it again a moment later, so the container is
  always ready to connect to.
