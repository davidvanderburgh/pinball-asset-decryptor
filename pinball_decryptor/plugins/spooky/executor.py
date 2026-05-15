"""Platform-aware command execution — WSL (Windows), native (Linux), Docker (macOS).

Clonezilla extraction requires Linux tools (partclone, debugfs) that aren't
available natively on Windows or macOS.  This module provides a unified
interface to run those commands on all three platforms:

- Windows: WSL2 (existing behavior, unchanged)
- macOS: Docker Desktop with a lightweight Alpine container
- Linux: Native execution (sudo or root)
"""

import os
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

# Docker image/container names
_DOCKER_IMAGE = "spooky-decryptor"
_DOCKER_CONTAINER = "spooky-decryptor-worker"


def _decode_output(data):
    """Decode subprocess output bytes, handling UTF-16LE from wsl.exe."""
    if not data:
        return ""
    # wsl.exe outputs UTF-16LE — detect by checking for null bytes
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
        """Run a bash command and return stdout. Raises CommandError on failure."""
        raise NotImplementedError

    def stream(self, bash_cmd, timeout=600):
        """Run a bash command and yield output lines as they arrive."""
        raise NotImplementedError

    def to_exec_path(self, host_path):
        """Convert a host filesystem path to a path visible inside the executor."""
        raise NotImplementedError

    def host_tmp_dir(self):
        """Return a host-side temp directory whose files are visible to the executor."""
        import tempfile
        return tempfile.gettempdir()

    def kill(self):
        """Kill the currently running streaming process (for cancellation)."""
        with self._lock:
            if self._current_proc:
                try:
                    self._current_proc.terminate()
                except OSError:
                    pass

    def check_available(self):
        """Check if this executor backend is available. Returns (bool, message)."""
        raise NotImplementedError

    def check_path_accessible(self, host_path):
        """Verify a host path is accessible from the executor. Returns (ok, message)."""
        return True, ""

    def run_host(self, args, timeout=60):
        """Run a command on the host OS directly. Returns (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                timeout=timeout,
                shell=True,
                creationflags=_CREATE_FLAGS,
            )
            stdout = _decode_output(result.stdout)
            stderr = _decode_output(result.stderr)
            return result.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout}s"
        except FileNotFoundError:
            return -1, "", f"Command not found: {args[0] if args else '?'}"


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
            raise CommandError(bash_cmd, -1, f"Command timed out after {timeout}s") from e

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
            raise CommandError(bash_cmd, -1, f"Command timed out after {timeout}s")
        finally:
            with self._lock:
                self._current_proc = None

    def to_exec_path(self, host_path):
        """Convert a Windows path to a WSL path.

        e.g. C:\\Users\\david\\file.img -> /mnt/c/Users/david/file.img
        """
        path = host_path.replace("\\", "/")
        if len(path) >= 2 and path[1] == ":":
            drive = path[0].lower()
            return f"/mnt/{drive}{path[2:]}"
        return path

    def check_path_accessible(self, host_path):
        """Verify a Windows path is accessible from WSL.

        WSL2 only automounts drives present at WSL startup.
        """
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
                f"WSL only sees drives that were connected when WSL started.  "
                f"If {letter}: is a USB or external drive that was plugged in "
                f"after booting, WSL cannot write to it.\n\n"
                f"Fix: run  wsl --shutdown  in a Windows terminal, then try "
                f"again (WSL will restart and detect the drive).\n"
                f"Alternatively, use a folder on C: or another internal drive."
            )
        return True, ""

    def check_available(self):
        try:
            self.run("echo ok", timeout=15)
            return True, "WSL2 available"
        except Exception:
            return False, "WSL2 not available. Install from Microsoft Store."


class NativeExecutor(CommandExecutor):
    """Execute commands natively on Linux using sudo (or directly as root)."""

    def _cmd_prefix(self):
        """Use sudo unless already running as root (e.g. inside Docker)."""
        if hasattr(os, "getuid") and os.getuid() == 0:
            return ["bash", "-c"]
        return ["sudo", "bash", "-c"]

    def run(self, bash_cmd, timeout=120):
        full_cmd = [*self._cmd_prefix(), bash_cmd]
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
            raise CommandError(bash_cmd, -1, f"Command timed out after {timeout}s") from e

        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            raise CommandError(bash_cmd, result.returncode, output.strip())

        return result.stdout

    def stream(self, bash_cmd, timeout=600):
        full_cmd = [*self._cmd_prefix(), bash_cmd]
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
            raise CommandError(bash_cmd, -1, f"Command timed out after {timeout}s")
        finally:
            with self._lock:
                self._current_proc = None

    def to_exec_path(self, host_path):
        """No conversion needed on Linux — paths are native."""
        return host_path

    def check_available(self):
        try:
            self.run("echo ok", timeout=15)
            return True, "Native Linux available"
        except Exception:
            return False, "sudo not available. Run as root or configure sudo."


class DockerExecutor(CommandExecutor):
    """Execute commands inside a Docker container (macOS).

    Uses a privileged Alpine container with bind mounts for host paths.
    The container is started on demand and stopped during cleanup.
    """

    def __init__(self):
        super().__init__()
        self._container_running = False
        self._host_mounts = []

    def _dockerfile_path(self):
        """Find the bundled Dockerfile."""
        # Check inside the package directory first
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        df = os.path.join(pkg_dir, "Dockerfile")
        if os.path.isfile(df):
            return df
        # Check in .app bundle Resources (macOS PyInstaller)
        resources = os.path.join(pkg_dir, "..", "Resources", "Dockerfile")
        if os.path.isfile(resources):
            return resources
        return df  # fall back — will fail with clear error

    def _cache_dir(self):
        """Return the host-side cache directory for temp files."""
        base = os.path.expanduser("~/.cache/spooky_decryptor/tmp")
        os.makedirs(base, exist_ok=True)
        return base

    def host_tmp_dir(self):
        """Return the cache dir that's bind-mounted as /tmp in the container."""
        return self._cache_dir()

    def _ensure_image(self):
        """Build the Docker image if it doesn't exist."""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", _DOCKER_IMAGE],
                capture_output=True, timeout=15,
            )
            if result.returncode == 0:
                return  # Image exists
        except Exception:
            pass

        dockerfile = self._dockerfile_path()
        if not os.path.isfile(dockerfile):
            raise CommandError("docker build", -1,
                f"Dockerfile not found at {dockerfile}")

        build_dir = os.path.dirname(dockerfile)
        try:
            result = subprocess.run(
                ["docker", "build", "-t", _DOCKER_IMAGE, "-f", dockerfile, build_dir],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            if result.returncode != 0:
                raise CommandError("docker build", result.returncode,
                    result.stderr or result.stdout or "")
        except subprocess.TimeoutExpired as e:
            raise CommandError("docker build", -1,
                "Docker image build timed out") from e

    def start_container(self, host_paths=None):
        """Start the privileged Docker container with bind mounts.

        Args:
            host_paths: list of host directories/files to mount under /host/
        """
        if self._container_running:
            return

        self._ensure_image()

        # Stop any leftover container
        subprocess.run(
            ["docker", "rm", "-f", _DOCKER_CONTAINER],
            capture_output=True, timeout=15,
        )

        mount_args = []
        cache_dir = self._cache_dir()
        mount_args.extend(["-v", f"{cache_dir}:/tmp"])

        if host_paths:
            for hp in host_paths:
                hp = os.path.abspath(hp)
                mount_args.extend(["-v", f"{hp}:/host{hp}"])
                self._host_mounts.append(hp)

        cmd = [
            "docker", "run", "-d",
            "--name", _DOCKER_CONTAINER,
            "--privileged",
            *mount_args,
            _DOCKER_IMAGE,
            "sleep", "infinity",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                raise CommandError("docker run", result.returncode,
                    result.stderr or result.stdout or "")
            self._container_running = True
        except subprocess.TimeoutExpired as e:
            raise CommandError("docker run", -1,
                "Container start timed out") from e

    def stop_container(self):
        """Stop and remove the Docker container."""
        if not self._container_running:
            return
        try:
            subprocess.run(
                ["docker", "rm", "-f", _DOCKER_CONTAINER],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass
        self._container_running = False
        self._host_mounts.clear()

    def run(self, bash_cmd, timeout=120):
        if not self._container_running:
            raise CommandError(bash_cmd, -1,
                "Docker container not running. Call start_container() first.")

        full_cmd = [
            "docker", "exec", _DOCKER_CONTAINER,
            "bash", "-c", bash_cmd,
        ]
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
            raise CommandError(bash_cmd, -1, f"Command timed out after {timeout}s") from e

        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            raise CommandError(bash_cmd, result.returncode, output.strip())

        return result.stdout

    def stream(self, bash_cmd, timeout=600):
        if not self._container_running:
            raise CommandError(bash_cmd, -1,
                "Docker container not running. Call start_container() first.")

        full_cmd = [
            "docker", "exec", _DOCKER_CONTAINER,
            "bash", "-c", bash_cmd,
        ]
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
            raise CommandError(bash_cmd, -1, f"Command timed out after {timeout}s")
        finally:
            with self._lock:
                self._current_proc = None

    def to_exec_path(self, host_path):
        """Convert a macOS host path to a container path.

        e.g. /Users/david/file.img -> /host/Users/david/file.img
        Cache dir files map to /tmp/ (bind-mounted in start_container).
        """
        path = os.path.abspath(host_path)
        cache = self._cache_dir()
        if path.startswith(cache + os.sep) or path == cache:
            rel = os.path.relpath(path, cache)
            return f"/tmp/{rel}" if rel != "." else "/tmp"
        return f"/host{path}"

    def check_available(self):
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, timeout=15,
            )
            if result.returncode == 0:
                return True, "Docker Desktop available"
            return False, "Docker Desktop not running. Start Docker Desktop."
        except FileNotFoundError:
            return False, "Docker not installed. Install Docker Desktop."
        except Exception:
            return False, "Docker check failed."


def create_executor():
    """Create the appropriate CommandExecutor for the current platform."""
    if sys.platform == "win32":
        return WslExecutor()
    elif sys.platform == "darwin":
        return DockerExecutor()
    else:
        # Linux and other Unix-like
        return NativeExecutor()
