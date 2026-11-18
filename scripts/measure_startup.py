"""
Measure real start-up cost and idle footprint.

Each sample runs in a fresh interpreter, so module import time is included and
no warm caches from a previous run leak in.  Results are medians of N samples.

Run:  python scripts/measure_startup.py [samples]
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = r"""
import json, time
start = time.perf_counter()
import customtkinter, psutil
from src.gui.app import App
constructed = time.perf_counter()
app = App()
app.update()
ready = time.perf_counter()

# Let the scheduled first sample and the event loop settle before sampling.
for _ in range(40):
    app.update()
    time.sleep(0.01)

process = psutil.Process()
rss = process.memory_info().rss / (1024 * 1024)
threads = process.num_threads()
cpu = process.cpu_percent(interval=3.0)

pages = len(app._pages)
app.quit()
app.destroy()

print(json.dumps({
    "import_and_construct": constructed - start,
    "window_ready": ready - start,
    "rss_mb": round(rss, 1),
    "threads": threads,
    "idle_cpu": round(cpu, 2),
    "pages_at_ready": pages,
}))
"""


def main() -> int:
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    results = []
    for index in range(samples):
        completed = subprocess.run(
            [sys.executable, "-c", CHILD],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            print(completed.stdout)
            print(completed.stderr)
            return 1
        data = json.loads(completed.stdout.strip().splitlines()[-1])
        results.append(data)
        print(f"sample {index + 1}: {data}")

    def median(key: str) -> float:
        return round(statistics.median(item[key] for item in results), 3)

    print("-" * 58)
    print(f"median import + construct : {median('import_and_construct'):.3f} s")
    print(f"median window ready      : {median('window_ready'):.3f} s")
    print(f"median RSS at ready      : {median('rss_mb'):.1f} MB")
    print(f"median idle CPU (3 s)    : {median('idle_cpu'):.2f} %")
    print(f"threads                  : {int(median('threads'))}")
    print(f"pages built at ready     : {int(median('pages_at_ready'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
