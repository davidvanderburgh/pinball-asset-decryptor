"""Platform-aware command execution — WSL (Windows), native (Linux), or macOS."""

import os
import shutil
import subprocess
import sys
import threading

# Prevent console windows from flashing when launched via pythonw.exe on Windows
_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Ensure common tool locations are on PATH (PyInstaller bundles get a minimal PATH)
if sys.platform == "darwin":
    _extra = ["/usr/local/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin"]
    _path = os.environ.get("PATH", "")
    _missing = [p for p in _extra if p not in _path.split(os.pathsep)]
    if _missing:
        os.environ["PATH"] = os.pathsep.join([_path] + _missing)


def _decode_output(data):
    """Decode subprocess output bytes, handling UTF-16LE from wsl.exe."""
    if not data:
        return ""
    if b"\x00" in data[:64]:
        try:
            return data.decode("utf-16-le").strip()
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace").strip()


class CommandError(Exception):
    """Raised when a command execution fails."""
    def __init__(self, cmd, returncode, output):
        self.cmd = cmd
        self.returncode = returncode
        self.output = output
        super().__init__(f"Command failed (exit {returncode}): {cmd}\n{output}")


class CommandExecutor:
    """Base class for platform-specific command execution."""

    def __init__(self):
        self._current_proc = None
        self._lock = threading.Lock()

    def run(self, bash_cmd, timeout=120):
        raise NotImplementedError

    def stream(self, bash_cmd, timeout=600):
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

    def check_path_accessible(self, host_path):
        return True, ""

    def run_host(self, args, timeout=60):
        """Run a command on the host OS. Returns (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                timeout=timeout,
                shell=True,
                creationflags=_CREATE_FLAGS,
            )
            return (result.returncode,
                    _decode_output(result.stdout),
                    _decode_output(result.stderr))
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout}s"
        except FileNotFoundError:
            return -1, "", f"Command not found"


class WslExecutor(CommandExecutor):
    """Execute commands in WSL2 via subprocess (Windows)."""

    def run(self, bash_cmd, timeout=120):
        full_cmd = ["wsl", "-u", "root", "--", "bash", "-c", bash_cmd]
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=_CREATE_FLAGS,
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
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
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

    def to_exec_path(self, host_path):
        """Convert a Windows path to a WSL path."""
        path = host_path.replace("\\", "/")
        if len(path) >= 2 and path[1] == ":":
            drive = path[0].lower()
            return f"/mnt/{drive}{path[2:]}"
        return path

    def check_path_accessible(self, host_path):
        path = host_path.replace("\\", "/")
        if len(path) < 2 or path[1] != ":":
            return True, ""
        drive = path[0].lower()
        mount_point = f"/mnt/{drive}"
        try:
            out = self.run(
                f"findmnt -n -o FSTYPE '{mount_point}' 2>/dev/null",
                timeout=10,
            ).strip()
        except CommandError:
            out = ""
        if not out:
            letter = drive.upper()
            return False, (
                f"Drive {letter}: is not accessible from WSL.\n\n"
                f"If {letter}: is an external drive plugged in after WSL started, "
                f"run  wsl --shutdown  in a Windows terminal, then try again."
            )
        return True, ""

    def check_available(self):
        try:
            self.run("echo ok", timeout=15)
            return True, "WSL2 available"
        except Exception:
            return False, "WSL2 not available. Install from Microsoft Store."


class NativeExecutor(CommandExecutor):
    """Execute commands natively on Linux."""

    def _prefix(self):
        if hasattr(os, "getuid") and os.getuid() == 0:
            return ["bash", "-c"]
        return ["sudo", "bash", "-c"]

    def run(self, bash_cmd, timeout=120):
        full_cmd = [*self._prefix(), bash_cmd]
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
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
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
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

    def to_exec_path(self, host_path):
        return host_path

    def check_available(self):
        return True, "Native Linux"


class MacExecutor(CommandExecutor):
    """Execute commands natively on macOS (no sudo needed for file operations)."""

    # Homebrew (Apple Silicon + Intel) and MacPorts paths — ensures tools like
    # gpg are found even when the login shell is zsh and bash -l doesn't pick
    # up the user's PATH additions.
    _EXTRA_PATH = "/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:/usr/local/MacGPG2/bin"

    def _wrap(self, bash_cmd):
        """Prepend Homebrew/MacPorts paths to PATH inside the shell command."""
        return f'export PATH="{self._EXTRA_PATH}:$PATH" && {bash_cmd}'

    def run(self, bash_cmd, timeout=120):
        full_cmd = ["bash", "-c", self._wrap(bash_cmd)]
        env = self._env()
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise CommandError(bash_cmd, -1, f"Timed out after {timeout}s") from e
        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            raise CommandError(bash_cmd, result.returncode, output.strip())
        return result.stdout

    def _env(self):
        env = os.environ.copy()
        env["PATH"] = self._EXTRA_PATH + os.pathsep + env.get("PATH", "")
        return env

    def stream(self, bash_cmd, timeout=600):
        full_cmd = ["bash", "-c", self._wrap(bash_cmd)]
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
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

    def to_exec_path(self, host_path):
        return host_path

    def check_available(self):
        return True, "macOS native"


def create_executor():
    """Return the appropriate executor for the current platform."""
    if sys.platform == "win32":
        return WslExecutor()
    elif sys.platform == "darwin":
        return MacExecutor()
    return NativeExecutor()
