"""
Evidence-based optimization registry and transactional planner.

Everything the UI offers comes from :data:`OPERATIONS`.  Each operation is an
independent, inspectable unit with:

  * honest metadata (risk, reversibility, restart requirement, evidence),
  * explicit compatibility requirements,
  * a planner that produces *real* :class:`Change` objects by reading the
    current state of the system (never by guessing),
  * an executor with per-change verification,
  * a rollback path for every change that is not inherently disposable.

The planner is read-only.  :func:`build_plan` is what powers dry-run mode: it
returns exactly the files, registry values and cache directories that an
execution would touch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .cache_manager import CACHE_GROUPS, GROUP_LABELS, CacheManager
from .compatibility import (
    CompatibilityVerdict,
    Environment,
    SupportLevel,
    evaluate_requirements,
)
from .logger import get_logger
from .prefs_manager import (
    PrefsManager,
    build_autostart_pref,
    build_cache_size_pref,
    build_hw_accel_pref,
)
from .registry_manager import RegistryManager
from .spicetify_manager import SpicetifyManager

log = get_logger("optimizations")


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


PROFILE_SAFE = "safe"
PROFILE_BALANCED = "balanced"
PROFILE_ADVANCED = "advanced"
PROFILE_CUSTOM = "custom"

PROFILE_DESCRIPTIONS: dict[str, str] = {
    PROFILE_SAFE: "Only well-supported, low-risk changes. Recommended.",
    PROFILE_BALANCED: "Adds startup management and GPU cache cleanup.",
    PROFILE_ADVANCED: "Every operation, including unverified settings, chosen individually.",
    PROFILE_CUSTOM: "Your own selection of individual operations.",
}


@dataclass(frozen=True)
class OperationSpec:
    id: str
    name: str
    summary: str
    detail: str
    rationale: str
    risk: Risk
    profiles: tuple[str, ...]
    requires_prefs: bool = False
    requires_cache: bool = False
    requires_registry: bool = False
    requires_spicetify: bool = False
    requires_spotify_closed: bool = False
    requires_backup: bool = True
    reversible: bool = True
    requires_restart: bool = False
    unverified: bool = False
    docs: str = ""

    def compatibility(self, env: Environment) -> CompatibilityVerdict:
        return evaluate_requirements(
            env,
            requires_prefs=self.requires_prefs,
            requires_cache=self.requires_cache,
            requires_registry=self.requires_registry,
            requires_spicetify=self.requires_spicetify,
            requires_spotify_closed=self.requires_spotify_closed,
            unverified=self.unverified,
        )


OPERATIONS: tuple[OperationSpec, ...] = (
    OperationSpec(
        id="prefs.hardware_acceleration",
        name="Disable hardware acceleration",
        summary="Turn off Spotify's GPU compositing so rendering falls back to the CPU.",
        detail=(
            "Writes hardware_acceleration_mode_enabled=false to Spotify's prefs file. "
            "This is the same value Spotify writes when you switch off "
            "'Enable hardware acceleration' in its own settings."
        ),
        rationale=(
            "On GPUs with buggy or memory-hungry drivers, disabling compositing can "
            "reduce GPU memory use and driver-side allocation. It can also make the "
            "interface smoother or choppier depending on your hardware."
        ),
        risk=Risk.LOW,
        profiles=(PROFILE_SAFE, PROFILE_BALANCED, PROFILE_ADVANCED),
        requires_prefs=True,
        requires_spotify_closed=True,
        requires_restart=True,
        docs="Spotify > Settings > Compatibility > Enable hardware acceleration",
    ),
    OperationSpec(
        id="prefs.cache_size",
        name="Limit Spotify cache size",
        summary="Cap the on-disk cache Spotify is allowed to grow to.",
        detail=(
            "Writes storage.size in megabytes. Spotify trims its cache to this limit "
            "as it runs; the full effect appears after a restart."
        ),
        rationale=(
            "A large cache is not a RAM leak, but it can fill the system drive and makes "
            "Spotify spend time indexing on start. A moderate cap keeps the cache useful."
        ),
        risk=Risk.LOW,
        profiles=(PROFILE_SAFE, PROFILE_BALANCED, PROFILE_ADVANCED),
        requires_prefs=True,
        requires_spotify_closed=True,
        requires_restart=True,
        docs="Spotify > Settings > Storage > Cache size",
    ),
    OperationSpec(
        id="cache.browser",
        name="Clear web and network cache",
        summary="Remove disposable HTTP tiles and service-worker blobs.",
        detail=(
            "Deletes the contents of Cache, Cache_Data, blob_storage and Service "
            "Worker caches. The directories are kept; Spotify re-creates entries "
            "as needed."
        ),
        rationale=(
            "Stale cache entries are the most common reason Spotify starts slowly or "
            "shows outdated artwork. The files are disposable by design."
        ),
        risk=Risk.LOW,
        profiles=(PROFILE_SAFE, PROFILE_BALANCED, PROFILE_ADVANCED),
        requires_cache=True,
        requires_spotify_closed=True,
        reversible=False,  # data is disposable, not recoverable — stated honestly
        docs="Spotify rebuilds these caches automatically.",
    ),
    OperationSpec(
        id="cache.code",
        name="Clear compiled code cache",
        summary="Remove cached JavaScript bytecode.",
        detail="Deletes the contents of 'Code Cache'. Spotify re-compiles scripts on next start.",
        rationale="Corrupt bytecode caches cause UI glitches; clearing them is harmless.",
        risk=Risk.LOW,
        profiles=(PROFILE_SAFE, PROFILE_BALANCED, PROFILE_ADVANCED),
        requires_cache=True,
        requires_spotify_closed=True,
        reversible=False,
    ),
    OperationSpec(
        id="cache.gpu",
        name="Clear GPU shader cache",
        summary="Remove cached shader programs.",
        detail="Deletes the contents of 'GPUCache'. Shaders are regenerated on next start.",
        rationale=(
            "A new shader cache is rebuilt on the next launch; this can help after a "
            "graphics driver update, but it briefly slows the first start."
        ),
        risk=Risk.LOW,
        profiles=(PROFILE_BALANCED, PROFILE_ADVANCED),
        requires_cache=True,
        requires_spotify_closed=True,
        reversible=False,
    ),
    OperationSpec(
        id="startup.run_entry",
        name="Remove Spotify autostart entries",
        summary="Stop Spotify from launching itself when you sign in to Windows.",
        detail=(
            "Removes Spotify values from HKCU\\Software\\Microsoft\\Windows\\"
            "CurrentVersion\\Run. The original command line is backed up and can be "
            "restored exactly."
        ),
        rationale=(
            "If you never asked Spotify to start with Windows, removing the entry stops "
            "a background process from consuming memory before you use the app."
        ),
        risk=Risk.MEDIUM,
        profiles=(PROFILE_BALANCED, PROFILE_ADVANCED),
        requires_registry=True,
        requires_spotify_closed=False,
        requires_restart=False,
        docs="Settings > Apps > Startup, or Task Manager > Startup apps",
    ),
    OperationSpec(
        id="prefs.autostart",
        name="Set Spotify's internal autostart mode to off",
        summary="Write app.autostart-mode=off into Spotify's preferences.",
        detail=(
            "Writes a preference key that Spotify is not documented to expose. It is "
            "offered for advanced users only and may have no effect on your version."
        ),
        rationale=(
            "Some Spotify builds read this key in addition to the Windows Run entry. "
            "Support cannot be established for all versions, so it is opt-in."
        ),
        risk=Risk.MEDIUM,
        profiles=(PROFILE_ADVANCED,),
        requires_prefs=True,
        requires_spotify_closed=True,
        requires_restart=True,
        unverified=True,
    ),
    OperationSpec(
        id="spicetify.extensions",
        name="Disable selected Spicetify extensions",
        summary="Remove chosen extensions from the Spicetify configuration.",
        detail=(
            "Removes only the extensions you tick from AdditionalOptions/extensions in "
            "config-xpui.ini and runs 'spicetify apply'."
        ),
        rationale=(
            "Each extension runs inside the Spotify renderer; unused ones cost memory "
            "and CPU. Removing them is reversible from the backup."
        ),
        risk=Risk.MEDIUM,
        profiles=(PROFILE_ADVANCED,),
        requires_spicetify=True,
        requires_spotify_closed=True,
        requires_restart=True,
        reversible=True,
        docs="Requires Spicetify; run 'spicetify restore' to remove all patches.",
    ),
    OperationSpec(
        id="spicetify.custom_apps",
        name="Disable selected Spicetify custom apps",
        summary="Remove chosen custom apps from the Spicetify configuration.",
        detail="Removes only the apps you tick from AdditionalOptions/custom_apps.",
        rationale="Custom apps are full web apps loaded into the Spotify client.",
        risk=Risk.MEDIUM,
        profiles=(PROFILE_ADVANCED,),
        requires_spicetify=True,
        requires_spotify_closed=True,
        requires_restart=True,
        reversible=True,
    ),
)

OPERATIONS_BY_ID: dict[str, OperationSpec] = {op.id: op for op in OPERATIONS}


def operations_for_profile(profile: str) -> list[str]:
    """Operation ids enabled by a named profile (empty for 'custom')."""
    if profile == PROFILE_CUSTOM:
        return []
    return [op.id for op in OPERATIONS if profile in op.profiles]


# ---------------------------------------------------------------------------
# Request / plan
# ---------------------------------------------------------------------------

@dataclass
class OptimizationRequest:
    operations: set[str] = field(default_factory=set)
    cache_size_mb: int = 512
    spicetify_extensions: list[str] = field(default_factory=list)
    spicetify_apps: list[str] = field(default_factory=list)

    def selected(self) -> list[OperationSpec]:
        """Selected operations in registry order (unknown ids are ignored)."""
        return [op for op in OPERATIONS if op.id in self.operations]


@dataclass
class Change:
    operation_id: str
    kind: str  # prefs | registry | cache | spicetify
    description: str
    target: str
    before: Optional[str] = None
    after: Optional[str] = None
    size_bytes: int = 0
    requires_restart: bool = False
    critical: bool = False
    payload: dict = field(default_factory=dict)

    def key(self) -> tuple[str, str, str]:
        return (self.kind, self.target, self.operation_id)


@dataclass
class SkippedOperation:
    operation_id: str
    reason: str


@dataclass
class Plan:
    request: OptimizationRequest
    changes: list[Change] = field(default_factory=list)
    skipped: list[SkippedOperation] = field(default_factory=list)
    backup_targets: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unsupported: list[SkippedOperation] = field(default_factory=list)

    @property
    def requires_spotify_closed(self) -> bool:
        return any(
            OPERATIONS_BY_ID.get(change.operation_id) is not None
            and OPERATIONS_BY_ID[change.operation_id].requires_spotify_closed
            for change in self.changes
        )

    @property
    def requires_restart(self) -> bool:
        return any(change.requires_restart for change in self.changes)

    @property
    def cache_bytes(self) -> int:
        return sum(c.size_bytes for c in self.changes if c.kind == "cache")

    @property
    def files_to_modify(self) -> list[str]:
        seen: list[str] = []
        for change in self.changes:
            if change.kind in ("prefs", "spicetify") and change.target not in seen:
                seen.append(change.target)
        return seen

    @property
    def registry_changes(self) -> list[Change]:
        return [c for c in self.changes if c.kind == "registry"]

    @property
    def cache_directories(self) -> list[str]:
        return [c.target for c in self.changes if c.kind == "cache"]

    def is_empty(self) -> bool:
        return not self.changes

    def describe(self) -> list[str]:
        """Human-readable preview lines describing real planned changes."""
        lines: list[str] = []
        if not self.changes:
            lines.append("No changes to apply.")
        for change in self.changes:
            if change.kind == "prefs":
                key = change.payload.get("key", change.operation_id)
                lines.append(
                    f"Preference {key}: {change.before or '(unset)'} -> {change.after}"
                    f"  ({Path(change.target).name})"
                )
            elif change.kind == "registry":
                lines.append(
                    f"Remove startup entry '{change.target}' "
                    f"(currently: {change.before or 'unknown'})"
                )
            elif change.kind == "cache":
                lines.append(
                    f"Delete contents of {change.description} "
                    f"({_format_bytes(change.size_bytes)})"
                )
            elif change.kind == "spicetify":
                lines.append(f"Spicetify: {change.description}")
        for skipped in self.skipped:
            lines.append(f"Skip {skipped.operation_id}: {skipped.reason}")
        for note in self.notes:
            lines.append(note)
        return lines

    def summary(self) -> str:
        parts = [f"{len(self.changes)} planned change(s)"]
        if self.cache_bytes:
            parts.append(f"{_format_bytes(self.cache_bytes)} of disposable cache")
        if self.requires_spotify_closed:
            parts.append("Spotify must be closed")
        if self.requires_restart:
            parts.append("restart required to take effect")
        return " • ".join(parts)


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def request_from_settings(settings) -> OptimizationRequest:
    """
    Translate the GUI's checkbox object into an explicit operation request.

    Duck-typed on purpose so this module never imports the engine.
    """
    operations: set[str] = set()
    if getattr(settings, "disable_hw_accel", False):
        operations.add("prefs.hardware_acceleration")
    if getattr(settings, "set_cache_size", False):
        operations.add("prefs.cache_size")
    if getattr(settings, "clean_browser_cache", False):
        operations.add("cache.browser")
    if getattr(settings, "clean_code_cache", False):
        operations.add("cache.code")
    if getattr(settings, "clean_gpu_cache", False):
        operations.add("cache.gpu")
    if getattr(settings, "disable_autostart", False):
        operations.add("startup.run_entry")
    if getattr(settings, "set_autostart_pref", False):
        operations.add("prefs.autostart")
    extensions = list(getattr(settings, "disable_spicetify_extensions", []) or [])
    apps = list(getattr(settings, "disable_spicetify_apps", []) or [])
    if extensions:
        operations.add("spicetify.extensions")
    if apps:
        operations.add("spicetify.custom_apps")

    cache_size = int(getattr(settings, "cache_size_mb", 512) or 512)
    return OptimizationRequest(
        operations=operations,
        cache_size_mb=max(0, min(cache_size, 10240)),
        spicetify_extensions=extensions,
        spicetify_apps=apps,
    )


def build_plan(
    request: OptimizationRequest,
    env: Environment,
    *,
    registry: Optional[RegistryManager] = None,
) -> Plan:
    """Build a read-only plan describing exactly what would change."""
    plan = Plan(request=request)
    registry_mgr = registry or RegistryManager()
    install = env.installation

    prefs = (
        PrefsManager(install.prefs_path)
        if install is not None and install.prefs_path
        else None
    )
    prefs_values: dict[str, str] = {}
    if prefs is not None and env.prefs_readable:
        prefs_values = prefs.read_all()
        plan.backup_targets.append(Path(install.prefs_path))  # type: ignore[arg-type]

    cache_mgr = (
        CacheManager(env.cache_root) if env.cache_root is not None else None
    )
    inventory_cache: dict[str, list] = {}
    if cache_mgr is not None and env.cache_readable:
        inventory_cache = cache_mgr.inventory_by_group()

    if env.spicetify_available and install is not None and install.spicetify:
        if install.spicetify.config_path:
            plan.backup_targets.append(Path(install.spicetify.config_path))

    for op in request.selected():
        verdict = op.compatibility(env)
        if not verdict.usable:
            plan.unsupported.append(SkippedOperation(op.id, verdict.reason))
            continue

        if op.id == "prefs.hardware_acceleration" and prefs is not None:
            before = prefs_values.get("hardware_acceleration_mode_enabled")
            if before == "false":
                plan.skipped.append(SkippedOperation(op.id, "already disabled"))
                continue
            plan.changes.append(Change(
                operation_id=op.id,
                kind="prefs",
                description="Spotify prefs file",
                target=str(prefs.path),
                before=before,
                after="false",
                requires_restart=True,
                critical=True,
                payload={"key": "hardware_acceleration_mode_enabled",
                         "value": "false"},
            ))

        elif op.id == "prefs.cache_size" and prefs is not None:
            after = build_cache_size_pref(request.cache_size_mb)["storage.size"]
            before = prefs_values.get("storage.size")
            if before == after:
                plan.skipped.append(SkippedOperation(op.id, "already set"))
                continue
            plan.changes.append(Change(
                operation_id=op.id,
                kind="prefs",
                description="Spotify prefs file",
                target=str(prefs.path),
                before=before,
                after=after,
                requires_restart=True,
                critical=True,
                payload={"key": "storage.size", "value": after},
            ))

        elif op.id == "prefs.autostart" and prefs is not None:
            after = build_autostart_pref("off")["app.autostart-mode"]
            before = prefs_values.get("app.autostart-mode")
            if before == after:
                plan.skipped.append(SkippedOperation(op.id, "already set"))
                continue
            plan.changes.append(Change(
                operation_id=op.id,
                kind="prefs",
                description="Spotify prefs file",
                target=str(prefs.path),
                before=before,
                after=after,
                requires_restart=True,
                critical=True,
                payload={"key": "app.autostart-mode", "value": after},
            ))

        elif op.id == "startup.run_entry":
            entries = registry_mgr.get_spotify_startup_entries()
            if not entries:
                plan.skipped.append(SkippedOperation(op.id, "no Spotify startup entry found"))
                continue
            for name, command in entries.items():
                if name.lower() not in {"spotify", "spotifywebhelper"}:
                    plan.skipped.append(SkippedOperation(
                        op.id, f"entry '{name}' has an unrecognised name and is left alone"
                    ))
                    continue
                plan.changes.append(Change(
                    operation_id=op.id,
                    kind="registry",
                    description=f"Startup entry {name}",
                    target=name,
                    before=command,
                    after=None,
                    critical=False,
                    payload={},
                ))

        elif op.id in ("cache.browser", "cache.code", "cache.gpu"):
            group = op.id.split(".", 1)[1]
            infos = inventory_cache.get(group, [])
            eligible = [info for info in infos if info.eligible and info.size_bytes > 0]
            if not eligible:
                plan.skipped.append(SkippedOperation(
                    op.id, "no removable cache files found"
                ))
                continue
            for info in eligible:
                plan.changes.append(Change(
                    operation_id=op.id,
                    kind="cache",
                    description=f"{GROUP_LABELS.get(group, group)} ({info.relative})",
                    target=str(info.path),
                    before=_format_bytes(info.size_bytes),
                    after="0",
                    size_bytes=info.size_bytes,
                    requires_restart=False,
                    critical=False,
                    payload={"group": group, "relative": info.relative},
                ))

        elif op.id == "spicetify.extensions":
            if not request.spicetify_extensions:
                plan.skipped.append(SkippedOperation(op.id, "no extensions selected"))
                continue
            plan.changes.append(Change(
                operation_id=op.id,
                kind="spicetify",
                description=f"remove extensions: {', '.join(request.spicetify_extensions)}",
                target=str(install.spicetify.config_path),  # type: ignore[union-attr]
                before="|".join(request.spicetify_extensions),
                after="",
                requires_restart=True,
                critical=False,
                payload={"extensions": list(request.spicetify_extensions)},
            ))

        elif op.id == "spicetify.custom_apps":
            if not request.spicetify_apps:
                plan.skipped.append(SkippedOperation(op.id, "no custom apps selected"))
                continue
            plan.changes.append(Change(
                operation_id=op.id,
                kind="spicetify",
                description=f"remove custom apps: {', '.join(request.spicetify_apps)}",
                target=str(install.spicetify.config_path),  # type: ignore[union-attr]
                before="|".join(request.spicetify_apps),
                after="",
                requires_restart=True,
                critical=False,
                payload={"apps": list(request.spicetify_apps)},
            ))

    if plan.changes and not plan.notes:
        plan.notes.append(
            "A timestamped backup is created and verified before any change is applied."
        )
    return plan


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@dataclass
class ChangeOutcome:
    change: Change
    status: str  # applied | failed | skipped | unchanged
    detail: str = ""
    verified: Optional[bool] = None


@dataclass
class ExecutionReport:
    outcomes: list[ChangeOutcome] = field(default_factory=list)
    rolled_back: bool = False
    rollback_details: list[str] = field(default_factory=list)
    spicetify_message: str = ""

    @property
    def applied(self) -> list[ChangeOutcome]:
        return [o for o in self.outcomes if o.status == "applied"]

    @property
    def failed(self) -> list[ChangeOutcome]:
        return [o for o in self.outcomes if o.status == "failed"]

    @property
    def skipped(self) -> list[ChangeOutcome]:
        return [o for o in self.outcomes if o.status in ("skipped", "unchanged")]

    @property
    def verified(self) -> list[ChangeOutcome]:
        return [o for o in self.outcomes if o.verified is True]


class Optimizer:
    """Applies a :class:`Plan` change by change, verifying each step."""

    def __init__(
        self,
        env: Environment,
        *,
        registry: Optional[RegistryManager] = None,
    ) -> None:
        self.env = env
        self.registry = registry or RegistryManager()
        install = env.installation
        self._prefs = (
            PrefsManager(install.prefs_path)
            if install is not None and install.prefs_path
            else None
        )
        self._cache = CacheManager(env.cache_root) if env.cache_root else None
        self._spicetify = (
            SpicetifyManager(install.spicetify)
            if install is not None and install.spicetify
            else None
        )

    # -- apply ---------------------------------------------------------

    def apply(self, plan: Plan, *, allow_registry: bool = True) -> ExecutionReport:
        report = ExecutionReport()

        for change in plan.changes:
            if change.kind == "registry" and not allow_registry:
                report.outcomes.append(ChangeOutcome(
                    change, "skipped",
                    "registry changes are disabled in this context",
                ))
                continue
            if change.kind == "cache" and self.env.spotify_running:
                report.outcomes.append(ChangeOutcome(
                    change, "skipped",
                    "Spotify is running; cache files are locked. Close Spotify first.",
                ))
                continue
            try:
                outcome = self._apply_change(change)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception(f"Unexpected failure applying {change.operation_id}")
                outcome = ChangeOutcome(change, "failed", str(exc))
            report.outcomes.append(outcome)

        # Spicetify needs one apply after config edits.
        spicetify_changes = [
            o for o in report.outcomes
            if o.change.kind == "spicetify" and o.status == "applied"
        ]
        if spicetify_changes and self._spicetify is not None:
            ok, message = self._spicetify.run_apply()
            report.spicetify_message = message
            if not ok:
                for outcome in spicetify_changes:
                    outcome.status = "failed"
                    outcome.detail = f"spicetify apply failed: {message}"
                    outcome.verified = False

        if any(o.status == "failed" for o in report.outcomes
               if o.change.critical):
            report.rollback_details = self.rollback(plan, report)
            report.rolled_back = True

        return report

    def _apply_change(self, change: Change) -> ChangeOutcome:
        if change.kind == "prefs":
            return self._apply_prefs(change)
        if change.kind == "registry":
            return self._apply_registry(change)
        if change.kind == "cache":
            return self._apply_cache(change)
        if change.kind == "spicetify":
            return self._apply_spicetify(change)
        return ChangeOutcome(change, "skipped", "unknown change type")

    def _apply_prefs(self, change: Change) -> ChangeOutcome:
        if self._prefs is None:
            return ChangeOutcome(change, "skipped", "Spotify prefs file unavailable")
        key = change.payload.get("key")
        value = change.payload.get("value")
        if not key or value is None:
            return ChangeOutcome(change, "failed", "malformed plan entry")
        if not self._prefs.set_values({key: value}):
            return ChangeOutcome(change, "failed", "could not write prefs")
        verified = self._prefs.verify({key: value}).get(key, False)
        return ChangeOutcome(
            change, "applied" if verified else "failed",
            "" if verified else "value was not present after writing",
            verified,
        )

    def _apply_registry(self, change: Change) -> ChangeOutcome:
        ok = self.registry.disable_startup_entry(
            change.target, require_spotify_value=True
        )
        if not ok:
            return ChangeOutcome(change, "failed", "could not remove startup entry")
        remaining = self.registry.get_spotify_startup_entries()
        verified = change.target not in remaining
        return ChangeOutcome(
            change, "applied" if verified else "failed",
            "" if verified else "entry is still present",
            verified,
        )

    def _apply_cache(self, change: Change) -> ChangeOutcome:
        if self._cache is None:
            return ChangeOutcome(change, "skipped", "cache directory unavailable")
        group = change.payload.get("group")
        if group not in CACHE_GROUPS:
            return ChangeOutcome(change, "failed", "unknown cache group")
        stats = self._cache.clean_groups([group])
        remaining = self._cache.get_cache_size(change.payload.get("relative"))
        verified = remaining == 0
        detail = f"{stats.freed_mb} MB freed, {stats.files_deleted} entries removed"
        if stats.errors:
            detail += f"; {len(stats.errors)} item(s) skipped"
        if remaining != 0 and not stats.files_deleted:
            return ChangeOutcome(change, "failed", detail or "nothing removed", False)
        return ChangeOutcome(change, "applied", detail, verified)

    def _apply_spicetify(self, change: Change) -> ChangeOutcome:
        if self._spicetify is None:
            return ChangeOutcome(change, "skipped", "Spicetify unavailable")
        if "extensions" in change.payload:
            ok = self._spicetify.disable_extensions(change.payload["extensions"])
        else:
            ok = self._spicetify.disable_custom_apps(change.payload.get("apps", []))
        return ChangeOutcome(
            change,
            "applied" if ok else "failed",
            "" if ok else "could not update Spicetify config",
            ok or None,
        )

    # -- rollback ------------------------------------------------------

    def rollback(
        self,
        plan: Plan,
        report: ExecutionReport,
        *,
        spicetify_backup: Optional[Path] = None,
    ) -> list[str]:
        """
        Undo applied preference and registry changes.

        Cache cleanup is inherently irreversible (the files are disposable) and
        is reported as such rather than silently skipped.
        """
        details: list[str] = []
        applied = [o for o in report.outcomes if o.status == "applied"]

        # Restore prefs first, in reverse order.
        prefs_updates: dict[str, Optional[str]] = {}
        for outcome in reversed(applied):
            if outcome.change.kind == "prefs":
                key = outcome.change.payload.get("key")
                if key:
                    prefs_updates[key] = outcome.change.before
        if prefs_updates and self._prefs is not None:
            if self._prefs.apply_changes(prefs_updates):
                details.append(
                    f"Restored {len(prefs_updates)} preference key(s) to their original values."
                )
            else:
                details.append("Could not restore preference values; use the backup session.")

        for outcome in reversed(applied):
            change = outcome.change
            if change.kind == "registry" and change.before:
                if self.registry.enable_startup_entry(change.target, change.before):
                    details.append(f"Restored startup entry '{change.target}'.")

        if spicetify_backup is not None and any(
            o.change.kind == "spicetify" for o in applied
        ):
            install = self.env.installation
            if (
                install is not None
                and install.spicetify
                and install.spicetify.config_path
                and spicetify_backup.exists()
            ):
                from .backup_manager import restore_file_checked
                ok, message = restore_file_checked(
                    spicetify_backup, install.spicetify.config_path
                )
                details.append(
                    "Restored Spicetify config." if ok else f"Spicetify restore failed: {message}"
                )
                if ok and self._spicetify is not None:
                    self._spicetify.run_apply()

        cache_count = sum(1 for o in applied if o.change.kind == "cache")
        if cache_count:
            details.append(
                f"{cache_count} cache cleanup(s) cannot be undone — those files are "
                "disposable and are re-downloaded by Spotify."
            )
        return details


__all__ = [
    "Change", "ChangeOutcome", "ExecutionReport", "OPERATIONS",
    "OPERATIONS_BY_ID", "OperationSpec", "OptimizationRequest", "Optimizer",
    "PROFILE_ADVANCED", "PROFILE_BALANCED", "PROFILE_CUSTOM", "PROFILE_SAFE",
    "PROFILE_DESCRIPTIONS", "Plan", "Risk", "SkippedOperation", "SupportLevel",
    "build_plan", "operations_for_profile", "request_from_settings",
]
