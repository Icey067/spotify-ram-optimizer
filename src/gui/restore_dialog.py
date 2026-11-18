"""
Selective restore window.

Implements two things the application previously lacked:

  * per-component restoration (preferences, startup entries, shortcuts,
    Spicetify config) instead of all-or-nothing, and
  * an explicit conflict-resolution step that names the component whose live
    state changed after the snapshot, and only overwrites it when the user says
    so.

The dialog performs no file or registry work itself; it collects a decision and
hands it to the engine, which already knows how to verify and contain it.
"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from .theme import (
    ACCENT, ACCENT_HOVER, BORDER, ERROR, MUTED, SUBTLE, SUCCESS, SURFACE,
    SURFACE_RAISED, TEXT, WARNING,
)

# component key -> (label, explanation)
COMPONENTS: tuple[tuple[str, str, str], ...] = (
    ("prefs", "Spotify preferences",
     "The prefs file written by the optimization (hardware acceleration, cache cap)."),
    ("registry", "Startup entries",
     "HKCU Run values for Spotify. A system change, applied only when selected."),
    ("shortcuts", "Desktop shortcuts",
     "Original shortcut arguments, restored only when selected."),
    ("spicetify", "Spicetify configuration",
     "config-xpui.ini extensions and custom apps."),
)


class RestoreDialog(ctk.CTkToplevel):
    """Choose components, resolve conflicts, then hand the decision to the app."""

    def __init__(
        self,
        master,
        summary: dict,
        on_restore: Optional[Callable[[list[str], bool], None]] = None,
        conflicts: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(master)
        self.summary = summary or {}
        self.on_restore = on_restore
        self.conflicts = dict(conflicts or {})
        self._vars: dict[str, ctk.BooleanVar] = {}
        self._conflict_labels: dict[str, ctk.CTkLabel] = {}

        self.title("Restore snapshot")
        self.geometry("640x600")
        self.minsize(560, 520)
        self.configure(fg_color=SURFACE)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.transient(master)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Restore a protected snapshot", text_color=TEXT,
                     font=ctk.CTkFont(size=19, weight="bold")).grid(
                         row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text=f"Snapshot {self.summary.get('name', 'unknown')} · "
                 f"{self.summary.get('created_at', 'unknown time')}",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        body.grid_columnconfigure(0, weight=1)

        integrity_text, integrity_color = self._integrity_text()
        ctk.CTkLabel(body, text=integrity_text, text_color=integrity_color,
                     justify="left", wraplength=560,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=0, column=0, padx=8, pady=(0, 8), sticky="w")

        ctk.CTkLabel(body, text="COMPONENTS TO RESTORE", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(
                         row=1, column=0, padx=8, pady=(4, 4), sticky="w")

        card = ctk.CTkFrame(body, fg_color=SURFACE_RAISED, corner_radius=12,
                            border_width=1, border_color=BORDER)
        card.grid(row=2, column=0, padx=4, pady=(0, 10), sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        artefacts = self.summary.get("artefacts") or {}
        row = 0
        for key, label, explanation in COMPONENTS:
            present = bool(artefacts.get(key))
            var = ctk.BooleanVar(value=present)
            self._vars[key] = var
            checkbox = ctk.CTkCheckBox(
                card, text=label, variable=var,
                state="normal" if present else "disabled",
                command=self._update_state,
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            checkbox.grid(row=row, column=0, padx=16, pady=(10, 0), sticky="w")
            ctk.CTkLabel(card, text=explanation, text_color=SUBTLE, justify="left",
                         wraplength=520, font=ctk.CTkFont(size=10)).grid(
                             row=row + 1, column=0, padx=34, pady=(0, 4), sticky="w")
            row += 2

            if not present:
                ctk.CTkLabel(card, text="Not included in this snapshot",
                             text_color=SUBTLE, font=ctk.CTkFont(size=9)).grid(
                                 row=row, column=0, padx=34, pady=(0, 6), sticky="w")
                row += 1
                continue

            reason = self.conflicts.get(key)
            if reason:
                conflict_label = ctk.CTkLabel(
                    card,
                    text=f"⚠  {reason} Overwriting is optional.",
                    text_color=WARNING, justify="left", wraplength=520,
                    font=ctk.CTkFont(size=10, weight="bold"),
                )
                conflict_label.grid(row=row, column=0, padx=34, pady=(0, 6), sticky="w")
                self._conflict_labels[key] = conflict_label
                row += 1

        ctk.CTkLabel(
            body,
            text="Startup entries and shortcuts are system changes. They are only "
                 "written when you select them here and confirm below.",
            text_color=SUBTLE, justify="left", wraplength=560,
            font=ctk.CTkFont(size=10),
        ).grid(row=3, column=0, padx=8, pady=(0, 6), sticky="w")

        self.overwrite_var = ctk.BooleanVar(value=False)
        self._overwrite_box = ctk.CTkCheckBox(
            body,
            text="Overwrite components whose live state changed after this snapshot",
            variable=self.overwrite_var,
            font=ctk.CTkFont(size=11),
        )
        self._overwrite_box.grid(row=4, column=0, padx=8, pady=(2, 6), sticky="w")
        if not self.conflicts:
            self._overwrite_box.configure(state="disabled")

        self._status = ctk.CTkLabel(
            body, text="", text_color=WARNING, justify="left", wraplength=560,
            font=ctk.CTkFont(size=10),
        )
        self._status.grid(row=5, column=0, padx=8, pady=(2, 10), sticky="w")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=20, pady=(6, 16))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(footer, text="Nothing has been restored yet.", text_color=SUBTLE,
                     font=ctk.CTkFont(size=10)).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(footer, text="Cancel", width=90, height=32, fg_color="#27303B",
                      hover_color="#333E4C", command=self.destroy).grid(
                          row=0, column=1, padx=(0, 8))
        self._restore_button = ctk.CTkButton(
            footer, text="Restore selected", width=150, height=32,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#08120C",
            font=ctk.CTkFont(size=12, weight="bold"), command=self._restore,
        )
        self._restore_button.grid(row=0, column=2)

        self._update_state()

    # ------------------------------------------------------------------

    def _integrity_text(self) -> tuple[str, str]:
        if not self.summary.get("has_manifest"):
            return ("Legacy snapshot without a manifest: contents cannot be "
                    "re-verified.", WARNING)
        if self.summary.get("integrity_ok"):
            return ("Integrity verified: every artefact still matches its recorded "
                    "SHA-256.", SUCCESS)
        return (f"Integrity problem: {self.summary.get('integrity_detail', 'hashes do not match')}",
                ERROR)

    def selected_components(self) -> list[str]:
        return [key for key, var in self._vars.items() if var.get()]

    def _update_state(self) -> None:
        selected = self.selected_components()
        if not selected:
            self._status.configure(text="Select at least one component to restore.")
            self._restore_button.configure(state="disabled")
            return
        self._restore_button.configure(state="normal")
        messages = []
        if "registry" in selected or "shortcuts" in selected:
            messages.append("Startup entries and shortcuts will be written to this machine.")
        if self.conflicts and not self.overwrite_var.get():
            messages.append(
                "Conflicting components will be left at their current values."
            )
        self._status.configure(text=" ".join(messages), text_color=WARNING)

    def _restore(self) -> None:
        selected = self.selected_components()
        if not selected:
            return
        callback = self.on_restore
        overwrite = bool(self.overwrite_var.get())
        self.destroy()
        if callback:
            callback(selected, overwrite)
