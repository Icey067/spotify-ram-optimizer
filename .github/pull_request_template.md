## Summary

<!-- What changes, and why? -->

## Type of change

- [ ] Bug fix
- [ ] New optimization (requires evidence + verification + rollback)
- [ ] Refactor (no behaviour change)
- [ ] Documentation / build / CI
- [ ] Security hardening

## Verification

Commands run and their results:

```text
python -m pytest tests -q
python main.py --smoke-test
```

If the executable was rebuilt:

```text
pyinstaller ... spotify_optimizer.spec
SpotifyOptimizer.exe --smoke-test   -> exit code
SHA256: ...
```

## Safety review

- [ ] No new path can delete data outside an allow-listed, containment-checked location
- [ ] No shell command is constructed from user or filesystem input
- [ ] Any new operation has a compatibility rule, verification and rollback (or is explicitly marked irreversible)
- [ ] No test writes to a real Spotify profile, registry key or cache
- [ ] No claim of performance improvement was added without a measurement

## Not tested

<!-- Be explicit, e.g. "not validated on Windows 10", "no Store installation available" -->

## Related issues

Closes #
