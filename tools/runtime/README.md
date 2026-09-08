# The PAD Runtime

The Linux the emulator runs on, built by us instead of borrowed from the user.

**Why** is in the [`Dockerfile`](Dockerfile)'s header and in
[`pinball_decryptor/core/runtime.py`](../../pinball_decryptor/core/runtime.py);
this file is the operational quick-start. The one-line version: every field
break the emulator has had came out of running on a machine's own distro —
its glibc, its python, its package names — and none of them was reproducible
on the machine that could fix it.

## What it is

A rootfs tarball, built in CI from a base image pinned by **digest** with
packages installed from a **snapshot** of the Ubuntu archive, exported and
pinned by SHA-256. The app downloads it, verifies it, and imports it as a
private WSL distro called `PAD-Runtime`. The user's own distro is not touched,
not read and not required — and a Windows PC with WSL enabled but no distro at
all can run the emulator.

The two binaries we build ourselves (`qemu-arm`, `s1hwshim`) are **baked in**,
taken from the payloads release and verified against the hashes the app carries
— so there is one build of the emulator in the world, not two.

## Building one

Never by hand for a release: run the workflow, which builds, self-tests,
publishes to an immutable `runtime-N` tag and prints the pin to paste into
`core/runtime.py`.

```bash
gh workflow run runtime.yml -f tag=runtime-2 -f variant=base -f publish=true
```

Locally, to try a change before spending a CI run (needs the payload binaries
in `payload/`, which the workflow otherwise fetches):

```bash
docker build tools/runtime -t pad-runtime:dev
CID=$(docker create pad-runtime:dev)
docker export "$CID" | gzip -9 > pad-runtime-base.tar.gz
docker rm "$CID"
```

## Installing, inspecting and removing one

The app does all of this from **Fix setup** on the Emulate tab, with no
terminal. By hand, from Windows:

```powershell
wsl --import PAD-Runtime "$env:LOCALAPPDATA\pinball_decryptor\runtime" pad-runtime-base.tar.gz --version 2
wsl -d PAD-Runtime -e cat /etc/pad-runtime.json      # what this runtime is
wsl -d PAD-Runtime -e cat /etc/pad-runtime.packages  # every package + version
wsl --unregister PAD-Runtime                         # remove it completely
```

`PAD_RUNTIME=0` in the app's environment sends every rig back to the machine's
default distro without uninstalling anything — the escape hatch for a machine
where the runtime is installed but suspect.

## What is in it, and what is not

The `base` variant carries what the **Spike 1** rig uses: python3, procps,
util-linux, socat, a uid-1000 account (the rig looks its user up by number),
and the emulator binaries. No `fuse3` — the device model links libfuse
statically and talks to `/dev/fuse` directly.

The **Spike 2** rig is deliberately *not* on it yet: it wants another ~400 MB
of toolchain (`qemu-user-static`, an ARM cross compiler, `ffmpeg`, `criu`), and
it is the rig in daily use, so moving it onto a new distro is its own pass with
its own proof. Until then it keeps using the machine's default distro. Which
rigs are routed here is decided in one place — `RIGS` in `core/runtime.py` —
and adding one there is a promise that the image can actually run it.
