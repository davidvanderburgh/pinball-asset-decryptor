"""Platform-aware command execution for native-tool pipelines (Clonezilla,
GPG verification, etc.).

- Windows → WSL2 (Ubuntu) via ``wsl -u root -- bash -c``
- macOS   → native bash, with Homebrew paths prepended
- Linux   → native bash (sudo if not running as root)
"""

import hashlib
import os
import re
import subprocess
import sys
import threading

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class CommandError(Exception):
    def __init__(self, cmd, returncode, output):
        self.cmd = cmd
        self.returncode = returncode
        self.output = output
        super().__init__(f"Command failed (exit {returncode}): {cmd}\n{output}")


class CommandExecutor:
    def __init__(self):
        self._current_proc = None
        self._lock = threading.Lock()

    def run(self, bash_cmd, timeout=120):
        raise NotImplementedError

    def stream(self, bash_cmd, timeout=600):
        raise NotImplementedError

    def popen_binary(self, bash_cmd):
        """Start *bash_cmd* and return a Popen with a **binary** stdout pipe.

        Used to stream large data out of the executor environment (e.g.
        ``cat`` a partclone image or ``tar`` an asset tree) without staging
        it on the slow Windows drvfs mount.  Caller must read stdout to
        completion and then ``wait()``.
        """
        raise NotImplementedError

    def to_exec_path(self, host_path):
        raise NotImplementedError

    def kill(self):
        with self._lock:
            if self._current_proc:
                try:
                    self._current_proc.terminate()
                except OSError:
                    pass

    def check_available(self):
        raise NotImplementedError


class WslExecutor(CommandExecutor):
    def run(self, bash_cmd, timeout=120):
        full_cmd = ["wsl", "-u", "root", "--", "bash", "-c", bash_cmd]
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout, creationflags=_CREATE_FLAGS,
            )
        except subprocess.TimeoutExpired as e:
            raise CommandError(bash_cmd, -1, f"Timed out after {timeout}s") from e
        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            raise CommandError(bash_cmd, result.returncode, output.strip())
        return result.stdout

    def stream(self, bash_cmd, timeout=600):
        full_cmd = ["wsl", "-u", "root", "--", "bash", "-c", bash_cmd]
        proc = subprocess.Popen(
            full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_CREATE_FLAGS,
        )
        with self._lock:
            self._current_proc = proc
        try:
            for line in proc.stdout:
                yield line.rstrip("\n\r")
            proc.wait(timeout=timeout)
            if proc.returncode != 0:
                raise CommandError(bash_cmd, proc.returncode, "")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise CommandError(bash_cmd, -1, f"Timed out after {timeout}s")
        finally:
            with self._lock:
                self._current_proc = None

    def popen_binary(self, bash_cmd):
        full_cmd = ["wsl", "-u", "root", "--", "bash", "-c", bash_cmd]
        return subprocess.Popen(
            full_cmd, stdout=subprocess.PIPE, creationflags=_CREATE_FLAGS)

    # UNC network shares (\\server\share\...) are never automounted by WSL —
    # they must be drvfs-mounted explicitly.  Mounted shares are tracked at
    # class level so every pipeline in the process reuses the same mounts.
    _unc_lock = threading.Lock()
    _unc_mounts = {}   # (server, share) lowercased -> WSL mount point

    @staticmethod
    def _unc_mount_name(name):
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name).lower()
        if safe != name.lower():
            # Disambiguate names that could collide after sanitization
            safe += "-" + hashlib.md5(name.lower().encode("utf-8")).hexdigest()[:6]
        return safe

    def _unc_exec_path(self, path):
        """Map //server/share/rest to an on-demand drvfs mount inside WSL."""
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return path  # bare //server with no share — let callers fail loudly
        server, share = parts[0], parts[1]
        # drvfs accepts the //server/share form, which — unlike backslashes —
        # survives the extra bash parse wsl.exe applies to `wsl -- bash -c`.
        unc_src = f"//{server}/{share}"
        unc_label = f"\\\\{server}\\{share}"
        if "'" in unc_src:
            raise CommandError("mount -t drvfs", -1,
                               f"Unsupported network share name: {unc_label}")
        key = (server.lower(), share.lower())
        with self._unc_lock:
            mount_point = self._unc_mounts.get(key)
            if mount_point is None:
                mount_point = (f"/mnt/unc/{self._unc_mount_name(server)}/"
                               f"{self._unc_mount_name(share)}")
                try:
                    self.run(
                        f"findmnt -n '{mount_point}' >/dev/null 2>&1 || "
                        f"{{ mkdir -p '{mount_point}' && "
                        f"mount -t drvfs '{unc_src}' '{mount_point}'; }}",
                        timeout=60,
                    )
                except CommandError as e:
                    raise CommandError(e.cmd, e.returncode, (
                        f"Cannot access network share {unc_label} from WSL:\n"
                        f"{e.output}\n\n"
                        f"Check that the share opens in File Explorer, or copy "
                        f"the file to a local drive and try again.")) from e
                self._unc_mounts[key] = mount_point
        rest = "/".join(parts[2:])
        return f"{mount_point}/{rest}" if rest else mount_point

    def to_exec_path(self, host_path):
        path = host_path.replace("\\", "/")
        if len(path) >= 2 and path[1] == ":":
            return f"/mnt/{path[0].lower()}{path[2:]}"
        if path.startswith("//"):
            return self._unc_exec_path(path)
        return path

    def check_available(self):
        try:
            self.run("echo ok", timeout=15)
            return True, "WSL2 available"
        except Exception:
            return False, "WSL2 not available. Install via: wsl --install -d Ubuntu"


class NativeExecutor(CommandExecutor):
    def _prefix(self):
        if hasattr(os, "getuid") and os.getuid() == 0:
            return ["bash", "-c"]
        return ["sudo", "bash", "-c"]

    def run(self, bash_cmd, timeout=120):
        full_cmd = [*self._prefix(), bash_cmd]
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise CommandError(bash_cmd, -1, f"Timed out after {timeout}s") from e
        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            raise CommandError(bash_cmd, result.returncode, output.strip())
        return result.stdout

    def stream(self, bash_cmd, timeout=600):
        full_cmd = [*self._prefix(), bash_cmd]
        proc = subprocess.Popen(
            full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        with self._lock:
            self._current_proc = proc
        try:
            for line in proc.stdout:
                yield line.rstrip("\n\r")
            proc.wait(timeout=timeout)
            if proc.returncode != 0:
                raise CommandError(bash_cmd, proc.returncode, "")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise CommandError(bash_cmd, -1, f"Timed out after {timeout}s")
        finally:
            with self._lock:
                self._current_proc = None

    def popen_binary(self, bash_cmd):
        return subprocess.Popen([*self._prefix(), bash_cmd],
                                stdout=subprocess.PIPE)

    def to_exec_path(self, host_path):
        return host_path

    def check_available(self):
        return True, "Native Linux"


class MacExecutor(CommandExecutor):
    _EXTRA_PATH = "/opt/homebrew/bin:/usr/local/bin:/opt/local/bin"

    def _wrap(self, bash_cmd):
        return f'export PATH="{self._EXTRA_PATH}:$PATH" && {bash_cmd}'

    def _env(self):
        env = os.environ.copy()
        env["PATH"] = self._EXTRA_PATH + os.pathsep + env.get("PATH", "")
        return env

    def run(self, bash_cmd, timeout=120):
        full_cmd = ["bash", "-c", self._wrap(bash_cmd)]
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout, env=self._env(),
            )
        except subprocess.TimeoutExpired as e:
            raise CommandError(bash_cmd, -1, f"Timed out after {timeout}s") from e
        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            raise CommandError(bash_cmd, result.returncode, output.strip())
        return result.stdout

    def stream(self, bash_cmd, timeout=600):
        full_cmd = ["bash", "-c", self._wrap(bash_cmd)]
        proc = subprocess.Popen(
            full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=self._env(),
        )
        with self._lock:
            self._current_proc = proc
        try:
            for line in proc.stdout:
                yield line.rstrip("\n\r")
            proc.wait(timeout=timeout)
            if proc.returncode != 0:
                raise CommandError(bash_cmd, proc.returncode, "")
        except subprocess.TimeoutExpired:
            proc.kill()
            raise CommandError(bash_cmd, -1, f"Timed out after {timeout}s")
        finally:
            with self._lock:
                self._current_proc = None

    def popen_binary(self, bash_cmd):
        return subprocess.Popen(["bash", "-c", self._wrap(bash_cmd)],
                                stdout=subprocess.PIPE, env=self._env())

    def to_exec_path(self, host_path):
        return host_path

    def check_available(self):
        return True, "macOS native"


def create_executor():
    if sys.platform == "win32":
        return WslExecutor()
    if sys.platform == "darwin":
        return MacExecutor()
    return NativeExecutor()
