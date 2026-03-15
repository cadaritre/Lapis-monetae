from __future__ import annotations

import tkinter as tk
from typing import Any


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _mix_color(a: str, b: str, t: float) -> str:
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    mixed = (
        int(ar + (br - ar) * t),
        int(ag + (bg - ag) * t),
        int(ab + (bb - ab) * t),
    )
    return _rgb_to_hex(mixed)


class AnimatedButton(tk.Canvas):
    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        self.text = kwargs.pop("text", "")
        self.command = kwargs.pop("command", None)
        self.base_bg = kwargs.pop("base_bg", "#edf0f7")
        self.hover_bg = kwargs.pop("hover_bg", "#2563eb")
        self.press_bg = kwargs.pop("press_bg", "#1d4ed8")
        self.disabled_bg = kwargs.pop("disabled_bg", "#e5e7eb")
        self.fg = kwargs.pop("fg", "#1e293b")
        self.hover_fg = kwargs.pop("hover_fg", "#ffffff")
        self.disabled_fg = kwargs.pop("disabled_fg", "#9ca3af")
        self.corner_radius = kwargs.pop("corner_radius", 10)
        self.height_px = kwargs.pop("height", 40)
        self.font = kwargs.pop("font", ("Segoe UI Semibold", 10))
        self.border_color = kwargs.pop("border_color", "#d5dae4")

        super().__init__(
            master,
            bg=master.cget("bg"),
            highlightthickness=0,
            bd=0,
            relief="flat",
            height=self.height_px,
            cursor="hand2",
        )

        self._state = "normal"
        self._current_bg = self.base_bg
        self._hovering = False
        self._animation_token: int | None = None

        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

        self._draw()

    def configure(self, cnf: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        if cnf:
            kwargs.update(cnf)
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            self.config(cursor="hand2" if self._state == "normal" else "arrow")
            self._current_bg = self.base_bg if self._state == "normal" else self.disabled_bg
            self._hovering = False
            self._draw()
        if "text" in kwargs:
            self.text = kwargs.pop("text")
            self._draw()
        if kwargs:
            return super().configure(**kwargs)
        return None

    config = configure

    def _on_enter(self, _event: tk.Event[tk.Misc]) -> None:
        if self._state == "normal":
            self._hovering = True
            self._animate_to(self.hover_bg)

    def _on_leave(self, _event: tk.Event[tk.Misc]) -> None:
        if self._state == "normal":
            self._hovering = False
            self._animate_to(self.base_bg)

    def _on_press(self, _event: tk.Event[tk.Misc]) -> None:
        if self._state == "normal":
            self._current_bg = self.press_bg
            self._draw()

    def _on_release(self, event: tk.Event[tk.Misc]) -> None:
        if self._state != "normal":
            return
        x, y = event.x, event.y
        if 0 <= x <= self.winfo_width() and 0 <= y <= self.winfo_height():
            self._animate_to(self.hover_bg)
            if callable(self.command):
                self.after(0, self.command)
        else:
            self._hovering = False
            self._animate_to(self.base_bg)

    def _current_fg(self) -> str:
        if self._state != "normal":
            return self.disabled_fg
        if self._hovering:
            return self.hover_fg
        return self.fg

    def _draw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 10)
        height = max(self.winfo_height(), self.height_px)
        r = min(self.corner_radius, height // 2)
        shadow_c = _mix_color("#000000", self.cget("bg") or "#f2f4f8", 0.82)
        self._draw_rounded_rect(1, 2, width, height, r, shadow_c)
        border_c = self.border_color if self._state == "normal" else "#e5e7eb"
        self._draw_rounded_rect(0, 0, width - 1, height - 2, r, border_c)
        self._draw_rounded_rect(1, 1, width - 2, height - 3, r, self._current_bg)
        highlight_c = _mix_color(self._current_bg, "#ffffff", 0.35)
        self.create_line(1 + r, 2, width - 2 - r, 2, fill=highlight_c, width=1)
        self.create_text(
            (width - 1) // 2,
            (height - 2) // 2,
            text=self.text,
            fill=self._current_fg(),
            font=self.font,
        )

    def _draw_rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, fill: str) -> None:
        self.create_arc(x1, y1, x1 + 2 * radius, y1 + 2 * radius, start=90, extent=90, fill=fill, outline=fill)
        self.create_arc(x2 - 2 * radius, y1, x2, y1 + 2 * radius, start=0, extent=90, fill=fill, outline=fill)
        self.create_arc(x1, y2 - 2 * radius, x1 + 2 * radius, y2, start=180, extent=90, fill=fill, outline=fill)
        self.create_arc(x2 - 2 * radius, y2 - 2 * radius, x2, y2, start=270, extent=90, fill=fill, outline=fill)
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
        self.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)

    def _animate_to(self, target: str, steps: int = 6, delay_ms: int = 16) -> None:
        if self._animation_token is not None:
            self.after_cancel(self._animation_token)
            self._animation_token = None
        start_color = self._current_bg

        def tick(step: int) -> None:
            if step > steps:
                self._current_bg = target
                self._draw()
                return
            ratio = step / float(steps)
            self._current_bg = _mix_color(start_color, target, ratio)
            self._draw()
            self._animation_token = self.after(delay_ms, tick, step + 1)

        tick(1)
