# Architecture

This document describes how the application is built, why it is built that way,
and where the sharp edges are.

## Principles

1. **The plan is the contract.** Nothing is applied that was not first described
   as a concrete `Change` object by a read-only planner.
2. **Every change is verified.** Success means "the value is present when read
   back", not "the write call did not raise".
3. **Everything is reversible, or honestly marked as not.** Cache cleanup is the
   only irreversible operation and it says so in its metadata.
4. **The GUI owns no knowledge of operations.** It renders `OPERATIONS`.
5. **Threads do I/O; Tk owns the UI.** No widget is touched off the main thread.

## Layers

```
main.py
  └─ src/gui/app.py            (shell, threading, orchestration)
       ├─ src/gui/*            (twelve lazily built pages, components, dialogs, theme)
       └─ src/core/engine.py   (pipeline)
            ├─ compatibility.py    → environment snapshot + verdicts
            ├─ optimizations.py    → registry, planner, executor, rollback
            │    ├─ prefs_manager.py
            │    ├─ registry_manager.py
            │    ├─ cache_manager.py
            │    └─ spicetify_manager.py
            ├─ backup_manager.py   → sessions, manifests, conflicts
            ├─ benchmark.py        → sampled measurements
            ├─ diagnostics.py      → health findings
            ├─ history.py          → SQLite
            └─ profiles.py         → validated JSON profiles
```

`src/core` has no Tk imports. It is importable, testable and reusable headlessly.

## The optimization pipeline

`OptimizationEngine._do_optimize` runs eight stages:

| # | Stage | Failure behaviour |
| --- | --- | --- |
| 1 | Build environment + plan | Unsupported operations are reported and skipped |
| 2 | Sampled "before" measurement | Degrades to "no live measurement" |
| 3 | Create backup, write manifest, verify integrity | **Abort before any change** |
| 4 | Close Spotify if the plan needs it | **Abort before any change** if it cannot close |
| 5 | Apply each change and verify | Rollback of preference/registry changes on a critical failure |
| 6 | Restart Spotify (only if requested) | Reported, not retried |
| 7 | Sampled "after" measurement | Reports non-comparability instead of a number |
| 8 | Record session + apply configured retention | Retention defaults to keep-everything |

### Data model

```python
OperationSpec   # static metadata from the registry
OptimizationRequest  # user selection (set of operation ids + parameters)
Plan            # changes + skipped + unsupported + backup targets + notes
Change          # one concrete write/delete with before/after values
ChangeOutcome   # applied | failed | skipped | unchanged, with verification
ExecutionReport # outcomes + rollback details
```

`Change.before` is what makes rollback and preview possible: the plan records
the current value before anything is written.

### Why the executor, not the operation, stops Spotify

Process lifecycle is a cross-cutting concern. Keeping it in the engine means
one place decides whether Spotify must close, and the cache executor can simply
refuse to run while Spotify is alive (files are locked) rather than each
operation re-implementing the check.

## Safety invariants

| Invariant | Enforced by |
| --- | --- |
| No deletion outside the cache root | `CacheManager._validate_target` + `app_paths.is_within` |
| No personal data in the cache allow-list | `PROTECTED_PATHS` and the exhaustive group lists |
| No registry writes outside `HKCU\...\Run` | `registry_manager.STARTUP_KEY_PATH` |
| No registry write to a non-Spotify name | `SPOTIFY_VALUE_NAMES` + value inspection |
| No restore that overwrites newer Spotify state silently | `BackupManager.has_conflict` |
| No deleted backups without explicit retention | `cleanup_old_sessions(keep<=0)` returns immediately |
| No shell execution | argument arrays only; version read via `ctypes` |
| No unvalidated import | `profiles.validate_profile` rejects unknown fields |
| No partial prefs file | temp file + `fsync` + `os.replace` |

## Page construction

Pages are registered as factories and built the first time they are shown
(`App._ensure_page`). The `*_panel` properties build on access so tests and the
smoke test keep their natural API. Nothing outside the visible page is
constructed at start-up, which is why start-up no longer pays for nine operation
cards, two canvases and the installation/backup trees before the first paint.
Cross-page callbacks (`_refresh_compatibility`, `_on_log_entry`,
`_refresh_performance`) check whether their page exists and do nothing if it does
not; the page refreshes itself through its `on_show` callback.

## Threading

- A scan, preview, optimization, restore, benchmark, process refresh, startup
  refresh and installation scan each run on a short-lived worker thread.
- `OptimizationEngine` holds a lock so two runs cannot interleave.
- Worker results reach the UI through `App._safe_after`. Calls already on the Tk
  thread run immediately; calls from a worker are enqueued and drained by
  `App._drain_ui_callbacks` on a 30 ms timer. `after()` is deliberately **not**
  called from worker threads: doing so silently dropped updates (scan results,
  progress text, health and benchmark output) because the scheduled callback
  could never run. After shutdown the queue is simply not drained.
- `logger` uses a lock around its bounded ring buffer and copies the callback
  list before invoking handlers.
- COM (`pythoncom.CoInitialize`) is initialised per calling thread in
  `shortcut_manager`, because shortcut access happens off the main thread.

## Measurement model

| Metric | Source | Caveat |
| --- | --- | --- |
| Working set | `psutil.memory_info().rss` summed over Spotify processes, sampled | Includes shared pages |
| Private memory | `psutil.memory_full_info().uss` when available | Optional; may be denied |
| CPU | per-process `cpu_percent(None)` deltas over the sampling loop | Playback state unknown |
| Cache size | recursive `scandir` sum over allow-listed directories | Disk, not RAM |

`benchmark.compare` refuses to produce a delta unless both readings have
Spotify running, warns when the difference is inside 5 % noise, and notes
version or process-count changes. This is the mechanism that prevents the
"we freed 600 MB" artefact of measuring after closing the app.

## Persistence

| Data | Location | Format |
| --- | --- | --- |
| Application settings | `%APPDATA%\SpotifyOptimizer\config.json` | JSON, validated and clamped |
| Backups | `%APPDATA%\SpotifyOptimizer\backups\<timestamp>\` | files + `metadata.json` + `manifest.json` |
| Logs | `%APPDATA%\SpotifyOptimizer\logs\optimizer_<ts>.log` | text, pruned at start-up |
| History | `%APPDATA%\SpotifyOptimizer\history.db` | SQLite (WAL) |
| Saved profiles | `%APPDATA%\SpotifyOptimizer\profiles\*.json` | validated JSON |

`SPOTIFY_OPTIMIZER_HOME` relocates all application state, which is what the
tests use to stay isolated.

## Testing strategy

| Layer | Files | Isolation |
| --- | --- | --- |
| Unit | `test_prefs_*`, `test_cache_*`, `test_detector`, `test_registry_manager`, `test_profiles` | temp dirs, mocked registry |
| Planning | `test_optimizations` (planning classes) | in-memory `Environment` |
| Transactional | `test_optimizations` (execution classes) | fake registry, temp prefs/cache |
| Backup | `test_backup_manager`, `test_backup_integrity` | temp backup root |
| Measurement | `test_benchmark`, `test_history` | fabricated results, temp DB |
| Diagnostics | `test_diagnostics` | in-memory environment, no measurement |
| GUI | `test_navigation`, `test_gui_features`, `test_smoke` | real Tk window, no destructive actions |
| Security | `test_security`, `test_profiles`, `test_cache_safety` | hostile inputs, mocked winreg |

## Trade-offs

- **Registry restore and shortcut restore are opt-in at API level.** Slightly
  more verbose for callers, but prevents a library user (or a test) from
  modifying a machine by accident.
- **Cache cleanup is irreversible.** Backing up gigabytes of disposable cache
  would be worse than the problem it solves; the operation is labelled
  non-reversible and excluded from rollback.
- **No abstraction over `psutil`.** A measurement façade would add indirection
  without testability gains, because the sampling logic is already isolated in
  `benchmark.py`.
- **Planner reads can be slow.** Enumerating a multi-gigabyte cache takes time;
  it happens on a worker thread and is the reason the preview is asynchronous.
