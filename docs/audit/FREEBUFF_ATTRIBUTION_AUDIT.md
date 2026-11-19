# Freebuff / `freebufff` attribution audit

- Repository: `https://github.com/Icey067/spotify-ram-optimizer`
- Audit date: 2026-11-19
- Remote HEAD at audit: `cd9bd5fecb44e028ae54893e2dd767bbfe596b3b` (`main`)
- Result: **`freebufff` is not present in the published repository history or in the
  GitHub contributor list.** No public history rewrite is required to remove it.

## Method

- `git fetch origin --prune --tags`
- `git ls-remote origin`
- `git log --all`, `git for-each-ref`, `git fsck --unreachable --dangling`
- `git rev-list --all | git grep` for the string `freebuff`
- GitHub REST API: commits, contributors (`anon=1`), forks, pull requests,
  repository events, and the `freebufff` account
- Git commit pages (rendered attribution)

## Published history

`main` and tag `v1.0.0` contain six commits. Every commit is authored and
committed by `Icey067`:

| Commit | Author / committer | Message |
| --- | --- | --- |
| `cafc4eb` | `Icey067 <Icey067@users.noreply.github.com>` | Initial release: Spotify RAM Optimizer v1.0.0 for Windows |
| `b530ae5` | `Icey067 <Icey067@users.noreply.github.com>` | docs: add release binary download links to README |
| `6f3f4f4` | `Icey067 <Icey067@users.noreply.github.com>` | docs: modernize README with screenshots, download links, and safety details |
| `24aa235` | `Icey067 <Icey067@users.noreply.github.com>` | docs: add project tagline and author credits for Icey |
| `33b0054` | `Icey <icey067@users.noreply.github.com>` | feat: add diagnostics and privacy pages, release tooling |
| `cd9bd5f` | `Icey <icey067@users.noreply.github.com>` | docs: withdraw Activity Logs capture exposing a local username |

No commit has `freebufff` as author, committer, co-author or email.

Two published commits carry an AI-assistant trailer:

```text
Generated with Codebuff
Co-Authored-By: Codebuff <noreply@codebuff.com>
```

- `33b0054`
- `cd9bd5f`

GitHub resolves that trailer to the account **`codebuff-team`**, not
`freebufff`, and displays it beside `Icey067` on the commit page. It is an
attribution trailer, not a second human author and not a collaborator.

## Local-only Freebuff refs (never pushed)

The Freebuff Desktop tool created checkpoint commits under `refs/freebuff/*`.
They are **not** on `origin` (`git ls-remote` shows only `main` and tag
`v1.0.0`), and they are not reachable from `main`.

| Commit | Date (local) | Message | Scope |
| --- | --- | --- | --- |
| `c7372a5` | 2026-11-19 00:55:07 +0530 | Freebuff: files sent to Cloud for chat `c4ed5c10-…` | 52 files, +8884/−1317 |
| `01a20cb` | 2026-11-19 01:47:26 +0530 | Freebuff: files sent to Cloud for chat `41ce89c9-…` | 77 files, +11557/−1390 |
| `89349d0` | 2026-11-19 12:22:07 +0530 | Freebuff: Cloud's files for chat `41ce89c9-…` | executable only |
| `17a2955` | 2026-11-19 12:22:08 +0530 | Freebuff: this computer's files before chat `41ce89c9-…` returned | 32 files, +149/−32 |
| `f4cc2c7` | 2026-11-19 12:22:11 +0530 | Freebuff: landed | empty commit (same tree as `17a2955`) |

Author and committer for all five: `Freebuff <desktop@freebuff.local>`.

Two additional dangling snapshots exist, both children of `01a20cb` and both
authored by the same local identity: `a18792e` and `118a513`. They are not
referenced by any branch, tag or remote.

These commits contain snapshots of the developer's own local work (source,
tests, screenshots and the executable). They contain no contribution authored by
a third party, and none of them is published.

## GitHub metadata

- `GET /repos/Icey067/spotify-ram-optimizer/contributors?anon=1` → only
  `Icey067` (6 contributions).
- `GET /repos/Icey067/spotify-ram-optimizer/forks` → empty.
- `GET /repos/Icey067/spotify-ram-optimizer/pulls?state=all` → empty.
- Issue search for `freebufff` → 0 results.
- The GitHub account `freebufff` exists (id `318733918`) but has no commit,
  fork, issue or pull-request relationship with this repository.
- Collaborator permissions could not be listed without authentication
  (unauthenticated API returns 401). This is separate from commit attribution;
  check **Settings → Collaborators and teams** while signed in. No evidence of a
  collaborator-based attribution was found.

## Why it appeared

1. A local Git UI or `git log --all` shows the `refs/freebuff/*` checkpoints as
   commits by "Freebuff". Those refs are tool bookkeeping in the local clone and
   were never pushed.
2. On GitHub, the only non-`Icey067` attribution is `codebuff-team`, caused by
   the two `Co-Authored-By: Codebuff` trailers. That is an AI-assistant
   attribution, not `freebufff`.
3. `freebufff` may have been seen in a local client, a different repository, or a
   cached view. It is not part of this repository's reachable history.

## Classification

- **Case A (incorrect commit attribution):** applies only to the local
  `refs/freebuff/*` snapshots. They were authored by the Freebuff tool while
  committing the developer's own files. Since they were never published, no
  public metadata correction is needed.
- **Case B (unwanted commits):** not applicable to public history. No Freebuff
  commit is on `main`, a tag or a remote branch.
- **Case C (collaborator access):** not demonstrated. Verify the collaborator
  list while signed in; revoking access would not change commit attribution.
- **Case D (external/fork contribution):** not applicable. No forks, PRs or
  external commits exist.

## Proposed local cleanup (NOT executed)

The working tree contains uncommitted v1.2.0 release work, so destructive
cleanup is intentionally deferred for approval. Backups are already in place.

After approval, these commands remove only the local Freebuff tool refs, not
`main`, tags, the backup branch or the bundle:

```powershell
git for-each-ref --format='%(refname)' refs/freebuff |
  ForEach-Object { git update-ref -d $_ }
git reflog expire --expire=now --all
git gc --prune=now
```

Expected result: `git log --all` / `git fsck` no longer show Freebuff commits;
the backup bundle and `backup/pre-freebuff-cleanup-cd9bd5f` still preserve them.

## Optional public rewrite (only if `codebuff-team` must also disappear)

This is **not** required for `freebufff` and has not been performed. It would
rewrite two published commits (`33b0054`, `cd9bd5f`) to remove the
`Co-Authored-By` trailer, changing every SHA from `33b0054` onward, and would
require `git push --force-with-lease` after explicit approval. The v1.0.0 tag and
its release are unaffected.

## Backups

- Local branch: `backup/pre-freebuff-cleanup-cd9bd5f` → `cd9bd5f`
- Bundle: `backups/spotify-pre-freebuff-cleanup-20261119.bundle`
  - 39,319,738 bytes
  - SHA-256 `78dbf517fafb78f7bac2671130180edd00bf74a8a11f805cf9cc449a02e8c87`
  - `git bundle verify` → “The bundle records a complete history.”
- Remote HEAD recorded: `cd9bd5fecb44e028ae54893e2dd767bbfe596b3b`
- No tag, release, push or force-push was made during this audit.
