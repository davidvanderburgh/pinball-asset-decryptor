"""Platform-aware command execution for native-tool pipelines (Clonezilla,
GPG verification, etc.).

- Windows → WSL2 (Ubuntu) via ``wsl -u root -- bash -c``
- macOS   → native bash, with Homebrew paths prepended
- Linux   → native bash (sudo if not running as root)
"""

import os
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

    def to_exec_path(self, host_path):
        path = host_path.replace("\\", "/")
        if len(path) >= 2 and path[1] == ":":
            return f"/mnt/{path[0].lower()}{path[2:]}"
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
