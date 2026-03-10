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


class AnimatedButton(tk.Button):
    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        self.base_bg = kwargs.pop("base_bg", "#2a2f45")
        self.hover_bg = kwargs.pop("hover_bg", "#3b57ff")
        self.press_bg = kwargs.pop("press_bg", "#2c44d4")
        super().__init__(
            master,
            bg=self.base_bg,
            fg="#f4f7ff",
            activeforeground="#ffffff",
            activebackground=self.press_bg,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=16,
            pady=10,
            **kwargs,
        )
        self._animation_token: int | None = None
        self.bind("<Enter>", lambda _e: self._animate_to(self.hover_bg))
        self.bind("<Leave>", lambda _e: self._animate_to(self.base_bg))
        self.bind("<ButtonPress-1>", lambda _e: self.config(bg=self.press_bg))
        self.bind("<ButtonRelease-1>", lambda _e: self._animate_to(self.hover_bg))

    def _animate_to(self, target: str, steps: int = 6, delay_ms: int = 18) -> None:
        if self._animation_token is not None:
            self.after_cancel(self._animation_token)
            self._animation_token = None
        current = self.cget("bg")

        def tick(step: int) -> None:
            if step > steps:
                self.config(bg=target)
                return
            ratio = step / float(steps)
            self.config(bg=_mix_color(current, target, ratio))
            self._animation_token = self.after(delay_ms, tick, step + 1)

        tick(1)
