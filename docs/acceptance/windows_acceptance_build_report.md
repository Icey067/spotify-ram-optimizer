# Spotify RAM Optimizer - Windows acceptance report

- Generated: 2026-11-19T13:44:27.2171910+05:30
- Host: local Windows 11 x64 machine
- Windows: Microsoft Windows 11 Pro (build 26300) / AMD64
- Python: Python 3.14.7
- Repository: local checkout
- Commit: cd9bd5f (modified (uncommitted))
- Overall: **PASS**
- Fresh build performed: True

## Results

| Step | Status | Exit code | Detail |
| --- | --- | --- | --- |
| Windows host | PASS |  | Microsoft Windows 11 Pro (build 26300); AMD64 |
| Python available | PASS | 0 | Python 3.14.7 |
| Runtime and test dependencies | PASS | 0 | customtkinter 6.0.0 Pillow 13.0.0 psutil 7.2.2 pytest 9.1.1 |
| Application imports | PASS | 0 | imports ok |
| PyInstaller build | PASS | 0 | 38287 INFO: Copying version information to EXE 38360 INFO: Copying 0 resources to EXE 38361 INFO: Embedding manifest in EXE 38430 INFO: Appending PKG archive to EXE 38572 INFO: Fixing EXE headers 39210 INFO: Building EXE from EXE-00.toc completed successfully. 39216 INFO: Build complete! The results are available in:  %USERPROFILE%\OneDrive\Desktop\Coding\Tweaker\Spotify\release |
| pytest tests (per-module isolation) | PASS | 0 | 313 passed, 1 skipped, 0 failed across 23 modules |
| Source smoke test | PASS | 0 | SMOKE TEST PASSED: ALL 11 CHECKS VERIFIED SUCCESSFULLY |
| Release executable | PASS |  | 34,373,370 bytes, written 2026-11-19T13:41:48.2983315+05:30 |
| SHA-256 | INFO |  | fresh build: f0f8f8cf8a4650d38f95f97506cfd78977709b55c9647959c64d7dc51cf4cd12 (previously recorded 5818ce0d72ca4f62d87dfb9972928125a3dc741909c625e389749141c77f71d1) |
| Version metadata | PASS |  | FileVersion=1.2.0.0; ProductVersion=1.2.0; Company=Icey |
| Packaged smoke test | PASS | 0 | SMOKE TEST PASSED: ALL 11 CHECKS VERIFIED SUCCESSFULLY |
| Screenshots | PASS | 0 | 05_backups.png  1770x1170  65 KB   06_startup.png  1770x1170  61 KB   07_installation.png  1770x1170  90 KB   08_activity_logs.png  1770x1170  65 KB   12_privacy_center.png  1770x1170  123 KB   09_settings.png  1770x1170  93 KB   10_about.png  1770x1170  91 KB 12 screenshots written to %USERPROFILE%\OneDrive\Desktop\Coding\Tweaker\Spotify\docs\screenshots |
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

