# Spotify RAM Optimizer - Windows acceptance report

- Generated: 2026-11-19T13:47:43.2573046+05:30
- Host: local Windows 11 x64 machine
- Windows: Microsoft Windows 11 Pro (build 26300) / AMD64
- Python: Python 3.14.7
- Repository: local checkout
- Commit: cd9bd5f (modified (uncommitted))
- Overall: **PASS**
- Fresh build performed: False

## Results

| Step | Status | Exit code | Detail |
| --- | --- | --- | --- |
| Windows host | PASS |  | Microsoft Windows 11 Pro (build 26300); AMD64 |
| Python available | PASS | 0 | Python 3.14.7 |
| Runtime and test dependencies | PASS | 0 | customtkinter 6.0.0 Pillow 13.0.0 psutil 7.2.2 pytest 9.1.1 |
| Application imports | PASS | 0 | imports ok |
| pytest tests (per-module isolation) | PASS | 0 | 313 passed, 1 skipped, 0 failed across 23 modules |
| Source smoke test | PASS | 0 | SMOKE TEST PASSED: ALL 11 CHECKS VERIFIED SUCCESSFULLY |
| Release executable | PASS |  | 34,373,370 bytes, written 2026-11-19T13:41:48.2983315+05:30 |
| SHA-256 | PASS |  | f0f8f8cf8a4650d38f95f97506cfd78977709b55c9647959c64d7dc51cf4cd12 |
| Version metadata | PASS |  | FileVersion=1.2.0.0; ProductVersion=1.2.0; Company=Icey |
| Packaged smoke test | PASS | 0 | SMOKE TEST PASSED: ALL 11 CHECKS VERIFIED SUCCESSFULLY |
| Screenshot inventory | INFO |  | 12 PNG capture(s) in docs\screenshots (12 expected for the current source) |

## Not automated by this script

A passing smoke test proves the window opens, all twelve destinations render and the
thread-safe dispatcher delivers a worker update. It does **not** replace a click-through:

- Navigate all twelve destinations and confirm sidebar highlighting and header text.
- Open Optimizations, cancel a preview, and confirm no file changed.
- Run a preview, apply it against a disposable Spotify tree, then restore it.
- Exercise the restore dialog's component selection and conflict opt-in.
- Resize to 1366x768, 1920x1080 and 2560x1440 at 100%, 125% and 150% scaling.
- Confirm Diagnostics findings expand and Privacy Center controls work.
- Verify clean shutdown (no orphaned python/SpotifyOptimizer processes).

## Safety

No test in this script writes to the developer's Spotify profile, cache or registry.
The suite redirects APPDATA/LOCALAPPDATA and mocks the registry; real system writes
must be exercised only against a disposable Windows account or VM.

