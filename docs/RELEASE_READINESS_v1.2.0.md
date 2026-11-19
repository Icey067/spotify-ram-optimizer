# v1.2.0 Release Readiness Report

- Date: 2026-11-19
- Project: Spotify RAM Optimizer
- Repository: `Icey067/spotify-ram-optimizer`
- Baseline: `main` at `cd9bd5fecb44e028ae54893e2dd767bbfe596b3b`
- Working tree: v1.2.0 changes present, **uncommitted**
- Verdict: **Ready for review. Not published.**

No commit, tag, GitHub Release, push, force-push or history rewrite was made.

## 1. Source baseline

- `git fetch origin --prune --tags` completed.
- `origin/main` = `cd9bd5fecb44e028ae54893e2dd767bbfe596b3b`.
- `cd9bd5f` is the remote HEAD and is an ancestor of the working tree.
- Published tags: `v1.0.0` only.
- Published history: six commits, all authored and committed by `Icey067`.
- The v1.2.0 changes are working-tree modifications and new files; they are not
  committed. `git log origin/main..HEAD` is empty.
- Existing backup branch: `backup/pre-freebuff-cleanup-cd9bd5f`.
- Existing complete bundle: `backups/spotify-pre-freebuff-cleanup-20261119.bundle`
  (SHA-256 `78dbf517fafb78f7bac2671130180edd00bf74a8a11f805cf9cc449a02e8c87`).

## 2. Version consistency (all 1.2.0)

| Surface | Value | Status |
| --- | --- | --- |
| `src/core/engine.py` `APP_VERSION` | `1.2.0` | PASS |
| `src/gui/app.py` `App.VERSION` (sidebar) | `1.2.0` | PASS |
| About page default (`workspace_pages.AboutPanel`) | `1.2.0` | PASS |
| `version_info.txt` | `FileVersion 1.2.0.0`, `ProductVersion 1.2.0` | PASS |
| Built PE resource | `FileVersion 1.2.0.0`, `ProductVersion 1.2.0` | PASS |
| `spotify_optimizer.spec` | 1.2.0 build | PASS |
| `README.md` | v1.2.0 | PASS |
| `CHANGELOG.md` | `[1.2.0]` | PASS |
| `docs/RELEASE_NOTES.md` | v1.2.0 | PASS |

`tests/test_version_consistency.py` enforces these surfaces. Result: **8 passed**.

## 3. Validation results

### Full acceptance with build

Command:

```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/windows_acceptance.ps1 -Build -CaptureScreenshots
```

Report: `docs/acceptance/windows_acceptance_build_report.md`

| Check | Result |
| --- | --- |
| Windows host | PASS — Windows 11 Pro build 26300, AMD64 |
| Python / dependencies | PASS — Python 3.14.7, customtkinter 6.0.0, Pillow 13.0.0, psutil 7.2.2, pytest 9.1.1 |
| Application imports | PASS |
| PyInstaller build | PASS — exit 0 |
| Test suite, one module per process | PASS — 313 passed, 1 skipped, 0 failed across 23 modules |
| Source smoke test | PASS — 11/11, exit 0 |
| Packaged smoke test | PASS — 11/11, exit 0 |
| Version metadata | PASS — `1.2.0.0` / `1.2.0` / company `Icey` |
| Screenshots | PASS — 12 captures at 1770x1170 |
| Overall | **PASS** |

### Final no-build verification

Command:

```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/windows_acceptance.ps1
```

Report: `docs/acceptance/windows_acceptance_report.md`

| Check | Result |
| --- | --- |
| Test suite, one module per process | PASS — 313 passed, 1 skipped, 0 failed |
| Source and packaged smoke tests | PASS — 11/11 each |
| SHA-256 against recorded value | PASS |
| Version metadata | PASS |
| Overall | **PASS** |

The single-process `python -m pytest tests -q` run still hits an intermittent
native Tcl/Tk access violation in `test_smoke` on this Python 3.14/customtkinter
combination. The acceptance runner executes each test module in its own process,
which is the validated path: 313 passed, 1 skipped, 0 failed. This is a test
harness limitation, not an application failure.

The skipped test is the symlink-creation test that requires elevation.

## 4. Standalone build

| Property | Value |
| --- | --- |
| Path | `release/SpotifyOptimizer.exe` |
| Size | **34,373,370 bytes** |
| SHA-256 | `f0f8f8cf8a4650d38f95f97506cfd78977709b55c9647959c64d7dc51cf4cd12` |
| FileVersion | `1.2.0.0` |
| ProductVersion | `1.2.0` |
| Company | `Icey` |
| Embedded icon | 1 icon resource (`ExtractIconEx`) |
| `--version` | exit 0 (`Spotify RAM Optimizer v1.2.0`) |
| Startup / smoke | 11/11 checks, exit 0 |

Checksums:

- `SHA256SUMS.txt` → `release/SpotifyOptimizer.exe`
- `release/SHA256SUMS.txt` → `SpotifyOptimizer.exe`

Both match the binary above.

## 5. Screenshots and privacy

All twelve captures were regenerated from a temporary `SPOTIFY_OPTIMIZER_HOME`:

| Page | File |
| --- | --- |
| Dashboard | `01_dashboard.png` |
| Optimizations | `02_optimizations.png` |
| Diagnostics | `11_diagnostics.png` |
| Performance | `03_performance.png` |
| Processes | `04_processes.png` |
| Backups & Restore | `05_backups.png` |
| Startup | `06_startup.png` |
| Installation | `07_installation.png` |
| Activity Logs | `08_activity_logs.png` |
| Privacy Center | `12_privacy_center.png` |
| Settings | `09_settings.png` |
| About | `10_about.png` |

Verified:

- No real Windows account name appears in any capture.
- Spotify paths are shown as `%USERPROFILE%`.
- Backups page shows **0 snapshots** and no backup IDs, timestamps or contents.
- Activity Logs capture is additionally sanitised with `redact_path()`.
- Privacy Center paths use the temporary capture directory and `%USERPROFILE%`.
- No credentials, tokens or secrets are present in the working tree.
- No personal Spotify listening data is shown.

**Historical exposure:** the v1.0.0 Activity Logs capture in commit `24aa235`
contained a real profile path. It remains in public Git history because history
has not been rewritten. All v1.2.0 captures are clean. Removing the historical
blob requires an authorized history rewrite and is not part of this release.

## 6. Freebuff / `freebufff` attribution

Summary: `freebufff` is **not** in the published history or GitHub contributor
list. Full evidence and exact commits: `docs/audit/FREEBUFF_ATTRIBUTION_AUDIT.md`.

- Public commits: six, all by `Icey067`.
- GitHub contributors with `anon=1`: only `Icey067`.
- No forks, pull requests or issue mentions.
- Local-only `refs/freebuff/*` checkpoints are authored by
  `Freebuff <desktop@freebuff.local>` and were never pushed.
- Two public commits (`33b0054`, `cd9bd5f`) contain
  `Co-Authored-By: Codebuff <noreply@codebuff.com>`, which GitHub shows as
  `codebuff-team`; this is not `freebufff`.
- No public history rewrite is needed to remove `freebufff`.
- Local Freebuff ref cleanup is proposed but **not executed**, pending approval.

## 7. Tested vs not tested

**Tested on native Windows:**

- Clean PyInstaller build from this source tree.
- PE version metadata and embedded icon.
- Packaged executable startup and CLI `--version`.
- All 314 automated tests (313 passed, 1 skipped).
- Both 11-check smoke tests.
- Rendering of all twelve destinations via the smoke test.
- Twelve real screenshots with isolated application data.

**Not tested:**

- A human click-through of preview → apply → restore against a live Spotify
  profile.
- Real registry writes or `spicetify apply`.
- Windows 10, a clean VM, or a Microsoft Store installation.
- 100/125/150% display scaling and 1366x768/2560x1440 layouts.
- Keyboard focus order.
- Code signing.

## 8. Known limitations

- No code signing; SmartScreen may warn about the unsigned binary.
- Playback state is unknown, so CPU findings are capped at “low”.
- `app.autostart-mode` is advanced/opt-in and unverified.
- `StartupApproved` is read, not written.
- The Processes page is read-only by design.
- Legacy 1.0.0 backups have no manifest and restore without hash verification.
- Screenshots come from one Windows 11 machine.
- The historical v1.0.0 Activity Logs capture remains in public history.

## 9. Publication steps (NOT executed — awaiting approval)

1. Review this report, `docs/RELEASE_NOTES.md`, the executable, the twelve
   screenshots and `SHA256SUMS.txt`.
2. Optionally perform the manual click-through on a disposable Windows profile.
3. Commit the v1.2.0 working tree.
4. Create tag `v1.2.0`.
5. Create the GitHub Release and upload `SpotifyOptimizer.exe` and
   `SHA256SUMS.txt`.
6. Decide separately whether to clean local `refs/freebuff/*` and whether to
   rewrite the two Codebuff co-author trailers.

None of steps 3–6 has been performed.
