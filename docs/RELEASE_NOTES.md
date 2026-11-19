# Release Notes

## v1.2.0 — Release Candidate (built and verified on Windows)

**Status:** final release candidate built, tested and validated on native
Windows 11 x64. **Not published.** No tag, GitHub Release, force-push or
history rewrite has been made; the working tree is left for review.

### Added

| Area | What it does |
| --- | --- |
| **Diagnostics workspace** | Dedicated page built on `run_health_check`: session check count, critical/warning/observation/information totals, last-check time, grouped findings with evidence, impact and recommendation, Refresh, and redacted Markdown export. It never applies a fix. |
| **Privacy Center workspace** | Shows the exact config, backup, log and history paths; files read; files modified; HKCU registry locations; retention settings and live counts. Clear-logs, clear-history, manage-backups and export-report actions reuse the existing app behaviour. |
| **Twelve-destination navigation** | Sidebar grouped into Overview, Management and Application, with lazy page construction and `grid_remove` view isolation. |
| **Redaction hardening** | `redact_text()` scrubs Windows and POSIX profile paths anywhere in diagnostic text and activity-log displays. |
| **Version consistency test** | `tests/test_version_consistency.py` enforces `1.2.0` across the engine, GUI, About page, `version_info.txt`, README, CHANGELOG and these notes. |
| **Windows acceptance runner** | `scripts/windows_acceptance.ps1` checks host, dependencies, imports, tests, both smoke tests, the fresh build, hash, PE metadata and screenshots, then writes a report with real exit codes. |

### Version inventory (all 1.2.0)

| Surface | Value |
| --- | --- |
| `src/core/engine.py` `APP_VERSION` | `1.2.0` |
| `App.VERSION` (sidebar and About) | `1.2.0` |
| `version_info.txt` | `FileVersion 1.2.0.0`, `ProductVersion 1.2.0` |
| PE resource | `FileVersion 1.2.0.0`, `ProductVersion 1.2.0` |
| `spotify_optimizer.spec` | 1.2.0 build |
| README, CHANGELOG, these notes | v1.2.0 |

### Verification — native Windows 11 x64

Host: Windows 11 Pro build 26300, AMD64; Python 3.14.7; customtkinter 6.0.0;
Pillow 13.0.0; psutil 7.2.2; pytest 9.1.1.

| Check | Result |
| --- | --- |
| PyInstaller build (`--clean --noconfirm`, v1.2.0 source) | **exit 0** |
| Full pytest suite, one module per process | **313 passed, 1 skipped, 0 failed** across 23 modules |
| Source smoke test (`python main.py --smoke-test`) | **11/11 checks, exit 0** |
| Packaged executable smoke test (`--smoke-test`) | **11/11 checks, exit 0** |
| PE version metadata | `FileVersion 1.2.0.0`, `ProductVersion 1.2.0`, Company `Icey` |
| Embedded icon | **1 icon resource** (`ExtractIconEx`) |
| Executable size | **34,373,370 bytes** |
| SHA-256 | `f0f8f8cf8a4650d38f95f97506cfd78977709b55c9647959c64d7dc51cf4cd12` |
| Screenshots | **12 captures**, 1770x1170, all twelve destinations |
| Screenshot inventory check | 12 of 12 expected |

The one skip is the symlink-creation test, which requires elevation on this
machine. Modules are executed in separate processes because a single-process
run hit an intermittent native Tcl/Tk crash on this Python 3.14/CTk combination;
both an isolated rerun and the per-module run passed all assertions. This is a
test-harness limitation, not an application failure. The earlier Linux audit
(305 passed, 1 skipped) is not re-run here.

### Privacy audit

- All twelve v1.2.0 captures were reviewed. Activity-log paths are displayed as
  `%USERPROFILE%`; no real Windows account name, personal Spotify path, playlist,
  download, cookie, login token or private backup metadata is visible.
- Captures run with a temporary `SPOTIFY_OPTIMIZER_HOME`, so the Backups page
  shows an empty state and no real snapshot IDs, timestamps or backup contents.
- The standard screenshots show the developer's real Spotify installation and
  version (Spotify was closed during capture, so the process table is empty);
  they contain no personal listening data.
- No secrets or credentials are present in the working tree or staged files.
- **Historical exposure:** the v1.0.0 capture `docs/screenshots/05_activity_logs.png`
  at commit `24aa235` showed the developer's real profile path in log lines. It remains in public
  Git history because history has not been rewritten. All v1.2.0 captures are
  clean; removing the historical blob requires an authorized history rewrite.

### Installation

1. Use `release/SpotifyOptimizer.exe` (34,373,370 bytes).
2. Verify it with:
   `Get-FileHash ./release/SpotifyOptimizer.exe -Algorithm SHA256`; the hash must
   equal `f0f8f8cf8a4650d38f95f97506cfd78977709b55c9647959c64d7dc51cf4cd12`.
3. Run it. No installer and no administrator rights are required.

### Tested vs not tested

**Tested on this Windows machine:** clean build, PE metadata, icon resource,
startup of the packaged executable, both smoke tests, all 314 automated tests,
all twelve destinations rendered by the smoke test, and headless/widget
navigation, diagnostics and Privacy Center rendering.

**Not tested:** a human click-through of preview → apply → restore against a live
Spotify profile; real registry writes or `spicetify apply`; Windows 10, a clean
VM or a Microsoft Store install; 100/125/150% display scaling and
1366x768/2560x1440 layouts; keyboard focus order; code signing.

**Known limitations**

- No code signing; SmartScreen may warn about the unsigned binary.
- Playback state is unknown, so CPU findings are capped at "low".
- `app.autostart-mode` is advanced/opt-in and unverified.
- `StartupApproved` is read, not written.
- The Processes page is read-only by design.
- Legacy 1.0.0 backups have no manifest and restore without hash verification.
- Screenshots come from one Windows 11 machine.

### Remaining work before publication

1. Review the executable, captures, notes and checksum.
2. Optionally perform the manual click-through on a disposable Windows profile.
3. Authorize the tag, GitHub Release and asset upload. Nothing has been tagged,
   committed or pushed for v1.2.0.

## v1.1.1 — unreleased (built and verified locally)

**Status:** built, tested and verified on the developer's Windows 11 machine.
**Not published.** No commit, tag, push or GitHub release has been made; the
working tree is left for review.

### Theme

Release polish and validation. There is no architectural rewrite in this
release. It closes the user-facing gaps left by 1.1.0, fixes the start-up
regression 1.1.0 introduced, and replaces placeholder presentation with real
captures and a real icon.

### User-facing additions

| Area | What it does |
| --- | --- |
| **Processes page** | The Spotify process tree — PID, executable, working set, CPU, state, start time, parent — read from the OS on demand. Read-only: there is no "end process" control. |
| **Startup page** | Every Spotify startup entry with its location, command, Windows enabled state and whether it may be modified. Enable/disable writes a verified snapshot first and confirms the registry state afterwards. Enabling reuses the command recorded in the newest backup. |
| **Installation page** | Install type, version, executable/data/preferences/cache paths, cache totals, disposable-cache bytes, Spicetify state and compatibility notes. Paths are redacted to `%USERPROFILE%` in the UI. |
| **Selective restore** | Pick which components to restore (preferences, startup entries, shortcuts, Spicetify config). A conflict is named per component, and overwriting requires an explicit opt-in instead of a yes/no message box. |
| **Icon and version display** | A drawn multi-resolution ICO (16–256 px) embedded in the executable and set as the window icon; version is shown in the sidebar and About page from one constant. |

### Defects found and fixed in 1.1.1

| Severity | Defect | Evidence |
| --- | --- | --- |
| High | UI updates scheduled from worker threads via `after()` could silently never run, dropping scan results, progress text, health reports and benchmark output. | A worker thread scheduling a callback printed nothing until the dispatch was replaced with a queue drained on the Tk thread. |
| High | Start-up regression from 1.1.0: every page was constructed before the first paint. | Measured below; fixed by building pages on first visit. |
| Medium | `spicetify.extensions` / `spicetify.custom_apps` reported "supported" on machines without Spicetify, then failed during execution. | The compatibility verdict returned `SUPPORTED` in an isolated tree with no Spicetify; they now declare `requires_spicetify`. |
| Low | Process-table values drifted away from their column headings (separate grids for header and body). | Visible in the first capture of the Processes page. |

### Verification — actual results

| Check | Result |
| --- | --- |
| Full test suite (`python -m pytest tests -q`) | **284 passed, 1 skipped** in 73.95 s |
| Isolated integration suite | **21 passed** in 1.49 s |
| Legacy regression suite (v1.0 tests) | Passing, unchanged |
| Source smoke test (`python main.py --smoke-test`) | **11/11 checks, exit 0** |
| Packaged executable smoke test | **exit 0**, 9.3 s |
| PyInstaller build | **exit 0** |
| Executable version resource | `FileVersion 1.1.1.0`, `ProductVersion 1.1.1` |
| Embedded icon | 1 icon resource (`ExtractIconEx` returns 1) |
| Executable size | **34,353,576 bytes** |
| SHA-256 | `16aebc52e23705588f53c6b32439f4cab55fec796a2270c108bf52be9944e67a` |

The single skip is symlink creation, which requires elevation on this machine.

### Start-up regression: measured, fixed, re-measured

Same tree, same machine, same dependencies, median of three fresh interpreters
(`scripts/measure_startup.py` measures the lazy build; the eager figure uses the
identical tree with every page constructed before the first paint, which is what
1.1.0 did):

| Strategy | First paint (median of 3) |
| --- | --- |
| Eager: build the seven original pages before painting (1.1.0 behaviour) | **1.632 s** |
| Lazy: build only the page being shown (1.1.1) | **0.909 s** |

Removed: **0.723 s** of work from the critical path. Run-to-run variance on this
desktop was ±0.1 s. An earlier in-session pair of direct `App()` + `update()`
measurements gave 0.977 s → 0.533 s for the same change.

Idle footprint after the change (median of 3): RSS at ready **56.1 MB**, threads
**11**, idle CPU over 3 s **0.00 %**, pages built at ready **1**.

### Validation levels — what was and was not executed

| Level | Scope | Result |
| --- | --- | --- |
| **Actual system** (read-only) | Detection, version, Spicetify discovery, process enumeration and screenshots on the developer's Windows 11 machine (Spotify 1.3.10.2586, Spicetify 2.46.7) | Verified |
| **Isolated** | Real core code against a complete temporary Spotify tree (`%APPDATA%\Spotify`, prefs, cache, Spicetify config) with application state redirected | 21 tests passing |
| **Mocked** | HKCU registry replaced by an in-memory implementation; no real startup value is read or written by the tests | Startup enable/disable, backup and restore verified |
| **Simulated** | Microsoft Store layout (temporary `Packages` tree), and `spicetify apply` (stubbed, binary never executed by tests) | Detection and config editing verified |

**No write was performed against the developer's real Spotify profile, registry,
shortcuts or cache during this release cycle.** All modification tests ran
against temporary trees.

### Compatibility

| Environment | Detection | Operations |
| --- | --- | --- |
| Windows 11 x64, standard Spotify Desktop | Verified (Spotify 1.3.10.2586) | Verified in isolation |
| Windows 10 | Detected by build number, guarded | **Not validated** |
| Microsoft Store install | Simulated layout detected | **Not validated on a real Store install** |
| Spicetify 2.46.7 | Detected, config parsed | Config edits verified in isolation; `spicetify apply` not executed |
| Non-Windows | Refused with a clear verdict | None |

### Known limitations

- **No code signing.** SmartScreen will warn about the unsigned executable. UPX
  is disabled to reduce heuristic false positives.
- **One machine.** Windows 10, a clean VM and a real Microsoft Store install are
  still unvalidated.
- **Playback state is unknown**, so CPU findings are capped at "low".
- **`app.autostart-mode` is unverified** and advanced/opt-in only.
- **`StartupApproved` is read, not written.** Only the HKCU Run value is toggled.
- **The Processes page is read-only** by design and cannot terminate anything.
- **The GUI restore flow was not executed end-to-end against a live profile.**
  The dialog (widget tests) and the engine (isolated tests) are covered
  separately; the click-through was not performed.
- **Screenshots** come from the developer's machine and therefore show its real
  Spotify version, real process tree and five legacy snapshots created by
  earlier use of the tool. Paths are redacted by the application.
- **Backups from 1.0.0** have no manifest and are labelled "Legacy snapshot";
  they restore without hash verification because there is nothing to verify.

### Remaining work

1. Validate on a clean Windows 10 VM and a real Microsoft Store install.
2. Sign the executable and document the signing steps.
3. Click-through validation of preview → apply → restore against a disposable
   Spotify profile.
4. Keyboard navigation pass and accessible focus order.
5. Optional scheduled health check (opt-in only), portable mode, CLI reporting.

## v1.1.0 — unreleased

Engine rebuilt around a declarative operation registry: dry-run preview,
hash-verified backups with conflict detection, transactional execution with
rollback, sampled benchmarking that refuses to compare incomparable readings,
a local SQLite history, validated custom profiles and a health-check engine.

Critical fixes: fabricated memory savings caused by measuring after Spotify was
closed, and every optimization silently deleting all but ten backups. Also
fixed: prefs rewritten sorted and comment-free, PowerShell command injection in
version detection, uncaught `PermissionError` scanning `WindowsApps`, and two
methods shadowing CustomTkinter internals.

## v1.0.0 — 2025-11-15

Initial public release: seven-page CustomTkinter workspace, Spotify detection,
preference and cache management, backup/restore, live resource monitoring,
standalone PyInstaller executable.
