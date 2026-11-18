# Contributing

Thanks for taking the time to improve this project. It is maintained by one
person, so small, focused, well-tested pull requests are the easiest to review.

## Ground rules

1. **No unsupported tweaks.** A new optimization needs evidence that the setting
   exists and is honoured, a compatibility rule, a verification step and a
   rollback path. "It might reduce RAM" is not enough.
2. **No new claims.** Do not add text that promises a speed-up, RAM saving or
   compatibility that cannot be measured or proven.
3. **Never touch personal data.** Playlists, downloads, cookies, logins, local
   storage, indexed DB and databases are off limits, including in tests.
4. **Tests first for behaviour changes.** A fix without a regression test will
   usually be asked for one.

## Development setup

```powershell
git clone https://github.com/Icey067/spotify-ram-optimizer.git
cd spotify-ram-optimizer
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python main.py
```

Run the packaged-path verification before opening a PR that touches the engine,
imports or the GUI shell:

```powershell
python main.py --smoke-test
```

## Adding an optimization

All operations live in `src/core/optimizations.py`.

1. Add an `OperationSpec` to `OPERATIONS` with:
   - a stable dotted id (`group.name`),
   - honest `summary` / `detail` / `rationale`,
   - `risk`, `profiles`, and the requirements it needs,
   - `unverified=True` if the setting is not officially documented.
2. Add a branch in `build_plan()` that produces `Change` objects by **reading**
   current state. The planner must remain read-only.
3. Add execution in `Optimizer._apply_change()` and verification by re-reading
   the value. If it is not reversible, say so (`reversible=False`) instead of
   pretending.
4. Add tests in `tests/test_optimizations.py`:
   - a dry-run test proving nothing is written,
   - an apply test proving the value and its verification,
   - a skip test for the unsupported case.
5. Update `CHANGELOG.md` and, if user-visible, `README.md`.

The GUI picks the operation up automatically; only add UI code if the operation
needs an input (for example the cache-size value).

## Code style

- Type hints on public functions; `from __future__ import annotations`.
- Prefer small, testable services over large methods.
- Catch specific exceptions. Broad `except Exception` is acceptable only at a
  thread boundary where the alternative is a crashed UI, and must be logged.
- No `print()` in library code; use `src.core.logger`.
- No blocking work on the Tk thread. Use a worker thread and `App._safe_after`.
- Do not name methods `_set_scaling` or `_apply_appearance_mode` on a
  `CTk` subclass — those are CustomTkinter hooks.

## Tests

```powershell
python -m pytest tests -q                 # full suite
python -m pytest tests/test_engine.py -q  # one module
python -m pytest tests -q -k cache        # one area
```

Rules for new tests:

- Use `tmp_path`; never a real Spotify profile.
- Never write to `HKCU` from a test. Use the in-memory registry pattern from
  `tests/test_optimizations.py`.
- Never assume Spotify is running; the benchmark tests are written to pass in
  both cases.

## Packaging

```powershell
python -m PyInstaller --clean --noconfirm `
  --distpath release --workpath .release-build spotify_optimizer.spec
```

Bump `version_info.txt`, `App.VERSION`, `engine.APP_VERSION` and
`CHANGELOG.md` together. Verify the executable with `--smoke-test` and record
its SHA-256 in the release notes.

## Commit messages

Conventional prefixes are used: `feat:`, `fix:`, `perf:`, `refactor:`, `test:`,
`docs:`, `build:`, `chore:`. Explain *why* in the body when the change is not
obvious.

## Pull requests

- Keep the diff scoped to one concern.
- Describe behaviour changes and how you verified them.
- Say explicitly what you did **not** test (for example "not validated on
  Windows 10" or "no Microsoft Store installation available").
- Never include fabricated test output, screenshots or performance numbers.
