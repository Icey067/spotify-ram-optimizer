"""
Settings panel — user-configurable optimization options (Optimizations page).
"""
from __future__ import annotations

from typing import Callable, Optional
import customtkinter as ctk

from src.core.engine import OptimizationSettings
from .theme import ACCENT, ACCENT_HOVER, MUTED, SUBTLE, SURFACE_RAISED, TEXT


class SettingsPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, on_run: Optional[Callable] = None, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.on_run = on_run
        self._vars: dict[str, ctk.BooleanVar | ctk.IntVar | ctk.StringVar] = {}
        self._spicetify_ext_vars: dict[str, ctk.BooleanVar] = {}
        self._spicetify_app_vars: dict[str, ctk.BooleanVar] = {}
        self._spicetify_section: ctk.CTkFrame | None = None
        self._defaults: dict[str, bool | int] = {}
        self._action_buttons: list[ctk.CTkButton] = []
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        row = 0

        hero = ctk.CTkFrame(self, fg_color=SURFACE_RAISED, corner_radius=14)
        hero.grid(row=row, column=0, sticky="ew", padx=12, pady=(14, 8))
        hero.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hero, text="Choose your optimization plan", text_color=TEXT,
                     font=ctk.CTkFont(size=18, weight="bold")).grid(
                         row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        ctk.CTkLabel(hero, text="Recommended options are selected by default. A backup is created automatically before optimization.",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).grid(
                         row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        btn_box = ctk.CTkFrame(hero, fg_color="transparent")
        btn_box.grid(row=0, column=1, rowspan=2, padx=14, pady=12, sticky="e")

        btn_reset = ctk.CTkButton(
            btn_box, text="Reset defaults", width=110, height=32,
            command=self.reset_defaults, fg_color="#343941", hover_color="#454B55"
        )
        btn_reset.pack(side="left", padx=(0, 8))
        self._action_buttons.append(btn_reset)

        if self.on_run:
            btn_run = ctk.CTkButton(
                btn_box, text="⚡  Optimize Spotify", width=140, height=32,
                command=self.on_run, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                text_color="#08120C", font=ctk.CTkFont(size=12, weight="bold")
            )
            btn_run.pack(side="left")
            self._action_buttons.append(btn_run)

        row += 1

        # ---- Preferences ----
        row = self._section(row, "Spotify Preferences")
        row = self._checkbox(row, "disable_hw_accel", "Disable Hardware Acceleration",
                             default=True,
                             tip="Reduces GPU usage and Chromium compositor overhead. Requires Spotify restart.")
        row = self._checkbox(row, "disable_autostart", "Disable Spotify Autostart",
                             default=True,
                             tip="Removes Spotify from Windows startup entries (HKCU\\...\\Run).")
        row = self._checkbox(row, "set_cache_size", "Limit Cache Size",
                             default=True)
        row = self._slider_row(row, "cache_size_mb", "Cache Size (MB)",
                               min_val=0, max_val=2048, default=512,
                               step=64)

        # ---- Cache Cleanup ----
        row = self._section(row, "Cache Cleanup")
        row = self._checkbox(row, "clean_browser_cache", "Clear Browser Cache",
                             default=True,
                             tip="Clears Spotify's HTTP tile cache. Disposable temporary files.")
        row = self._checkbox(row, "clean_code_cache", "Clear Code Cache",
                             default=True,
                             tip="Clears compiled JavaScript bytecode cache.")
        row = self._checkbox(row, "clean_gpu_cache", "Clear GPU Shader Cache",
                             default=False,
                             tip="Clears shader cache (disabled by default — optional).")

        # ---- Spicetify ----
        self._spicetify_section = ctk.CTkFrame(self, fg_color="transparent")
        self._spicetify_section.grid(
            row=row, column=0, sticky="ew", padx=8, pady=(12, 0)
        )
        row += 1
        self._spicetify_section.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self._spicetify_section,
            text="SPICETIFY CUSTOMIZATIONS", text_color=ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(4, 2))
        self._spicetify_inner = ctk.CTkFrame(
            self._spicetify_section, fg_color="transparent"
        )
        self._spicetify_inner.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            self._spicetify_inner,
            text="Spicetify not detected on this system.",
            font=ctk.CTkFont(size=12),
            text_color="#888888",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=4)

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in self._action_buttons:
            btn.configure(state=state)

    def _section(self, row: int, title: str) -> int:
        ctk.CTkLabel(
            self,
            text=title.upper(), text_color=ACCENT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(14, 2))
        return row + 1

    def _checkbox(self, row: int, key: str, label: str,
                  default: bool = True, tip: str = "") -> int:
        var = ctk.BooleanVar(value=default)
        self._vars[key] = var
        self._defaults[key] = default
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=8, pady=2)
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkCheckBox(frame, text=label, variable=var).grid(
            row=0, column=0, sticky="w"
        )
        if tip:
            ctk.CTkLabel(
                frame, text=tip, font=ctk.CTkFont(size=11), text_color=SUBTLE
            ).grid(row=1, column=0, sticky="w", padx=24)
        return row + 1

    def _slider_row(self, row: int, key: str, label: str,
                    min_val: int, max_val: int, default: int, step: int = 1) -> int:
        var = ctk.IntVar(value=default)
        self._vars[key] = var
        self._defaults[key] = default
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=24, pady=2)
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        value_lbl = ctk.CTkLabel(frame, text=f"{default} MB", font=ctk.CTkFont(size=12, weight="bold"), width=58)
        value_lbl.grid(row=0, column=2, padx=8)

        def on_change(v):
            snapped = round(float(v) / step) * step
            var.set(snapped)
            value_lbl.configure(text=f"{snapped} MB")

        var.trace_add("write", lambda *_: value_lbl.configure(text=f"{var.get()} MB"))

        ctk.CTkSlider(
            frame, variable=var,
            from_=min_val, to=max_val,
            command=on_change,
        ).grid(row=0, column=1, sticky="ew")
        return row + 1

    def reset_defaults(self) -> None:
        """Return the core options to the safe recommended selection."""
        for key, value in self._defaults.items():
            variable = self._vars.get(key)
            if variable is not None:
                variable.set(value)
        for variable in self._spicetify_ext_vars.values():
            variable.set(False)
        for variable in self._spicetify_app_vars.values():
            variable.set(False)

    def update_spicetify(self, extensions: list[str], custom_apps: list[str]) -> None:
        for widget in self._spicetify_inner.winfo_children():
            widget.destroy()
        self._spicetify_ext_vars.clear()
        self._spicetify_app_vars.clear()

        r = 0
        if extensions:
            ctk.CTkLabel(
                self._spicetify_inner,
                text="Extensions (optional — select to disable):",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=r, column=0, sticky="w", padx=8, pady=(4, 2))
            r += 1
            for ext in extensions:
                var = ctk.BooleanVar(value=False)
                self._spicetify_ext_vars[ext] = var
                ctk.CTkCheckBox(
                    self._spicetify_inner,
                    text=f"Disable: {ext}",
                    variable=var,
                ).grid(row=r, column=0, sticky="w", padx=24, pady=1)
                r += 1

        if custom_apps:
            ctk.CTkLabel(
                self._spicetify_inner,
                text="Custom Apps (optional — select to disable):",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=r, column=0, sticky="w", padx=8, pady=(8, 2))
            r += 1
            for app in custom_apps:
                var = ctk.BooleanVar(value=False)
                self._spicetify_app_vars[app] = var
                ctk.CTkCheckBox(
                    self._spicetify_inner,
                    text=f"Disable: {app}",
                    variable=var,
                ).grid(row=r, column=0, sticky="w", padx=24, pady=1)
                r += 1

        if not extensions and not custom_apps:
            ctk.CTkLabel(
                self._spicetify_inner,
                text="Spicetify detected, but no extensions or custom apps found.",
                font=ctk.CTkFont(size=12),
                text_color="#888888",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=4)

    def get_settings(self) -> OptimizationSettings:
        def bv(key: str, default: bool = False) -> bool:
            v = self._vars.get(key)
            return bool(v.get()) if isinstance(v, ctk.BooleanVar) else default

        def iv(key: str, default: int = 0) -> int:
            v = self._vars.get(key)
            return int(v.get()) if isinstance(v, ctk.IntVar) else default

        return OptimizationSettings(
            disable_hw_accel=bv("disable_hw_accel", True),
            set_cache_size=bv("set_cache_size", True),
            cache_size_mb=iv("cache_size_mb", 512),
            disable_autostart=bv("disable_autostart", True),
            clean_browser_cache=bv("clean_browser_cache", True),
            clean_code_cache=bv("clean_code_cache", True),
            clean_gpu_cache=bv("clean_gpu_cache", False),
            disable_spicetify_extensions=[
                ext for ext, var in self._spicetify_ext_vars.items() if var.get()
            ],
            disable_spicetify_apps=[
                app for app, var in self._spicetify_app_vars.items() if var.get()
            ],
        )
