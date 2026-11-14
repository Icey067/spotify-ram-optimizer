"""Reusable, framework-native building blocks for the desktop workspace."""
from __future__ import annotations

from typing import Callable, Iterable

import customtkinter as ctk

from .theme import ACCENT, ACCENT_HOVER, BORDER, MUTED, SUBTLE, SURFACE, SURFACE_RAISED, TEXT


class SectionCard(ctk.CTkFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, fg_color=SURFACE, corner_radius=14, border_width=1,
                         border_color=BORDER, **kwargs)


class PageHeader(ctk.CTkFrame):
    def __init__(self, master, title: str, description: str, action: Callable | None = None,
                 action_text: str = "Refresh") -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title, text_color=TEXT,
                     font=ctk.CTkFont(family="Segoe UI", size=25, weight="bold")).grid(
                         row=0, column=0, sticky="w")
        ctk.CTkLabel(self, text=description, text_color=MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=12)).grid(
                         row=1, column=0, sticky="w", pady=(3, 0))
        if action:
            ctk.CTkButton(self, text=action_text, command=action, height=32, width=100,
                          fg_color=SURFACE_RAISED, hover_color="#29313B", text_color=TEXT).grid(
                              row=0, column=1, rowspan=2, sticky="e")


class StatusPill(ctk.CTkLabel):
    def __init__(self, master, text: str = "Checking", color: str = MUTED, **kwargs) -> None:
        super().__init__(master, text=f"●  {text}", text_color=color, fg_color=SURFACE_RAISED,
                         corner_radius=12, padx=10, pady=5,
                         font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), **kwargs)

    def set(self, text: str, color: str = MUTED) -> None:
        self.configure(text=f"●  {text}", text_color=color)


class MetricCard(SectionCard):
    def __init__(self, master, title: str, value: str = "—", caption: str = "", mark: str = "", **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=title.upper(), text_color=MUTED,
                     font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold")).grid(
                         row=0, column=0, padx=14, pady=(13, 2), sticky="w")
        self.value = ctk.CTkLabel(self, text=value, text_color=TEXT,
                                  font=ctk.CTkFont(family="Segoe UI", size=21, weight="bold"))
        self.value.grid(row=1, column=0, padx=14, sticky="w")
        self.caption = ctk.CTkLabel(self, text=caption, text_color=SUBTLE,
                                    font=ctk.CTkFont(family="Segoe UI", size=10))
        self.caption.grid(row=2, column=0, padx=14, pady=(1, 12), sticky="w")
        if mark:
            ctk.CTkLabel(self, text=mark, text_color=ACCENT,
                         font=ctk.CTkFont(size=16, weight="bold")).grid(
                             row=0, column=1, rowspan=2, padx=14, sticky="ne")

    def set(self, value: str, caption: str | None = None, color: str = TEXT) -> None:
        self.value.configure(text=value, text_color=color)
        if caption is not None:
            self.caption.configure(text=caption)


class MemoryChart(SectionCard):
    """A small Canvas chart that renders only measurements supplied by the app."""
    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="MEMORY HISTORY", text_color=MUTED,
                     font=ctk.CTkFont(size=10, weight="bold")).grid(row=0, column=0, padx=16, pady=(14, 0), sticky="w")
        self.canvas = ctk.CTkCanvas(self, bg=SURFACE, highlightthickness=0, height=160)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 10))
        self._values: list[float] = []
        self.canvas.bind("<Configure>", lambda _e: self._render_chart())
        self._render_chart()

    def set_values(self, values: Iterable[float]) -> None:
        self._values = list(values)[-36:]
        self._render_chart()

    def _render_chart(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 250)
        height = max(canvas.winfo_height(), 130)
        if len(self._values) < 2:
            canvas.create_text(width / 2, height / 2 - 8, text="Waiting for memory readings", fill=MUTED,
                               font=("Segoe UI", 12, "bold"))
            canvas.create_text(width / 2, height / 2 + 15, text="Keep Spotify open to collect a history.", fill=SUBTLE,
                               font=("Segoe UI", 10))
            return
        low, high = min(self._values), max(self._values)
        padding_x, padding_y = 15, 22
        span = max(high - low, 1.0)
        points = []
        for i, value in enumerate(self._values):
            x = padding_x + i * (width - padding_x * 2) / (len(self._values) - 1)
            y = height - padding_y - ((value - low) / span) * (height - padding_y * 2)
            points.extend((x, y))
        for y in (padding_y, height / 2, height - padding_y):
            canvas.create_line(padding_x, y, width - padding_x, y, fill=BORDER, dash=(2, 4))
        canvas.create_line(*points, fill=ACCENT, width=2, smooth=True)
        canvas.create_text(padding_x, 8, text=f"{high:.1f} MB", fill=MUTED, anchor="w", font=("Segoe UI", 9))
        canvas.create_text(padding_x, height - 7, text=f"{low:.1f} MB", fill=MUTED, anchor="w", font=("Segoe UI", 9))


class SidebarButton(ctk.CTkButton):
    def __init__(self, master, label: str, command: Callable, **kwargs) -> None:
        super().__init__(master, text=label, command=command, anchor="w", height=38,
                         corner_radius=8, fg_color="transparent", hover_color="#202731",
                         text_color=MUTED, font=ctk.CTkFont(family="Segoe UI", size=13), **kwargs)

    def set_active(self, active: bool) -> None:
        self.configure(fg_color="#193526" if active else "transparent",
                       text_color=ACCENT if active else MUTED)
