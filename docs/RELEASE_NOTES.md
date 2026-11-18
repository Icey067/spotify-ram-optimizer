# Release Notes

## Source changes after the 1.1.1 build — unreleased, not in the executable

**Status:** implemented in the working tree; **not built, not published**.
`release/SpotifyOptimizer.exe` is unchanged and still has SHA-256
`16aebc52e23705588f53c6b32439f4cab55fec796a2270c108bf52be9944e67a`.

| Area | Change | Verified how |
| --- | --- | --- |
| **Diagnostics page** | New navigation destination built on `run_health_check`: session check count, critical/warning/observation/informational counts, last-check timestamp, grouped findings with expandable evidence/impact/recommendation, Refresh and redacted export. It never applies a fix. | Widget tests (not yet run on Windows); portable diagnostics engine tests |
| **Privacy Center page** | New destination showing the real config, backup, log and history paths; files read; files modified; HKCU registry locations; retention settings and current local counts. Clear logs, clear history, manage backups and export report route to the existing app actions. | Widget tests (not yet run on Windows); paths come from `app_paths` and `AppConfig` |
| **12-destination navigation** | Sidebar regrouped into Overview / Management / Application with all twelve destinations. | Navigation tests updated; requires a Windows run |
| **Redaction hardening** | `redact_text()` now scrubs Windows (`C:\Users\name`), POSIX (`/home/name`, `/Users/name`), `USERPROFILE` and `HOME` profile paths anywhere in a report, not only as the string prefix. | 6 parametrised diagnostics tests |
| **Registry test split** | The full-run registry test is now Windows-only; a portable mocked-registry test covers the restore opt-in guard on every platform. | 20 passed, 1 skipped in `test_integration_isolated.py` on Linux |
| **Windows acceptance script** | `scripts/windows_acceptance.ps1` checks host, Python, imports, pytest, both smoke tests, executable, hash, version metadata and screenshots, then writes a Markdown report with real exit codes. | Script reviewed; **not executed** (no Windows here) |

### Verification performed (Linux audit host, not Windows)

- Full suite with Tk 8.6 and a virtual display:
  **305 passed, 1 skipped in 37.13 s** (306 collected).
  The skip is the Windows-only full-run registry test; the portable
  mocked-registry restore guard passes on Linux.
- `python main.py --smoke-test`: **11/11 checks, exit 0**.
- `py_compile` on every changed module: **exit 0**; all GUI modules import.
- Headless captures of both new pages at 1180x780 and 980x660 were reviewed.
  They exposed two real layout defects, now fixed: fixed `wraplength` values
  clipped text below ~1000 px, and the twelve-item sidebar pushed its footer
  off-screen at the 660 px minimum height. The fixes are source-level and were
  re-checked at both sizes.
- These are automated widget/navigation tests plus a rendered layout check, not
  a human click-through and **not Windows validation**.

### Not verified

- No Windows run, build or packaged smoke test after these changes.
- `scripts/windows_acceptance.ps1` has not been executed (no Windows host).
- No genuine Diagnostics or Privacy Center capture exists; the ten screenshots
  in `docs/screenshots/` belong to the previous ten-page build.
- 100/125/150% Windows display scaling and 1366x768 / 2560x1440 window layouts.
- Real registry writes, real Spicetify execution and the manual optimization
  workflow on a disposable Windows profile.

Nothing is claimed about the shipped executable containing these pages. A fresh
Windows build, all twelve captures, the new SHA-256 and the manual click-through
are still outstanding.

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
