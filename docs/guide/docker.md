# Running it in Docker, over VNC

[← Back to Installing](install.md)

The app can run on a server (Unraid, a NAS, any Linux box with Docker) and
be used from any PC through VNC or a web browser. It sees the server's own
drives, so card images and projects never leave it, and every PC you
connect from shares one install, one set of settings and the same projects.

The image is the Linux release on a virtual screen with every
manufacturer's tools installed. You connect with:

- **a browser** at `http://<server>:6080/` (noVNC, nothing to install), or
- **any VNC viewer** at `<server>:5900`.

## Build it

From a copy of this repository:

```bash
docker build -f installer/docker/Dockerfile -t pinball-asset-decryptor installer
```

It takes the newest release. `--build-arg PAD_VERSION=v1.289.0` picks
another. The app's own update check is off in the container: building the
image again is how it updates.

## Run it

```bash
docker run -d --name pinball-asset-decryptor --privileged \
  -p 6080:6080 -p 5900:5900 \
  -e VNC_PASSWORD=choose-one \
  -v /mnt/user/appdata/pinball-asset-decryptor:/config \
  -v /mnt/user/pinball:/data \
  pinball-asset-decryptor
```

| Setting | What it is |
|---|---|
| `/config` | The app's home: settings, the log, and the Stern emulator's working files. Give it room: Emulate keeps a copy of each card it runs here (about 5 GB for a Spike 2 card). |
| `/data` | Your game files and projects. Browse to them under `/data` in the app. |
| `6080` | The screen in a browser (noVNC). |
| `5900` | The screen for a VNC viewer. |
| `VNC_PASSWORD` | Asked for by both. Leave it out and anyone who can reach the ports can use the app. |
| `PUID` / `PGID` | Who the files the app writes belong to. Default `99` / `100`, Unraid's `nobody:users`. |
| `RESOLUTION` | The virtual screen. Default `1600x900`. |
| `TZ` | Time zone for the log, e.g. `America/Chicago`. |

On Unraid, add a container with these as its paths, ports and variables
and switch **Privileged** on.

### Why privileged

Only Stern Emulate needs it:

- The game is a 32-bit ARM program, run through qemu once qemu is
  registered with the server's kernel. The container registers it at start
  if the server has not, and it stays registered until the server restarts.
- Save states (freeze and thaw a running game) need kernel features a
  normal container is denied.

Everything else (extracting, replacing, building cards, every other
manufacturer) works without `--privileged`. Leave it off and the Emulate
tab says what is missing.

## What to expect

- **Emulators run on the server.** Their speed is the server's CPU, not the
  network. Only the picture travels, so a slow link (Tailscale from outside,
  say) makes the screen update less smoothly but does not slow the game.
- **No sound.** VNC carries the picture only. Tick **Mute** on the Emulate
  tab.
- **No GPU.** The screen is drawn in software. The emulators' game windows
  work this way too, just with more CPU.
- **Writing to an SD card** needs the card reader on the server. Building a
  card image into `/data` and flashing it from the PC you sit at works
  anywhere.
- **Closing the app** starts it again a moment later, so the container is
  always ready to connect to.
