"""
Optimizations page.

The operation list is generated from :mod:`src.core.optimizations`; this panel
never hardcodes what the engine supports.  Each row shows the operation's real
risk level and its compatibility verdict for the current machine.
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from src.core.compatibility import Environment
from src.core.engine import OptimizationSettings
from src.core.optimizations import (
    OPERATIONS,
    PROFILE_ADVANCED,
    PROFILE_BALANCED,
    PROFILE_CUSTOM,
    PROFILE_DESCRIPTIONS,
    PROFILE_SAFE,
    Risk,
    operations_for_profile,
)

from .theme import (
    ACCENT, ACCENT_HOVER, BORDER, ERROR, MUTED, SUBTLE, SUCCESS,
    SURFACE, SURFACE_RAISED, TEXT, WARNING,
)

PROFILE_LABELS = {
    "Safe": PROFILE_SAFE,
    "Balanced": PROFILE_BALANCED,
    "Advanced": PROFILE_ADVANCED,
    "Custom": PROFILE_CUSTOM,
}
LABEL_FOR_PROFILE = {value: key for key, value in PROFILE_LABELS.items()}

RISK_COLORS = {
    Risk.LOW: SUCCESS,
    Risk.MEDIUM: WARNING,
    Risk.HIGH: ERROR,
}


class SettingsPanel(ctk.CTkScrollableFrame):
    def __init__(
        self,
        master,
        on_run: Optional[Callable] = None,
        on_preview: Optional[Callable] = None,
        on_profile_change: Optional[Callable[[str], None]] = None,
        on_export_profile: Optional[Callable] = None,
        on_import_profile: Optional[Callable] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_run = on_run
        self.on_preview = on_preview
        self.on_profile_change = on_profile_change
        self.on_export_profile = on_export_profile
        self.on_import_profile = on_import_profile
        self._op_vars: dict[str, ctk.BooleanVar] = {}
        self._op_rows: dict[str, dict] = {}
        self._compat_labels: dict[str, ctk.CTkLabel] = {}
        self._spicetify_ext_vars: dict[str, ctk.BooleanVar] = {}
        self._spicetify_app_vars: dict[str, ctk.BooleanVar] = {}
        self._action_buttons: list[ctk.CTkButton] = []
        self._profile = PROFILE_SAFE
        self._build()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        row = 0

        hero = ctk.CTkFrame(self, fg_color=SURFACE_RAISED, corner_radius=14)
        hero.grid(row=row, column=0, sticky="ew", padx=12, pady=(14, 8))
        hero.grid_columnconfigure(0, weight=1)
        row += 1

        ctk.CTkLabel(hero, text="Choose your optimization plan", text_color=TEXT,
                     font=ctk.CTkFont(size=18, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        self._profile_description = ctk.CTkLabel(
            hero,
            text=PROFILE_DESCRIPTIONS[self._profile],
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            justify="left",
            wraplength=520,
        )
        self._profile_description.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        controls = ctk.CTkFrame(hero, fg_color="transparent")
        controls.grid(row=0, column=1, rowspan=2, padx=14, pady=12, sticky="e")

        ctk.CTkLabel(controls, text="Profile", text_color=SUBTLE,
                     font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w")
        self.profile_menu = ctk.CTkOptionMenu(
            controls, values=list(PROFILE_LABELS), width=130,
            command=self._handle_profile_change,
        )
        self.profile_menu.set(LABEL_FOR_PROFILE[self._profile])
        self.profile_menu.pack(anchor="w", pady=(2, 8))

        buttons = ctk.CTkFrame(controls, fg_color="transparent")
        buttons.pack(anchor="e")
        btn_reset = ctk.CTkButton(
            buttons, text="Reset", width=74, height=30,
            command=self.reset_defaults, fg_color="#343941", hover_color="#454B55",
        )
        btn_reset.pack(side="left", padx=(0, 6))
        self._action_buttons.append(btn_reset)

        if self.on_preview:
            btn_preview = ctk.CTkButton(
                buttons, text="Preview", width=90, height=30, command=self.on_preview,
                fg_color="#27303B", hover_color="#333E4C",
            )
            btn_preview.pack(side="left", padx=(0, 6))
            self._action_buttons.append(btn_preview)

        if self.on_run:
            btn_run = ctk.CTkButton(
                buttons, text="⚡  Optimize", width=120, height=30,
                command=self.on_run, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                text_color="#08120C", font=ctk.CTkFont(size=12, weight="bold"),
            )
            btn_run.pack(side="left")
            self._action_buttons.append(btn_run)

        if self.on_export_profile or self.on_import_profile:
            profile_row = ctk.CTkFrame(controls, fg_color="transparent")
            profile_row.pack(anchor="e", pady=(6, 0))
            if self.on_import_profile:
                button = ctk.CTkButton(
                    profile_row, text="Import profile", width=112, height=26,
                    command=self.on_import_profile, fg_color="#27303B",
                    hover_color="#333E4C", font=ctk.CTkFont(size=11))
                button.pack(side="left", padx=(0, 6))
                self._action_buttons.append(button)
            if self.on_export_profile:
                button = ctk.CTkButton(
                    profile_row, text="Export profile", width=112, height=26,
                    command=self.on_export_profile, fg_color="#27303B",
                    hover_color="#333E4C", font=ctk.CTkFont(size=11))
                button.pack(side="left")
                self._action_buttons.append(button)

        row = self._section(row, "Spotify preferences")
        row = self._operation_row(row, "prefs.hardware_acceleration")
        row = self._operation_row(row, "prefs.cache_size")
        row = self._cache_size_row(row)
        row = self._operation_row(row, "prefs.autostart")

        row = self._section(row, "Startup")
        row = self._operation_row(row, "startup.run_entry")

        row = self._section(row, "Cache cleanup")
        row = self._operation_row(row, "cache.browser")
        row = self._operation_row(row, "cache.code")
        row = self._operation_row(row, "cache.gpu")

        # ---- Spicetify ----
        self._spicetify_section = ctk.CTkFrame(self, fg_color="transparent")
        self._spicetify_section.grid(row=row, column=0, sticky="ew", padx=8, pady=(12, 0))
        self._spicetify_section.grid_columnconfigure(0, weight=1)
        row += 1
        ctk.CTkLabel(
            self._spicetify_section, text="SPICETIFY CUSTOMIZATIONS", text_color=ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(4, 2))
        self._spicetify_inner = ctk.CTkFrame(self._spicetify_section, fg_color="transparent")
        self._spicetify_inner.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            self._spicetify_inner, text="Spicetify not detected on this system.",
            font=ctk.CTkFont(size=12), text_color=SUBTLE,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=4)

        self.apply_profile(self._profile, notify=False)

    def _section(self, row: int, title: str) -> int:
        ctk.CTkLabel(
            self, text=title.upper(), text_color=ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(14, 2))
        return row + 1

    def _operation_row(self, row: int, operation_id: str) -> int:
        """Render one registry operation with risk and compatibility badges."""
        spec = next((op for op in OPERATIONS if op.id == operation_id), None)
        if spec is None:
            return row

        card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10,
                            border_width=1, border_color=BORDER)
        card.grid(row=row, column=0, sticky="ew", padx=8, pady=3)
        card.grid_columnconfigure(0, weight=1)

        var = ctk.BooleanVar(value=False)
        self._op_vars[spec.id] = var
        checkbox = ctk.CTkCheckBox(
            card, text=spec.name, variable=var,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._mark_custom,
        )
        checkbox.grid(row=0, column=0, padx=14, pady=(10, 0), sticky="w")

        risk_label = ctk.CTkLabel(
            card, text=spec.risk.value.upper(), text_color=RISK_COLORS[spec.risk],
            fg_color=SURFACE_RAISED, corner_radius=8, padx=8, pady=2,
            font=ctk.CTkFont(size=9, weight="bold"),
        )
        risk_label.grid(row=0, column=1, padx=(0, 6), pady=(10, 0), sticky="e")

        if spec.unverified:
            ctk.CTkLabel(
                card, text="UNVERIFIED", text_color=WARNING, fg_color=SURFACE_RAISED,
                corner_radius=8, padx=8, pady=2,
                font=ctk.CTkFont(size=9, weight="bold"),
            ).grid(row=0, column=2, padx=(0, 14), pady=(10, 0), sticky="e")

        ctk.CTkLabel(
            card, text=spec.summary, text_color=MUTED, justify="left",
            wraplength=700, font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, columnspan=3, padx=14, pady=(2, 0), sticky="w")

        compat = ctk.CTkLabel(
            card, text="Checking compatibility…", text_color=SUBTLE,
            justify="left", wraplength=700, font=ctk.CTkFont(size=10),
        )
        compat.grid(row=2, column=0, columnspan=3, padx=14, pady=(2, 10), sticky="w")

        self._compat_labels[spec.id] = compat
        self._op_rows[spec.id] = {"card": card, "checkbox": checkbox, "spec": spec}
        return row + 1

    def _cache_size_row(self, row: int) -> int:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=24, pady=(2, 6))
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text="Cache limit (MB)", font=ctk.CTkFont(size=12),
                     text_color=MUTED).grid(row=0, column=0, sticky="w", padx=(0, 8))

        self._cache_size_var = ctk.IntVar(value=512)
        value_label = ctk.CTkLabel(frame, text="512 MB", width=70,
                                   font=ctk.CTkFont(size=12, weight="bold"))
        value_label.grid(row=0, column=2, padx=8)

        def on_change(value):
            snapped = int(round(float(value) / 64) * 64)
            self._cache_size_var.set(snapped)
            value_label.configure(text=f"{snapped} MB")

        ctk.CTkSlider(frame, variable=self._cache_size_var, from_=0, to=2048,
                      number_of_steps=32, command=on_change).grid(
                          row=0, column=1, sticky="ew")
        self._cache_size_label = value_label
        return row + 1

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _mark_custom(self) -> None:
        if self._profile in (PROFILE_CUSTOM,):
            return
        if set(self.selected_operations()) != set(operations_for_profile(self._profile)):
            self._profile = PROFILE_CUSTOM
            self.profile_menu.set(LABEL_FOR_PROFILE[self._profile])
            self._profile_description.configure(text=PROFILE_DESCRIPTIONS[self._profile])
            if self.on_profile_change:
                self.on_profile_change(self._profile)

    def _handle_profile_change(self, label: str) -> None:
        profile = PROFILE_LABELS.get(label, PROFILE_SAFE)
        self.apply_profile(profile)

    def apply_profile(self, profile: str, *, notify: bool = True) -> None:
        """Select exactly the operations the profile defines."""
        self._profile = profile
        wanted = set(operations_for_profile(profile))
        if profile != PROFILE_CUSTOM:
            for operation_id, var in self._op_vars.items():
                var.set(operation_id in wanted)
        self.profile_menu.set(LABEL_FOR_PROFILE[profile])
        self._profile_description.configure(text=PROFILE_DESCRIPTIONS[profile])
        if notify and self.on_profile_change:
            self.on_profile_change(profile)

    def select_operations(self, operation_ids: list[str]) -> None:
        wanted = set(operation_ids)
        for operation_id, var in self._op_vars.items():
            var.set(operation_id in wanted)
        self._profile = PROFILE_CUSTOM
        self.profile_menu.set(LABEL_FOR_PROFILE[self._profile])
        self._profile_description.configure(text=PROFILE_DESCRIPTIONS[self._profile])

    def selected_operations(self) -> list[str]:
        return [operation_id for operation_id, var in self._op_vars.items() if var.get()]

    @property
    def profile(self) -> str:
        return self._profile

    def set_cache_size(self, size_mb: int) -> None:
        """Set the cache-limit slider from a validated profile value."""
        value = max(0, min(int(size_mb), 2048))
        self._cache_size_var.set(value)
        self._cache_size_label.configure(text=f"{value} MB")

    def get_cache_size_mb(self) -> int:
        return int(self._cache_size_var.get())

    def reset_defaults(self) -> None:
        """Return to the conservative safe profile."""
        self.apply_profile(PROFILE_SAFE, notify=False)
        self._cache_size_var.set(512)
        self._cache_size_label.configure(text="512 MB")
        for variable in self._spicetify_ext_vars.values():
            variable.set(False)
        for variable in self._spicetify_app_vars.values():
            variable.set(False)

    # ------------------------------------------------------------------
    # Compatibility
    # ------------------------------------------------------------------

    def update_compatibility(self, env: Optional[Environment]) -> None:
        """Show the engine's real verdict for each operation."""
        for operation_id, label in self._compat_labels.items():
            row = self._op_rows.get(operation_id)
            if row is None:
                continue
            spec = row["spec"]
            if env is None:
                label.configure(text="Scan Spotify to check compatibility.", text_color=SUBTLE)
                continue
            verdict = spec.compatibility(env)
            color = SUCCESS if verdict.usable else ERROR
            prefix = "✓" if verdict.usable else "✕"
            label.configure(text=f"{prefix} {verdict.level.value} — {verdict.reason}",
                            text_color=color)
            state = "normal" if verdict.usable else "disabled"
            try:
                row["checkbox"].configure(state=state)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Spicetify
    # ------------------------------------------------------------------

    def update_spicetify(self, extensions: list[str], custom_apps: list[str]) -> None:
        for widget in self._spicetify_inner.winfo_children():
            widget.destroy()
        self._spicetify_ext_vars.clear()
        self._spicetify_app_vars.clear()

        row = 0
        if extensions:
            ctk.CTkLabel(
                self._spicetify_inner,
                text="Extensions (select to disable):",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=row, column=0, sticky="w", padx=8, pady=(4, 2))
            row += 1
            for extension in extensions:
                var = ctk.BooleanVar(value=False)
                self._spicetify_ext_vars[extension] = var
                ctk.CTkCheckBox(
                    self._spicetify_inner, text=f"Disable: {extension}", variable=var,
                ).grid(row=row, column=0, sticky="w", padx=24, pady=1)
                row += 1

        if custom_apps:
            ctk.CTkLabel(
                self._spicetify_inner,
                text="Custom apps (select to disable):",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=row, column=0, sticky="w", padx=8, pady=(8, 2))
            row += 1
            for app in custom_apps:
                var = ctk.BooleanVar(value=False)
                self._spicetify_app_vars[app] = var
                ctk.CTkCheckBox(
                    self._spicetify_inner, text=f"Disable: {app}", variable=var,
                ).grid(row=row, column=0, sticky="w", padx=24, pady=1)
                row += 1

        if not extensions and not custom_apps:
            ctk.CTkLabel(
                self._spicetify_inner,
                text="Spicetify detected, but no extensions or custom apps were found.",
                font=ctk.CTkFont(size=12), text_color=SUBTLE,
            ).grid(row=0, column=0, sticky="w", padx=8, pady=4)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def get_settings(self) -> OptimizationSettings:
        selected = set(self.selected_operations())
        return OptimizationSettings(
            disable_hw_accel="prefs.hardware_acceleration" in selected,
            set_cache_size="prefs.cache_size" in selected,
            cache_size_mb=max(0, min(int(self._cache_size_var.get()), 10240)),
            disable_autostart="startup.run_entry" in selected,
            clean_browser_cache="cache.browser" in selected,
            clean_code_cache="cache.code" in selected,
            clean_gpu_cache="cache.gpu" in selected,
            set_autostart_pref="prefs.autostart" in selected,
            disable_spicetify_extensions=[
                name for name, var in self._spicetify_ext_vars.items() if var.get()
            ],
            disable_spicetify_apps=[
                name for name, var in self._spicetify_app_vars.items() if var.get()
            ],
        )

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in self._action_buttons:
            try:
                button.configure(state=state)
            except Exception:
                pass
