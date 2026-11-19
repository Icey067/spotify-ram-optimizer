# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [1.2.0] — 2026-11-19 (release candidate, not published)

Final release candidate incorporating the Diagnostics and Privacy Center workspaces, twelve-destination navigation, path redaction hardening, version consistency testing, and a unified Windows acceptance suite.

### Added (1.2.0)

- **Diagnostics workspace**: Dedicated diagnostic surface displaying active health findings, grouped by severity (critical, warning, observation, info), with evidence, impact, recommended fix, and redacted markdown report export.
- **Privacy Center workspace**: Transparent visibility into exactly what Spotify Optimizer reads, modifies, and stores; real paths for configs, backups, logs, and telemetry history; explicit retention periods; and 1-click log and history purge actions.
- **Twelve-destination navigation**: Unified sidebar structured into Overview, Management, and Application categories with clean `grid_remove` view isolation and lazy loading.
- **Profile path redaction hardening**: Enhanced `redact_text()` scrubbing Windows (`C:\Users\username`) and POSIX profile paths anywhere within diagnostic exports and activity log displays.
- **Native Windows acceptance suite**: Comprehensive `scripts/windows_acceptance.ps1` automated release readiness runner.
- **Version consistency test**: Dedicated automated test (`tests/test_version_consistency.py`) ensuring version uniformity across all code and metadata surfaces.
- **CLI version argument**: Added `--version` / `-v` flag to `main.py` printing application version.

### Changed (1.2.0)

- Updated application version to `1.2.0` across engine, GUI, metadata, and docs.
- Updated Win32 PE version resource to `1.2.0.0`.
- Redacted historical activity log screenshot exposure and updated acceptance suite.

### Validation (1.2.0)

- Native Windows 11 x64 acceptance run: PyInstaller build exit 0; **313 passed,
  1 skipped, 0 failed** across 23 test modules; source and packaged smoke tests
  both **11/11, exit 0**.
- PE metadata: `FileVersion 1.2.0.0`, `ProductVersion 1.2.0`, Company `Icey`;
  1 embedded icon resource.
- Executable: **34,373,370 bytes**, SHA-256
  `f0f8f8cf8a4650d38f95f97506cfd78977709b55c9647959c64d7dc51cf4cd12`.
- Twelve screenshots regenerated at 1770x1170; activity-log paths redacted.

## [1.1.1] — 2026-11-18

Release polish and validation. No architectural rewrite: this release closes the
user-facing gaps left by 1.1.0, fixes the start-up regression it introduced, and
replaces the placeholder presentation with real captures and a real icon.

### Added (1.1.1)

- **Processes page**: the Spotify process tree (PID, executable, working set,
  CPU, state, start time, parent) read from the OS on demand. Read-only by
  design — there is no "end process" control.
- **Startup page**: every Spotify startup entry with its location, command,
  Windows enabled state and whether it is safe to modify. Enable/disable is
  backup-first and verified afterwards; enabling re-uses the command recorded in
  the newest backup.
- **Installation page**: install type, version, executable and data paths,
  preferences/cache locations, file and cache sizes, disposable-cache total,
  Spicetify state and the environment's compatibility notes. Paths are redacted
  to `%USERPROFILE%`.
- **Selective restore dialog**: choose which components (preferences, startup
  entries, shortcuts, Spicetify config) to restore, with each conflict named and
  an explicit "overwrite" opt-in instead of an all-or-nothing message box.
- **Application icon**: a drawn multi-resolution ICO (16–256 px) embedded in the
  executable and shown in the window.
- **`scripts/`**: icon generation, real screenshot capture (`PrintWindow`, so an
  overlapping window cannot corrupt a capture) and a reproducible start-up
  measurement harness.
- **Isolated integration suite**: a complete temporary Spotify tree exercises
  detection (standard and Microsoft Store layout), compatibility verdicts, dry
  run, backup + integrity, apply + verification, restore, conflict handling,
  cache cleanup with personal-data protection, Spicetify edit/restore and the
  startup toggle. The registry is mocked and `spicetify apply` is simulated; no
  real Spotify profile, registry value or cache is touched.
- **Thread-safe UI dispatch test** in the packaged smoke test.

### Changed (1.1.1)

- **Pages are built lazily** on first visit instead of all at start-up. This is
  the fix for the 1.1.0 start-up regression; navigation, state and tests are
  unchanged.
- Restore is now per-component and always explains which component conflicted.
- Worker-thread updates are queued and drained on the Tk thread.
- `spicetify.extensions` and `spicetify.custom_apps` declare
  `requires_spicetify`, so they report **unsupported** when Spicetify is absent
  rather than claiming support and failing later.
- Version is `1.1.1` everywhere; executable metadata is `1.1.1.0`.
- Screenshots regenerated from this build; the outdated v1.0.0 set (including a
duplicate `screenshots/` folder) was removed.

### Fixed (1.1.1)

- **High:** UI updates scheduled from worker threads with `after()` could
  silently never run, dropping scan results, progress text, health reports and
  benchmark output. Replaced with a queue drained on the Tk thread.
- **High:** the 1.1.0 start-up regression (+0.34 s) came from constructing every
  page (nine operation cards, two canvases) before the first paint.
- **Medium:** Spicetify operations were reported as supported on machines
  without Spicetify.
- **Low:** process-table values drifted away from their column headings because
  header and body used separate grids.

### Validation (1.1.1)

- Test suite: **284 passed, 1 skipped** (~74 s).
- Isolated integration: **21 passed** (simulated/mocked boundaries documented in
  the module docstring).
- Start-up, same tree and machine, median of 3 fresh interpreters: eager
  seven-page construction **1.632 s** → lazy **0.909 s**.
- Packaged executable: rebuilt, version resource `1.1.1.0`, smoke test exit 0.

## [1.1.0] — unreleased

### Added (1.1.0)

- **Operation registry** (`src/core/optimizations.py`): every optimization is a
  declared unit with name, description, rationale, risk level, profile
  membership, compatibility requirements, reversibility and restart policy. The
  GUI renders this registry instead of hardcoding options.
- **Compatibility layer** (`src/core/compatibility.py`): Windows release/build,
  edition, architecture, install type, Spicetify availability, prefs/cache
  access and process state, with per-operation verdicts
  (supported / partially supported / unsupported / requires restart / requires
  confirmation).
- **Dry-run preview**: a real plan listing the prefs keys, registry values,
  cache directories and files that would change, plus backups to be taken.
- **Transactional execution**: per-change verification and automatic rollback of
  preference and registry changes when a critical step fails.
- **Optimization profiles**: Safe (default), Balanced, Advanced, Custom.
- **Backup 2.0**: SHA-256 manifest, integrity verification, post-write hash
  recording, restore conflict detection, per-session restore, explicit deletion,
  and retention that keeps everything by default.
- **Health check engine**: evidence-based findings with severity, impact,
  recommendation and an optional available action. Never auto-applies.
- **Benchmark engine**: sampled working set, private memory (when exposed), mean
  and peak CPU, uptime, cache size — with explicit non-comparability handling.
- **Performance history**: local SQLite store with retention and clearing.
- **Cache inventory**: per-directory sizes, eligibility reasons, allow-list
  enforcement, symlink/junction refusal.
- **Startup manager view**: Spotify startup entries with location, command,
  Windows enabled state, and whether they are safe to modify.
- **Process monitor data**: process tree details (PID, memory, CPU, state,
  start time, Spotify-parent relationships).
- **Custom profiles**: versioned JSON export/import with strict validation.
- **Privacy & transparency section**: exact paths read/written, log/history
  clearing, redacted diagnostic report export.
- **Diagnostic report export** with `%USERPROFILE%` redaction.
- **CI pipeline** (`.github/workflows/ci.yml`), issue and PR templates.

### Changed (1.1.0)

- The engine now refuses to write preferences when Spotify cannot be closed,
  instead of writing values Spotify may overwrite on exit.
- Memory "before/after" is only compared when Spotify ran for both readings.
  Fictional "freed MB" values are gone.
- Old backups are no longer deleted automatically during optimization.
- Spotify version detection uses the Win32 version API instead of a PowerShell
  subprocess (removes a command-injection vector, ~100x faster).
- `prefs` edits preserve comments, key order, unknown keys and CRLF line endings.
- Application logs are pruned at start-up; the in-memory log buffer is bounded.
- Cache cleanup validates resolved containment and never follows links.
- Registry writes are restricted to a Spotify value allow-list and verify the
  value still points at Spotify.
- Registry and shortcut writes are opt-in at the API level; the GUI enables them.
- Spicetify checkbox rows are rebuilt only when discovery changes (was: every
  five seconds, discarding user selections).
- `customtkinter` requirement widened to `<7` to match the tested 6.0 release.
- PyInstaller build embeds version metadata and disables UPX.

### Fixed (1.1.0)

- **Critical:** optimization reported large RAM savings that were an artefact of
  having just closed Spotify.
- **Critical:** every optimization silently deleted all but the 10 newest
  backups, including a backup taken in the same run.
- **High:** Spotify's prefs file was rewritten sorted and stripped of comments.
- **High:** `_get_version` interpolated the executable path into a PowerShell
  command string.
- **High:** scanning `WindowsApps` could raise an uncaught `PermissionError`.
- **High:** `App._set_scaling` shadowed a CustomTkinter internal hook, breaking
  window creation in some initialization orders.
- **High:** `App._apply_appearance_mode` shadowed another CustomTkinter hook.
- **Medium:** COM was not initialized for shortcut access on worker threads.
- **Medium:** a saved `custom` profile restored no selections at start-up.
- **Medium:** the log directory grew without bound.

### Security (1.1.0)

- Removed all shell-string construction; no `powershell`, `cmd` or `shell=True`.
- Added preference key/value validation against newline injection.
- Added strict schema validation for imported profiles (unknown fields rejected).
- Added containment checks for backup deletion and cache cleanup.

## [1.0.0] — 2025-11-15

### Added
- Initial public release: seven-page CustomTkinter desktop application,
  Spotify installation detection, preference and cache management, backup and
  restore, live resource monitoring, standalone PyInstaller executable.
