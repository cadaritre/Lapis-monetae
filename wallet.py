#!/usr/bin/env python3
"""
Phase 1 wallet launcher with dark GUI (Python wrapper for the existing CLI).

This script does not replace wallet logic. It delegates critical operations
to the project CLI so create/import/open and address workflows stay consistent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Any
from tkinter import filedialog, ttk


CONFIG_PATH = Path(__file__).with_name(".wallet_py_config.json")
DEFAULT_NETWORK = "mainnet"
NETWORK_CHOICES = ("mainnet", "testnet-10", "testnet-11")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"cli_path": "", "network": DEFAULT_NETWORK}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cli_path": "", "network": DEFAULT_NETWORK}
    return {
        "cli_path": str(data.get("cli_path", "")).strip(),
        "network": str(data.get("network", DEFAULT_NETWORK)).strip() or DEFAULT_NETWORK,
    }


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def resolve_cli_binary(config: dict[str, Any]) -> str | None:
    candidates: list[str] = []
    explicit = str(config.get("cli_path", "")).strip()
    env_bin = os.environ.get("LMT_CLI_BIN", "").strip()
    if explicit:
        candidates.append(explicit)
    if env_bin:
        candidates.append(env_bin)
    candidates.extend(["kaspa-cli", "lmt-cli", "kaspa-cli.exe", "lmt-cli.exe"])

    for candidate in candidates:
        if not candidate:
            continue
        if Path(candidate).exists():
            return str(Path(candidate))
        found = shutil.which(candidate)
        if found:
            return found
    return None


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


class WalletGui(tk.Tk):
    BG = "#0f111a"
    PANEL = "#171b2b"
    INPUT_BG = "#22283d"
    TEXT_BG = "#121829"
    FG = "#ecf1ff"
    MUTED = "#9aa8ca"
    ACCENT = "#3b57ff"
    SUCCESS = "#2ac98c"
    ERROR = "#ff5f7a"
    WARNING = "#f8c14b"

    def __init__(self) -> None:
        super().__init__()
        self.config_data = load_config()
        self.action_buttons: list[AnimatedButton] = []
        self._busy = False
        self.title("Lapis Monetae Wallet Launcher")
        self.geometry("1020x700")
        self.minsize(920, 620)
        self.configure(bg=self.BG)
        self._build_style()
        self._build_layout()
        self.refresh_cli_status()
        self.log("GUI ready. Configure CLI and network, then run an action.")

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Dark.TCombobox",
            fieldbackground=self.INPUT_BG,
            background=self.INPUT_BG,
            foreground=self.FG,
            arrowcolor=self.FG,
            bordercolor=self.INPUT_BG,
            lightcolor=self.INPUT_BG,
            darkcolor=self.INPUT_BG,
        )

    def _build_layout(self) -> None:
        outer = tk.Frame(self, bg=self.BG, padx=18, pady=18)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=self.BG)
        header.pack(fill="x", pady=(0, 12))
        tk.Label(
            header,
            text="Lapis Monetae Wallet",
            bg=self.BG,
            fg=self.FG,
            font=("Segoe UI Semibold", 22),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Phase 1 - Modern dark mode GUI",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 0))
        self.pill_status = tk.Label(
            header,
            text=" READY ",
            bg="#1f2740",
            fg="#c9d8ff",
            font=("Segoe UI Semibold", 9),
            padx=10,
            pady=4,
        )
        self.pill_status.pack(anchor="e", pady=(0, 2))

        top_shell = tk.Frame(outer, bg="#0c0f18", padx=1, pady=1)
        top_shell.pack(fill="x")
        top_panel = tk.Frame(top_shell, bg=self.PANEL, padx=14, pady=14)
        top_panel.pack(fill="x")

        tk.Label(top_panel, text="CLI path", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w")
        self.cli_path_var = tk.StringVar(value=self.config_data.get("cli_path", ""))
        cli_entry = tk.Entry(
            top_panel,
            textvariable=self.cli_path_var,
            bg=self.INPUT_BG,
            fg=self.FG,
            insertbackground=self.FG,
            relief="flat",
            font=("Consolas", 10),
        )
        cli_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), ipady=8)

        AnimatedButton(top_panel, text="Browse", command=self.on_browse_cli).grid(row=1, column=1, padx=(0, 8))
        AnimatedButton(top_panel, text="Save", command=self.on_save_cli_path, base_bg="#2f3653", hover_bg="#4b57a3").grid(row=1, column=2)

        tk.Label(top_panel, text="Network", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10)).grid(row=0, column=3, sticky="w", padx=(18, 0))
        self.network_var = tk.StringVar(value=self.config_data.get("network", DEFAULT_NETWORK))
        network_box = ttk.Combobox(
            top_panel,
            values=NETWORK_CHOICES,
            textvariable=self.network_var,
            state="readonly",
            style="Dark.TCombobox",
            width=12,
        )
        network_box.grid(row=1, column=3, sticky="w", padx=(18, 0), ipady=4)
        network_box.bind("<<ComboboxSelected>>", lambda _e: self.on_network_change())

        tk.Label(top_panel, text="Wallet name (optional)", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10)).grid(row=0, column=4, sticky="w", padx=(18, 0))
        self.wallet_name_var = tk.StringVar()
        tk.Entry(
            top_panel,
            textvariable=self.wallet_name_var,
            bg=self.INPUT_BG,
            fg=self.FG,
            insertbackground=self.FG,
            relief="flat",
            font=("Segoe UI", 10),
            width=22,
        ).grid(row=1, column=4, sticky="w", padx=(18, 0), ipady=8)
        top_panel.grid_columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="CLI: unresolved")
        status = tk.Label(outer, textvariable=self.status_var, bg=self.BG, fg=self.MUTED, font=("Segoe UI", 10))
        status.pack(anchor="w", pady=(10, 8))

        actions_shell = tk.Frame(outer, bg="#0c0f18", padx=1, pady=1)
        actions_shell.pack(fill="x", pady=(0, 12))
        actions = tk.Frame(actions_shell, bg=self.PANEL, padx=10, pady=10)
        actions.pack(fill="x")

        row1 = tk.Frame(actions, bg=self.PANEL)
        row1.pack(fill="x", pady=(0, 8))
        row2 = tk.Frame(actions, bg=self.PANEL)
        row2.pack(fill="x")

        self._add_action_button(row1, 0, "Create Wallet", self.action_create, "#465bff")
        self._add_action_button(row1, 1, "Import Wallet", self.action_import, "#4f67ff")
        self._add_action_button(row1, 2, "Open Wallet", self.action_open, "#5a72ff")
        self._add_action_button(row1, 3, "Wallet List", lambda: self.run_capture_action(["wallet", "list"]), "#2f9df0")
        self._add_action_button(row2, 0, "Accounts/Balances", self.action_list_balances, "#1fa9cc")
        self._add_action_button(row2, 1, "Show Address", lambda: self.run_capture_action(["address"]), "#27bb9c")
        self._add_action_button(row2, 2, "New Address", lambda: self.run_capture_action(["address", "new"]), "#31c27b")
        self._add_action_button(row2, 3, "Clear Output", self.clear_output, "#7d4df2")
        for col in range(4):
            row1.grid_columnconfigure(col, weight=1)
            row2.grid_columnconfigure(col, weight=1)

        output_shell = tk.Frame(outer, bg="#0c0f18", padx=1, pady=1)
        output_shell.pack(fill="both", expand=True)
        output_panel = tk.Frame(output_shell, bg=self.PANEL, padx=12, pady=10)
        output_panel.pack(fill="both", expand=True)
        tk.Label(output_panel, text="Command Output", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI Semibold", 10)).pack(anchor="w", pady=(0, 6))

        self.output = tk.Text(
            output_panel,
            bg=self.TEXT_BG,
            fg="#dbe4ff",
            insertbackground=self.FG,
            relief="flat",
            wrap="word",
            font=("Consolas", 10),
            padx=12,
            pady=10,
        )
        self.output.pack(fill="both", expand=True)
        self.output.tag_configure("ts", foreground="#7f95c7")
        self.output.tag_configure("error", foreground=self.ERROR)
        self.output.tag_configure("ok", foreground=self.SUCCESS)

    def _add_action_button(self, parent: tk.Frame, col: int, text: str, command: Any, hover: str) -> None:
        btn = AnimatedButton(parent, text=text, command=command, hover_bg=hover)
        btn.grid(row=0, column=col, padx=6, pady=6, sticky="ew")
        self.action_buttons.append(btn)

    def log(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.output.insert("end", f"[{ts}] ", ("ts",))
        self.output.insert("end", text.rstrip() + "\n")
        self.output.see("end")

    def on_browse_cli(self) -> None:
        path = filedialog.askopenfilename(title="Select CLI binary")
        if path:
            self.cli_path_var.set(path)

    def on_save_cli_path(self) -> None:
        self.config_data["cli_path"] = self.cli_path_var.get().strip()
        save_config(self.config_data)
        self.refresh_cli_status()
        self.log("CLI path saved.")
        self.toast("CLI path saved", "ok")

    def on_network_change(self) -> None:
        self.config_data["network"] = self.network_var.get().strip() or DEFAULT_NETWORK
        save_config(self.config_data)
        self.log(f"Network saved: {self.config_data['network']}")
        self.toast(f"Active network: {self.config_data['network']}", "info")

    def refresh_cli_status(self) -> None:
        binary = resolve_cli_binary(self.config_data)
        if binary:
            self.status_var.set(f"CLI: {binary} | Network: {self.config_data.get('network', DEFAULT_NETWORK)}")
            self._set_pill(" READY ", "#1f2740", "#c9d8ff")
        else:
            self.status_var.set(f"CLI: not found | Network: {self.config_data.get('network', DEFAULT_NETWORK)}")
            self._set_pill(" CLI MISSING ", "#3a1f2a", "#ffd0d9")

    def require_cli(self) -> str | None:
        self.refresh_cli_status()
        binary = resolve_cli_binary(self.config_data)
        if not binary:
            self.log("ERROR: CLI binary not found. Set a path or define LMT_CLI_BIN.")
            self.toast("CLI was not found", "error")
            return None
        return binary

    def run_capture_action(self, args: list[str], ensure_network: bool = False) -> None:
        if self._busy:
            self.toast("Please wait for the current command to finish", "info")
            return
        binary = self.require_cli()
        if not binary:
            return

        self._set_busy(True)

        def worker() -> None:
            if ensure_network:
                net_code, net_out = self.run_capture(binary, ["network", self.config_data.get("network", DEFAULT_NETWORK)])
                self.after(0, lambda: self.log(net_out))
                if net_code != 0:
                    self.after(0, lambda: self.toast("Failed to select network", "error"))
                    self.after(0, lambda: self._set_busy(False))
                    return
            code, out = self.run_capture(binary, args)
            self.after(0, lambda: self.log(out))
            self.after(0, lambda: self.log(f"Exit code: {code}\n"))
            if code == 0:
                self.after(0, lambda: self.toast("Command completed", "ok"))
            else:
                self.after(0, lambda: self.toast("Command finished with an error", "error"))
            self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def run_capture(self, binary: str, args: list[str]) -> tuple[int, str]:
        command = [binary, *args]
        try:
            result = subprocess.run(command, text=True, capture_output=True, cwd=str(Path(__file__).parent))
        except OSError as err:
            return 1, f"> {' '.join(command)}\nERROR: {err}"

        text = f"> {' '.join(command)}\n"
        if result.stdout:
            text += result.stdout
        if result.stderr:
            text += "\n[stderr]\n" + result.stderr
        if not result.stdout and not result.stderr:
            text += "(no output)\n"
        return result.returncode, text

    def launch_interactive(self, args: list[str]) -> None:
        if self._busy:
            self.toast("Please wait for the current command to finish", "info")
            return
        binary = self.require_cli()
        if not binary:
            return

        self.run_capture_action(["network", self.config_data.get("network", DEFAULT_NETWORK)], ensure_network=False)

        command = [binary, *args]
        try:
            if os.name == "nt":
                subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=str(Path(__file__).parent))
                self.log(f"Launched interactive command in new console: {' '.join(command)}")
                self.toast("Interactive command opened in a new console", "info")
            else:
                subprocess.Popen(command, cwd=str(Path(__file__).parent))
                self.log(f"Launched interactive command: {' '.join(command)}")
                self.toast("Interactive command launched", "info")
        except OSError as err:
            self.log(f"ERROR launching interactive command: {err}")
            self.toast("Error opening interactive console", "error")

    def _wallet_name(self) -> str:
        return self.wallet_name_var.get().strip()

    def action_create(self) -> None:
        args = ["wallet", "create"]
        name = self._wallet_name()
        if name:
            args.append(name)
        self.launch_interactive(args)

    def action_import(self) -> None:
        args = ["wallet", "import"]
        name = self._wallet_name()
        if name:
            args.append(name)
        self.launch_interactive(args)

    def action_open(self) -> None:
        args = ["wallet", "open"]
        name = self._wallet_name()
        if name:
            args.append(name)
        self.launch_interactive(args)

    def action_list_balances(self) -> None:
        self.run_capture_action(["list"], ensure_network=True)

    def clear_output(self) -> None:
        self.output.delete("1.0", "end")
        self.toast("Output cleared", "ok")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for button in self.action_buttons:
            button.config(state=state)
        if busy:
            self._set_pill(" RUNNING ", "#2d2439", "#efd4ff")
        else:
            self.refresh_cli_status()

    def _set_pill(self, text: str, bg: str, fg: str) -> None:
        self.pill_status.config(text=text, bg=bg, fg=fg)

    def toast(self, message: str, kind: str = "info") -> None:
        colors = {
            "ok": ("#143328", "#a8f2cf"),
            "error": ("#3c1e29", "#ffc5d0"),
            "info": ("#1c2e45", "#c8ddff"),
            "warn": ("#3d3218", "#ffe6a6"),
        }
        bg, fg = colors.get(kind, colors["info"])

        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.attributes("-alpha", 0.0)
        width, height = 320, 46
        x = self.winfo_rootx() + self.winfo_width() - width - 24
        y = self.winfo_rooty() + 24
        toast.geometry(f"{width}x{height}+{x}+{y}")
        tk.Frame(toast, bg="#0c0f18", padx=1, pady=1).pack(fill="both", expand=True)
        inner = tk.Frame(toast, bg=bg)
        inner.place(relx=0, rely=0, relwidth=1, relheight=1)
        tk.Label(inner, text=message, bg=bg, fg=fg, font=("Segoe UI Semibold", 10), anchor="w").pack(fill="both", expand=True, padx=12)

        def fade_in(alpha: float = 0.0) -> None:
            if alpha >= 0.96:
                toast.attributes("-alpha", 0.96)
                toast.after(1700, fade_out, 0.96)
                return
            toast.attributes("-alpha", alpha)
            toast.after(18, fade_in, alpha + 0.12)

        def fade_out(alpha: float) -> None:
            if alpha <= 0.0:
                toast.destroy()
                return
            toast.attributes("-alpha", alpha)
            toast.after(18, fade_out, alpha - 0.14)

        fade_in()


def main() -> int:
    app = WalletGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)
