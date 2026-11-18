"""
Spotify process management.

Safely detects and stops Spotify processes before file modifications.
Never touches unrelated processes: only executables whose name is on a short
allow-list are ever enumerated, and termination is restricted to exactly those
processes.

Process names are matched case-insensitively against a fixed allow-list so a
process called ``spotify.exe`` launched from an unexpected directory is still
recognised as Spotify, while unrelated processes are never matched by
wildcards.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import psutil

from .logger import get_logger

log = get_logger("process")

SPOTIFY_PROCESS_NAMES = {
    "spotify.exe",
    "spotifywebhelper.exe",
    "spotifycrashhandler.exe",
    "spotifycrashandler.exe",  # historical misspelling used by some builds
}


@dataclass
class ProcessSnapshot:
    pid: int
    name: str
    memory_mb: float
    cpu_percent: float
    status: str


@dataclass
class ProcessDetails:
    pid: int
    name: str
    memory_mb: float
    cpu_percent: float
    status: str
    create_time: Optional[float]
    parent_pid: Optional[int]
    exe: Optional[str]
    is_spotify: bool

    def start_time_text(self) -> str:
        if not self.create_time:
            return "unknown"
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.create_time))
        except (OSError, ValueError):
            return "unknown"


def get_spotify_processes() -> list[psutil.Process]:
    """Return all running Spotify-related processes."""
    found: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name")
            if name and name.lower() in SPOTIFY_PROCESS_NAMES:
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return found


def get_process_snapshot(proc: psutil.Process) -> Optional[ProcessSnapshot]:
    """Get a memory/CPU snapshot for a process, ``None`` if unavailable."""
    try:
        with proc.oneshot():
            mem = proc.memory_info().rss / (1024 * 1024)
            try:
                cpu = proc.cpu_percent(None)
            except (psutil.Error, OSError):
                cpu = 0.0
            return ProcessSnapshot(
                pid=proc.pid,
                name=proc.name(),
                memory_mb=round(mem, 2),
                cpu_percent=round(cpu, 2),
                status=proc.status(),
            )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def get_process_details() -> list[ProcessDetails]:
    """
    Detailed view of the Spotify process tree for the Process Monitor page.

    Only Spotify executables are included; ``parent_pid`` is reported when the
    parent is another Spotify process, otherwise ``None`` so the UI never
    implies an unrelated process is part of Spotify.
    """
    spotify_pids: dict[int, psutil.Process] = {}
    for proc in get_spotify_processes():
        spotify_pids[proc.pid] = proc

    details: list[ProcessDetails] = []
    for pid, proc in spotify_pids.items():
        try:
            with proc.oneshot():
                memory = proc.memory_info().rss / (1024 * 1024)
                try:
                    cpu = proc.cpu_percent(None)
                except (psutil.Error, OSError):
                    cpu = 0.0
                try:
                    parent = proc.ppid()
                except (psutil.Error, OSError):
                    parent = None
                try:
                    create_time = proc.create_time()
                except (psutil.Error, OSError):
                    create_time = None
                try:
                    exe = proc.exe()
                except (psutil.Error, OSError):
                    exe = None
                details.append(ProcessDetails(
                    pid=pid,
                    name=proc.name(),
                    memory_mb=round(memory, 2),
                    cpu_percent=round(cpu, 2),
                    status=proc.status(),
                    create_time=create_time,
                    parent_pid=parent if parent in spotify_pids else None,
                    exe=exe,
                    is_spotify=True,
                ))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(details, key=lambda item: item.pid)


def prime_cpu_counters() -> None:
    """Prime per-process CPU counters so the next read is a real delta."""
    for proc in get_spotify_processes():
        try:
            proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def get_total_spotify_memory_mb() -> float:
    """Combined RSS memory of all Spotify processes in MB."""
    total = 0.0
    for proc in get_spotify_processes():
        snap = get_process_snapshot(proc)
        if snap:
            total += snap.memory_mb
    return round(total, 2)


def get_spotify_process_count() -> int:
    return len(get_spotify_processes())


def is_spotify_running() -> bool:
    return len(get_spotify_processes()) > 0


def stop_spotify(timeout: float = 15.0) -> tuple[bool, str]:
    """
    Gracefully stop all Spotify processes.

    Returns ``(success, message)``.  Only processes on the Spotify allow-list
    are terminated; nothing else is touched.
    """
    processes = get_spotify_processes()
    if not processes:
        return True, "Spotify is not running."

    log.info(f"Stopping {len(processes)} Spotify process(es)…")

    for proc in processes:
        try:
            log.debug(f"Terminating PID {proc.pid} ({proc.name()})")
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            log.warning(f"Could not terminate PID {proc.pid}: {exc}")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not get_spotify_processes():
            log.info("All Spotify processes stopped.")
            return True, "Spotify stopped successfully."
        time.sleep(0.5)

    remaining = get_spotify_processes()
    for proc in remaining:
        try:
            log.warning(f"Force-killing PID {proc.pid}")
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            log.warning(f"Could not kill PID {proc.pid}: {exc}")

    time.sleep(2.0)
    still_remaining = get_spotify_processes()
    if still_remaining:
        pids = ", ".join(str(p.pid) for p in still_remaining)
        message = f"Could not stop Spotify processes: PIDs {pids}"
        log.error(message)
        return False, message

    log.info("Spotify force-stopped.")
    return True, "Spotify force-stopped."


def launch_spotify(exe_path: Path | str) -> tuple[bool, str]:
    """
    Start Spotify from a known-good executable path.

    An argument array is passed directly to the OS (no shell), so the path can
    never be interpreted as a command.
    """
    import subprocess

    path = Path(exe_path) if exe_path else None
    if path is None or not path.is_file():
        return False, "Spotify executable not found."
    try:
        subprocess.Popen([str(path)], close_fds=True)
        log.info(f"Spotify launched from {path}")
        return True, "Spotify started."
    except OSError as exc:
        log.error(f"Could not launch Spotify: {exc}")
        return False, str(exc)


def wait_for_spotify_exit(timeout: float = 10.0) -> bool:
    """Wait for Spotify to exit on its own. True if it did within timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_spotify_running():
            return True
        time.sleep(0.3)
    return False
