"""
Spotify process management.

Safely detects and stops Spotify processes before file modifications.
Never touches unrelated processes.
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
    "spotifycrashandler.exe",
}


@dataclass
class ProcessSnapshot:
    pid: int
    name: str
    memory_mb: float
    cpu_percent: float
    status: str


def get_spotify_processes() -> list[psutil.Process]:
    """Return all running Spotify-related processes."""
    found: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() in SPOTIFY_PROCESS_NAMES:
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return found


def get_process_snapshot(proc: psutil.Process) -> Optional[ProcessSnapshot]:
    """Get a memory/CPU snapshot for a process, returns None if unavailable."""
    try:
        with proc.oneshot():
            mem = proc.memory_info().rss / (1024 * 1024)
            try:
                cpu = proc.cpu_percent(interval=0)
            except Exception:
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


def get_total_spotify_memory_mb() -> float:
    """Return combined RSS memory of all Spotify processes in MB."""
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

    Returns (success, message).
    Does NOT touch any non-Spotify processes.
    """
    processes = get_spotify_processes()
    if not processes:
        return True, "Spotify is not running."

    log.info(f"Stopping {len(processes)} Spotify process(es)...")

    # Graceful terminate first
    for proc in processes:
        try:
            log.debug(f"Terminating PID {proc.pid} ({proc.name()})")
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log.warning(f"Could not terminate PID {proc.pid}: {e}")

    # Wait for graceful exit
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        still_alive = get_spotify_processes()
        if not still_alive:
            log.info("All Spotify processes stopped.")
            return True, "Spotify stopped successfully."
        time.sleep(0.5)

    # Force kill remaining
    remaining = get_spotify_processes()
    for proc in remaining:
        try:
            log.warning(f"Force-killing PID {proc.pid}")
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log.warning(f"Could not kill PID {proc.pid}: {e}")

    time.sleep(2.0)
    still_remaining = get_spotify_processes()
    if still_remaining:
        pids = [str(p.pid) for p in still_remaining]
        msg = f"Could not stop Spotify processes: PIDs {', '.join(pids)}"
        log.error(msg)
        return False, msg

    log.info("Spotify force-stopped.")
    return True, "Spotify force-stopped."


def wait_for_spotify_exit(timeout: float = 10.0) -> bool:
    """
    Wait for Spotify to exit on its own.
    Returns True if exited within timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_spotify_running():
            return True
        time.sleep(0.3)
    return False
