"""
Capture real screenshots of the running application.

The window is rendered by the application itself and captured through Win32
``PrintWindow`` (with an ``ImageGrab`` fallback), so an overlapping window or a
screen saver cannot produce a wrong or blank image.  If the application cannot
start, or a page renders nothing, this script fails instead of writing an image.

Run:  python scripts/capture_screenshots.py [output-directory] [--isolated]

``--isolated`` points ``SPOTIFY_OPTIMIZER_HOME`` at a temporary directory before
the application starts, so documentation captures never contain the developer's
real backup history, settings or activity log while Spotify detection still
uses the real installation.
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time
from pathlib import Path
from ctypes import wintypes

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAGES = (
    ("01_dashboard", "Dashboard"),
    ("02_optimizations", "Optimizations"),
    ("11_diagnostics", "Diagnostics"),
    ("03_performance", "Performance"),
    ("04_processes", "Processes"),
    ("05_backups", "Backups"),
    ("06_startup", "Startup"),
    ("07_installation", "Installation"),
    ("08_activity_logs", "Activity"),
    ("12_privacy_center", "Privacy"),
    ("09_settings", "Settings"),
    ("10_about", "About"),
)


def _wait(app, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.update()
        time.sleep(0.02)


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def capture_window(hwnd: int):
    """Render the window's client area into a PIL image, occluding or not."""
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    window = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(window))
    width = window.right - window.left
    height = window.bottom - window.top
    client = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(client))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    dx, dy = origin.x - window.left, origin.y - window.top

    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)
    try:
        user32.PrintWindow(hwnd, memory_dc, 2)  # PW_RENDERFULLCONTENT

        header = _BitmapInfoHeader()
        header.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.biWidth = width
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer,
                        ctypes.byref(header), 0)
        image = Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
        return image.crop((dx, dy, dx + client.right, dy + client.bottom))
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    output = Path(args[0]) if args else ROOT / "docs" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)

    if "--isolated" in sys.argv[1:]:
        base = Path(tempfile.mkdtemp(prefix="spotify_capture_"))
        os.environ["SPOTIFY_OPTIMIZER_HOME"] = str(base)
        print(f"isolated app data: {base}")

    try:
        from PIL import ImageGrab
    except ImportError:
        print("Pillow is required to capture screenshots.")
        return 2

    from src.gui.app import App

    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

    app = App()
    app.update()
    app.lift()
    app.attributes("-topmost", True)
    _wait(app, 0.4)

    # A saved configuration can switch off the automatic start-up scan. Trigger
    # the same scan the "Scan Spotify" button runs, so the images show real data.
    if app._installation is None:
        app._do_scan()
        app.update()

    deadline = time.monotonic() + 45
    while app._installation is None and time.monotonic() < deadline:
        _wait(app, 0.2)
    if app._installation is None:
        app.destroy()
        print("Detection scan did not finish; screenshots were not written.")
        return 1
    print(f"detected: {app._installation.install_type.value} "
          f"{app._installation.version or '(version unknown)'}")

    hwnd = None
    if sys.platform == "win32":
        hwnd = ctypes.windll.user32.GetAncestor(app.winfo_id(), 2)

    written: list[Path] = []
    for filename, page in PAGES:
        app.show_page(page)
        app.update()
        if page == "Activity":
            # Log lines contain real profile paths; redact them before they can
            # end up in a published screenshot.
            from src.core.app_paths import redact_path

            panel = app.log_panel
            panel.entries = [(ts, level, redact_path(message))
                             for ts, level, message in panel.entries]
            panel.render()
        _wait(app, 0.7)

        # PrintWindow can return a black frame while the first paint is still
        # being composited. Retry briefly before treating the page as blank.
        image = None
        for _attempt in range(8):
            app.update_idletasks()
            app.update()
            image = capture_window(hwnd) if hwnd else None
            if image is None:
                x, y = app.winfo_rootx(), app.winfo_rooty()
                width, height = app.winfo_width(), app.winfo_height()
                image = ImageGrab.grab(bbox=(x, y, x + width, y + height),
                                       all_screens=True)

            low, high = image.convert("L").getextrema()
            if high - low > 8:
                break
            _wait(app, 0.5)
        else:
            app.destroy()
            print(f"refused to save {filename}: the page rendered blank")
            return 1

        target = output / f"{filename}.png"
        image.save(target)
        written.append(target)
        print(f"  {target.name}  {image.size[0]}x{image.size[1]}  "
              f"{target.stat().st_size // 1024} KB")

    app.quit()
    app.destroy()

    print(f"{len(written)} screenshots written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
