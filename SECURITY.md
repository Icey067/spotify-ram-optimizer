# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.1.x | Yes |
| 1.0.x | No — upgrade to 1.1 (it fixes a false memory-reporting defect and a silent backup-deletion defect) |

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting on this repository
(*Security → Report a vulnerability*). Include:

- the affected version and Windows build,
- what an attacker could achieve,
- reproduction steps or a proof of concept,
- whether the issue requires a malicious backup/profile file or local access.

There is no bug bounty. Reports are acknowledged on a best-effort basis by a
single maintainer.

## Security model

### Trust boundaries

| Input | Trust | Handling |
| --- | --- | --- |
| Spotify `prefs` file | Semi-trusted | Parsed line by line; unknown keys preserved verbatim; values re-read for verification |
| HKCU registry | Semi-trusted | Read for detection; written only for allow-listed Spotify value names, always after backup |
| Spotify cache directories | Untrusted layout | Fixed allow-list; resolved containment; links refused |
| Imported profile JSON | **Untrusted** | Strict schema; unknown fields rejected; only known operation ids and a bounded integer accepted |
| Backup sessions | Semi-trusted | Manifest with SHA-256; integrity verified before restore; deletion containment-checked |
| Shortcut `.lnk` files | Semi-trusted | Read via Shell COM; written only on explicit restore, from captured values |
| Log/diagnostic output | Untrusted for sharing | Diagnostic export redacts `%USERPROFILE%` |

### Deliberate design decisions

1. **No shell execution.** The application does not invoke `powershell`, `cmd`,
   `sh`, or any command string. Process creation uses argument arrays
   (`subprocess.Popen([exe])`). Version metadata is read through the Win32
   version API with `ctypes`, so a path containing quotes cannot become a
   command.
2. **No elevation.** Everything runs as the current user. `HKLM` is read-only
   (for Windows edition) and never written. There is no UAC prompt.
3. **No network.** There are no HTTP clients, no telemetry, no update checks.
4. **Allow-lists over denylists.** Registry value names, cache directories and
   operations are enumerated exhaustively. Anything not listed is refused.
5. **Containment checks.** Cache cleanup and backup deletion resolve paths and
   confirm they remain inside their root; symlinks and junctions are not
   traversed.
6. **Atomic writes.** Preference and configuration writes go to a temporary file
   in the same directory, are flushed and `fsync`ed, then `os.replace`d.
7. **Injection-resistant values.** Preference keys/values containing `=`, CR or
   LF are rejected before writing, so a value cannot create additional lines.
8. **Opt-in system changes.** `OptimizationEngine` and `restore_session` refuse
   registry and shortcut writes unless the caller passes an explicit flag. The
   GUI passes it; library callers do not by accident.
9. **Backups are never deleted implicitly.** Retention defaults to "keep
   everything"; pruning requires a positive configured count and is a manual,
   explicit action.

### Known limitations

- **No code signing.** SmartScreen will warn on first run of a locally built
  executable. Verify the SHA-256 from the release notes.
- **Antivirus heuristics.** A PyInstaller one-file executable that reads the
  registry and terminates a process can look suspicious. UPX is disabled to
  reduce false positives, but this cannot be eliminated without signing.
- **Self-reported results.** The application cannot prove that Spotify honoured
  a preference; it verifies the file content, not Spotify's behaviour.
- **Store installs.** Files inside a packaged app sandbox may be inaccessible;
  operations are then reported as unsupported rather than attempted.
- **Profile import scope.** A profile can only select implemented operations. It
  cannot execute code, write arbitrary paths, or change unrelated settings.

## Dependency surface

Runtime dependencies are intentionally minimal:

| Package | Purpose |
| --- | --- |
| `customtkinter`, `Pillow` | GUI toolkit and its image support |
| `psutil` | Process and memory measurement |
| `pywin32` | Shell COM access for shortcut inspection |

`pytest` and `pyinstaller` are development-only (`requirements-dev.txt`).

Audit locally with:

```powershell
python -m pip install pip-audit
python -m pip_audit -r requirements.txt
```

The project does not vendor or download code at runtime.
