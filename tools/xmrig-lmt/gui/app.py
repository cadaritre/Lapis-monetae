from __future__ import annotations

import json
import logging
import logging.handlers
import os
import queue
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any
from urllib.parse import urlparse

import sys

from ui_components import AnimatedButton

_FROZEN = getattr(sys, "frozen", False)
_EXE_DIR = Path(sys.executable).parent if _FROZEN else Path(__file__).parent
_BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", "")) if _FROZEN else Path(__file__).parent

CONFIG_PATH = _EXE_DIR / "config.json"
ASSETS_DIR = _BUNDLE_DIR / "assets" if _FROZEN else Path(__file__).resolve().parents[3] / "wallet-gui" / "assets"
LOG_DIR = _EXE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_file_logger = logging.getLogger("miner_gui")
_file_logger.setLevel(logging.DEBUG)
_log_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "miner_gui.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_file_logger.addHandler(_log_handler)

_HASHRATE_RE = re.compile(
    r"speed\s+\S+\s+([\d.]+|n/a)\s+([\d.]+|n/a)\s+([\d.]+|n/a)\s+H/s.*?max\s+([\d.]+|n/a)"
)
_SHARES_RE = re.compile(r"accepted\s+\((\d+)/(\d+)\)")
_LATENCY_RE = re.compile(r"accepted.*?\((\d+)\s*ms\)")
_POOL_USE_RE = re.compile(r"\[(?:pool|net)\]\s+(?:use pool|login|new job)")

MAX_RESTARTS = 5
RESTART_BACKOFF_BASE = 2
RESTART_BACKOFF_MAX = 60
RESTART_RESET_AFTER_S = 60
GRACEFUL_TIMEOUT_S = 5

# ── Bech32 / CashAddr address validation ──

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_MAP = {c: i for i, c in enumerate(_BECH32_CHARSET)}
_BECH32_SET = frozenset(_BECH32_CHARSET)
_GENERATORS = (0x98f2bc8e61, 0x79b76d99e2, 0xf33e5fb3c4, 0xae2eabe2a8, 0x1e4f43e470)
_VALID_PREFIXES = ("lmt", "lmttest", "lmtsim", "lmtdev",
                   "kaspa", "kaspatest", "kaspasim", "kaspadev")


def _cashaddr_polymod(values: list[int]) -> int:
    c = 1
    for d in values:
        c0 = c >> 35
        c = ((c & 0x07_FFFF_FFFF) << 5) ^ d
        for i in range(5):
            if c0 & (1 << i):
                c ^= _GENERATORS[i]
    return c ^ 1


def _verify_address_checksum(prefix: str, payload: str) -> bool:
    prefix_5bit = [b & 0x1F for b in prefix.encode("ascii")]
    try:
        payload_5bit = [_BECH32_MAP[c] for c in payload]
    except KeyError:
        return False
    return _cashaddr_polymod(prefix_5bit + [0] + payload_5bit) == 0


def validate_address_full(address: str) -> tuple[bool, str]:
    normalized = address.strip().lower()
    if len(normalized) < 24:
        return False, "Address is too short"
    if ":" not in normalized:
        return False, "Address must contain a ':' separator"
    prefix, payload = normalized.split(":", 1)
    if prefix not in _VALID_PREFIXES:
        return False, f"Unknown address prefix: {prefix}"
    if not payload:
        return False, "Address payload is empty"
    bad = set(payload) - _BECH32_SET
    if bad:
        return False, f"Invalid characters in address: {''.join(sorted(bad))}"
    if not _verify_address_checksum(prefix, payload):
        return False, "Address checksum is invalid"
    return True, ""


def _network_from_prefix(address: str) -> str:
    addr = address.strip().lower()
    if addr.startswith(("lmttest:", "kaspatest:")):
        return "testnet"
    if addr.startswith(("lmtsim:", "kaspasim:")):
        return "simnet"
    if addr.startswith(("lmtdev:", "kaspadev:")):
        return "devnet"
    return "mainnet"


# ── Config with profiles ──

_PROFILE_KEYS = (
    "bridge_path", "listen", "rpc_url", "pay_address", "extra_data_hex",
    "allow_non_daa", "refresh_ms", "xmrig_path", "xmrig_url", "xmrig_extra",
    "start_miner_with_bridge", "auto_restart_bridge", "auto_restart_miner",
)

_PROFILE_DEFAULTS: dict[str, Any] = {
    "bridge_path": "", "listen": "0.0.0.0:3333",
    "rpc_url": "grpc://127.0.0.1:26110", "pay_address": "",
    "extra_data_hex": "", "allow_non_daa": True, "refresh_ms": 5000,
    "xmrig_path": "", "xmrig_url": "stratum+tcp://127.0.0.1:3333",
    "xmrig_extra": "", "start_miner_with_bridge": False,
    "auto_restart_bridge": False, "auto_restart_miner": False,
}


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"_version": 2, "active_profile": "default",
                "profiles": {"default": dict(_PROFILE_DEFAULTS)}}
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"_version": 2, "active_profile": "default",
                "profiles": {"default": dict(_PROFILE_DEFAULTS)}}
    if "_version" not in raw:
        return {"_version": 2, "active_profile": "default",
                "profiles": {"default": raw}}
    return raw


def save_config(data: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _active_profile(cfg: dict[str, Any]) -> dict[str, Any]:
    name = cfg.get("active_profile", "default")
    profiles = cfg.get("profiles", {})
    return profiles.get(name, dict(_PROFILE_DEFAULTS))


def _format_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h {m}m"


class BridgeGui(tk.Tk):
    BG = "#f2f4f8"
    PANEL = "#ffffff"
    INPUT_BG = "#eaecf2"
    TEXT_BG = "#fafbfe"
    FG = "#1a2138"
    MUTED = "#6b7a94"
    BLUE = "#2563eb"
    BLUE_LIGHT = "#dbeafe"
    BLUE_DARK = "#1d4ed8"
    ORANGE = "#d97706"
    ORANGE_LIGHT = "#fef3c7"
    SUCCESS = "#16a34a"
    ERROR = "#dc2626"
    BORDER = "#dce1ea"
    GROUP_BG = "#f7f8fc"
    TEAL = "#0891b2"

    def __init__(self) -> None:
        super().__init__()
        self.process: subprocess.Popen[str] | None = None
        self.miner_process: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self._status_tick = False
        self.action_buttons: list[AnimatedButton] = []

        self._bridge_stopping = False
        self._miner_stopping = False
        self._bridge_restart_count = 0
        self._miner_restart_count = 0
        self._bridge_start_time: float | None = None
        self._miner_start_time: float | None = None

        self._metrics: dict[str, Any] = {
            "hashrate_10s": "\u2014", "hashrate_60s": "\u2014",
            "hashrate_15m": "\u2014", "hashrate_max": "\u2014",
            "accepted": 0, "rejected": 0,
            "pool_latency": "\u2014", "reconnects": 0,
            "last_share": "\u2014", "stratum_since": None,
        }
        self._metric_vars: dict[str, tk.StringVar] = {}

        self._config = load_config()
        profile = _active_profile(self._config)
        self.bridge_path = tk.StringVar(value=profile.get("bridge_path", ""))
        self.listen = tk.StringVar(value=profile.get("listen", "0.0.0.0:3333"))
        self.rpc_url = tk.StringVar(value=profile.get("rpc_url", "grpc://127.0.0.1:26110"))
        self.pay_address = tk.StringVar(value=profile.get("pay_address", ""))
        self.extra_data_hex = tk.StringVar(value=profile.get("extra_data_hex", ""))
        self.allow_non_daa = tk.BooleanVar(value=profile.get("allow_non_daa", True))
        self.refresh_ms = tk.StringVar(value=str(profile.get("refresh_ms", 5000)))
        self.xmrig_path = tk.StringVar(value=profile.get("xmrig_path", ""))
        self.xmrig_url = tk.StringVar(value=profile.get("xmrig_url", "stratum+tcp://127.0.0.1:3333"))
        self.xmrig_extra = tk.StringVar(value=profile.get("xmrig_extra", ""))
        self.start_miner_with_bridge = tk.BooleanVar(value=profile.get("start_miner_with_bridge", False))
        self.auto_restart_bridge = tk.BooleanVar(value=profile.get("auto_restart_bridge", False))
        self.auto_restart_miner = tk.BooleanVar(value=profile.get("auto_restart_miner", False))

        self.title("LMT Miner Control Center")
        self.geometry("700x600")
        self.minsize(480, 600)
        self.configure(bg=self.BG)
        self._set_window_icon()
        self._build_style()
        self._build_menubar()
        self._build_layout()
        self._start_log_pump()
        self._animate_status()
        self._update_metrics_display()
        self.log_message("Welcome to LMT Miner Control Center.")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ── Window icon ──

    def _set_window_icon(self) -> None:
        ico_path = ASSETS_DIR / "lmt_icon.ico"
        png_path = ASSETS_DIR / "lmt_icon_64.png"
        try:
            self.iconbitmap(default=str(ico_path))
        except tk.TclError:
            pass
        try:
            icon_img = tk.PhotoImage(file=str(png_path))
            self.iconphoto(True, icon_img)
            self._icon_ref = icon_img
        except tk.TclError:
            pass

    # ── Style ──

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Light.TCombobox", fieldbackground=self.INPUT_BG,
                        background="#ffffff", foreground=self.FG, arrowcolor=self.MUTED,
                        bordercolor=self.BORDER, lightcolor="#ffffff", darkcolor=self.BORDER,
                        selectbackground=self.BLUE, selectforeground="#ffffff")
        style.map("Light.TCombobox", fieldbackground=[("readonly", self.INPUT_BG)],
                  foreground=[("readonly", self.FG)], bordercolor=[("focus", self.BLUE)])
        style.configure("Light.TCheckbutton", background=self.PANEL,
                        foreground=self.FG, font=("Segoe UI", 9))
        style.map("Light.TCheckbutton", background=[("active", self.PANEL)])

    # ── Menubar ──

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self, bg=self.PANEL, fg=self.FG, activebackground=self.BLUE,
                          activeforeground="#ffffff", font=("Segoe UI", 9), relief="flat")
        file_menu = tk.Menu(menubar, tearoff=0, bg=self.PANEL, fg=self.FG,
                            activebackground=self.BLUE, activeforeground="#ffffff",
                            font=("Segoe UI", 9))
        file_menu.add_command(label="\u2713  Save Settings", command=self.save_settings)
        file_menu.add_command(label="\u2B07  Export Logs", command=self._export_logs)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0, bg=self.PANEL, fg=self.FG,
                             activebackground=self.BLUE, activeforeground="#ffffff",
                             font=("Segoe UI", 9))
        tools_menu.add_command(label="\u2713  Preflight Check", command=self._preflight_check)
        tools_menu.add_command(label="\u2715  Clear Log", command=self.clear_log)
        tools_menu.add_separator()
        tools_menu.add_command(label="\u2398  Copy Bridge Cmd", command=self._copy_bridge_cmd)
        tools_menu.add_command(label="\u2398  Copy Miner Cmd", command=self._copy_miner_cmd)
        tools_menu.add_command(label="\u2750  Open Data Dir", command=self._open_data_dir)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.config(menu=menubar)

    # ── Layout ──

    def _build_layout(self) -> None:
        outer = tk.Frame(self, bg=self.BG, padx=8, pady=4)
        outer.pack(fill="both", expand=True)
        self._build_header(outer)
        self._build_profile_bar(outer)
        self._build_status_row(outer)
        self._build_main_notebook(outer)
        self._build_statusbar()

    # ── Header with dual pills ──

    def _build_header(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=self.BG)
        header.pack(fill="x", pady=(0, 2))
        title_row = tk.Frame(header, bg=self.BG)
        title_row.pack(fill="x")

        header_png = ASSETS_DIR / "lmt_header.png"
        try:
            self._header_logo = tk.PhotoImage(file=str(header_png))
            tk.Label(title_row, image=self._header_logo, bg=self.BG).pack(side="left", padx=(0, 6))
        except tk.TclError:
            pass

        tk.Label(title_row, text="LMT Miner Control Center", bg=self.BG, fg=self.FG,
                 font=("Segoe UI Semibold", 14)).pack(side="left")

        self.pill_miner = tk.Label(title_row, text=" \u25CF  MINER: OFF ", bg=self.BLUE_LIGHT,
                                   fg=self.MUTED, font=("Segoe UI Semibold", 7), padx=6, pady=1)
        self.pill_miner.pack(side="right", padx=(4, 0))
        self.pill_bridge = tk.Label(title_row, text=" \u25CF  BRIDGE: IDLE ", bg=self.BLUE_LIGHT,
                                    fg=self.BLUE, font=("Segoe UI Semibold", 7), padx=6, pady=1)
        self.pill_bridge.pack(side="right")

        accent_line = tk.Canvas(parent, bg=self.BG, height=2, highlightthickness=0, bd=0)
        accent_line.pack(fill="x", pady=(1, 4))
        accent_line.bind("<Configure>", lambda e: self._draw_gradient_line(accent_line, e.width))

    def _draw_gradient_line(self, canvas: tk.Canvas, width: int) -> None:
        canvas.delete("all")
        if width < 2:
            return
        colors = [self.BLUE, "#6366f1", self.ORANGE, self.BLUE]
        segments = len(colors) - 1
        seg_w = max(width / segments, 1)
        for i in range(segments):
            canvas.create_rectangle(int(i * seg_w), 0, int((i + 1) * seg_w), 2,
                                    fill=colors[i], outline=colors[i + 1])

    # ── Profile bar ──

    def _build_profile_bar(self, parent: tk.Frame) -> None:
        bar = tk.Frame(parent, bg=self.PANEL, padx=8, pady=3,
                       highlightbackground=self.BORDER, highlightthickness=1)
        bar.pack(fill="x", pady=(0, 4))
        tk.Label(bar, text="Profile", bg=self.PANEL, fg=self.MUTED,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        self.profile_var = tk.StringVar(value=self._config.get("active_profile", "default"))
        profile_names = list(self._config.get("profiles", {}).keys())
        self.profile_combo = ttk.Combobox(bar, values=profile_names, textvariable=self.profile_var,
                                          state="readonly", style="Light.TCombobox", width=16)
        self.profile_combo.pack(side="left", padx=(0, 6), ipady=1)
        self.profile_combo.bind("<<ComboboxSelected>>",
                                lambda _: self._switch_profile(self.profile_var.get()))
        AnimatedButton(bar, text="Save As\u2026", command=self._save_as_profile,
                       base_bg="#edf0f7", hover_bg=self.BLUE, border_color=self.BORDER,
                       height=24, font=("Segoe UI Semibold", 7)).pack(side="left", padx=(0, 4))
        AnimatedButton(bar, text="Delete", command=self._delete_profile,
                       base_bg="#fee2e2", hover_bg=self.ERROR, border_color="#fecaca",
                       height=24, font=("Segoe UI Semibold", 7)).pack(side="left")

    # ── Status row ──

    def _build_status_row(self, parent: tk.Frame) -> None:
        self.status_var = tk.StringVar(value="\u25B8 Bridge stopped")
        self.state_hint_var = tk.StringVar(value="LMT native stratum mode")
        row = tk.Frame(parent, bg=self.BG)
        row.pack(fill="x", pady=(0, 4))
        tk.Label(row, textvariable=self.status_var, bg=self.BG, fg=self.MUTED, font=("Consolas", 7)).pack(side="left")
        tk.Label(row, textvariable=self.state_hint_var, bg=self.BG, fg=self.MUTED, font=("Consolas", 7)).pack(side="right")

    # ── Status bar (bottom) ──

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self, bg=self.BORDER, height=1)
        bar.pack(side="bottom", fill="x")
        sb = tk.Frame(self, bg=self.PANEL, padx=8, pady=2)
        sb.pack(side="bottom", fill="x")
        self._sb_bridge_var = tk.StringVar(value="Bridge: idle")
        self._sb_miner_var = tk.StringVar(value="Miner: off")
        tk.Label(sb, textvariable=self._sb_bridge_var, bg=self.PANEL, fg=self.MUTED,
                 font=("Consolas", 7)).pack(side="left", padx=(0, 12))
        tk.Label(sb, textvariable=self._sb_miner_var, bg=self.PANEL, fg=self.MUTED,
                 font=("Consolas", 7)).pack(side="left")

    # ── Main notebook (Bridge / Miner / Console / Metrics / Help) ──

    def _build_main_notebook(self, parent: tk.Frame) -> None:
        style = ttk.Style()
        style.configure("Main.TNotebook", background=self.BG, borderwidth=0)
        style.configure("Main.TNotebook.Tab", font=("Segoe UI Semibold", 8),
                        padding=[8, 3], background=self.BG, foreground=self.MUTED)
        style.map("Main.TNotebook.Tab", background=[("selected", self.PANEL)],
                  foreground=[("selected", self.BLUE)])
        notebook = ttk.Notebook(parent, style="Main.TNotebook")
        notebook.pack(fill="both", expand=True)

        self._build_bridge_tab(notebook)
        self._build_miner_tab(notebook)
        self._build_console_tab(notebook)
        self._build_metrics_tab(notebook)
        self._build_help_tab(notebook)

    # ── Bridge tab ──

    def _build_bridge_tab(self, notebook: ttk.Notebook) -> None:
        tab = tk.Frame(notebook, bg=self.BG)
        sc = tk.Canvas(tab, bg=self.BG, highlightthickness=0, bd=0)
        ss = tk.Scrollbar(tab, orient="vertical", command=sc.yview)
        sc.configure(yscrollcommand=ss.set)
        ss.pack(side="right", fill="y"); sc.pack(side="left", fill="both", expand=True)
        panel = tk.Frame(sc, bg=self.PANEL, padx=10, pady=6)
        sw = sc.create_window((0, 0), window=panel, anchor="nw")
        self._section_title(panel, "\u26A1 Bridge Settings", self.BLUE)

        tk.Label(panel, text="Bridge Binary", bg=self.PANEL, fg=self.MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w")
        er = tk.Frame(panel, bg=self.PANEL); er.pack(fill="x", pady=(0, 4))
        self._make_entry(er, self.bridge_path).pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 4))
        AnimatedButton(er, text="\u2026", command=lambda: self._browse_binary("bridge"),
                       base_bg="#edf0f7", hover_bg=self.BLUE, border_color=self.BORDER,
                       height=26, font=("Segoe UI Semibold", 8)).pack(side="left")

        r2 = tk.Frame(panel, bg=self.PANEL); r2.pack(fill="x", pady=(0, 4))
        lf = tk.Frame(r2, bg=self.PANEL); lf.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(lf, text="Listen Address", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self._make_entry(lf, self.listen).pack(fill="x", ipady=4)
        rf = tk.Frame(r2, bg=self.PANEL); rf.pack(side="left", fill="x", expand=True)
        tk.Label(rf, text="RPC URL", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self._make_entry(rf, self.rpc_url).pack(fill="x", ipady=4)

        tk.Label(panel, text="Pay Address", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self._make_entry(panel, self.pay_address).pack(fill="x", ipady=4, pady=(0, 4))

        r4 = tk.Frame(panel, bg=self.PANEL); r4.pack(fill="x", pady=(0, 4))
        ef = tk.Frame(r4, bg=self.PANEL); ef.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(ef, text="Extra Data (hex)", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self._make_entry(ef, self.extra_data_hex).pack(fill="x", ipady=4)
        mf = tk.Frame(r4, bg=self.PANEL); mf.pack(side="left")
        tk.Label(mf, text="Refresh (ms)", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self._make_entry(mf, self.refresh_ms, width=10).pack(fill="x", ipady=4)

        cf = tk.Frame(panel, bg=self.PANEL); cf.pack(fill="x", pady=(2, 6))
        ttk.Checkbutton(cf, text="Allow non-DAA", variable=self.allow_non_daa,
                        style="Light.TCheckbutton").pack(side="left", padx=(0, 10))
        ttk.Checkbutton(cf, text="Auto-restart", variable=self.auto_restart_bridge,
                        style="Light.TCheckbutton").pack(side="left")

        tk.Frame(panel, bg=self.BORDER, height=1).pack(fill="x", pady=(0, 6))
        bf = tk.Frame(panel, bg=self.PANEL); bf.pack(fill="x")
        for i, (lbl, cmd, clr) in enumerate([
            ("\u25B6 Start", self.start_bridge, self.BLUE),
            ("\u25A0 Stop", self.stop_bridge, self.ERROR),
            ("\u2316 Test RPC", self.test_rpc, "#6366f1"),
            ("\u25CF Test Stratum", self.test_stratum, "#8b5cf6"),
        ]):
            bf.grid_columnconfigure(i, weight=1, uniform="bbtn")
            btn = AnimatedButton(bf, text=lbl, command=cmd, base_bg="#edf0f7",
                                 hover_bg=clr, border_color=self.BORDER, fg="#1e293b",
                                 hover_fg="#ffffff", height=28, font=("Segoe UI Semibold", 8))
            btn.grid(row=0, column=i, padx=2, pady=1, sticky="ew")
            self.action_buttons.append(btn)

        AnimatedButton(panel, text="\u2713 Save Settings", command=self.save_settings,
                       base_bg="#dcfce7", hover_bg=self.SUCCESS, border_color="#86efac",
                       fg="#166534", height=28, font=("Segoe UI Semibold", 8)).pack(fill="x", pady=(6, 0))

        panel.bind("<Configure>", lambda _: sc.configure(scrollregion=sc.bbox("all")))
        sc.bind("<Configure>", lambda e: sc.itemconfig(sw, width=e.width))
        sc.bind("<Enter>", lambda _: self._bind_mousewheel(sc))
        sc.bind("<Leave>", lambda _: self._unbind_mousewheel(sc))
        notebook.add(tab, text=" \u26A1 Bridge ")

    # ── Miner tab ──

    def _build_miner_tab(self, notebook: ttk.Notebook) -> None:
        tab = tk.Frame(notebook, bg=self.BG)
        sc = tk.Canvas(tab, bg=self.BG, highlightthickness=0, bd=0)
        ss = tk.Scrollbar(tab, orient="vertical", command=sc.yview)
        sc.configure(yscrollcommand=ss.set)
        ss.pack(side="right", fill="y"); sc.pack(side="left", fill="both", expand=True)
        panel = tk.Frame(sc, bg=self.PANEL, padx=10, pady=6)
        sw = sc.create_window((0, 0), window=panel, anchor="nw")
        self._section_title(panel, "\u2692 XMRig (Fork) Settings", self.TEAL)

        tk.Label(panel, text="XMRig Binary", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        er = tk.Frame(panel, bg=self.PANEL); er.pack(fill="x", pady=(0, 4))
        self._make_entry(er, self.xmrig_path).pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 4))
        AnimatedButton(er, text="\u2026", command=lambda: self._browse_binary("xmrig"),
                       base_bg="#edf0f7", hover_bg=self.TEAL, border_color=self.BORDER,
                       height=26, font=("Segoe UI Semibold", 8)).pack(side="left")

        r2 = tk.Frame(panel, bg=self.PANEL); r2.pack(fill="x", pady=(0, 4))
        uf = tk.Frame(r2, bg=self.PANEL); uf.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(uf, text="XMRig URL", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self._make_entry(uf, self.xmrig_url).pack(fill="x", ipady=4)
        xf = tk.Frame(r2, bg=self.PANEL); xf.pack(side="left", fill="x", expand=True)
        tk.Label(xf, text="Extra Args", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self._make_entry(xf, self.xmrig_extra).pack(fill="x", ipady=4)

        cf = tk.Frame(panel, bg=self.PANEL); cf.pack(fill="x", pady=(2, 6))
        ttk.Checkbutton(cf, text="Start with bridge", variable=self.start_miner_with_bridge,
                        style="Light.TCheckbutton").pack(side="left", padx=(0, 10))
        ttk.Checkbutton(cf, text="Auto-restart", variable=self.auto_restart_miner,
                        style="Light.TCheckbutton").pack(side="left")

        tk.Frame(panel, bg=self.BORDER, height=1).pack(fill="x", pady=(0, 6))
        bf = tk.Frame(panel, bg=self.PANEL); bf.pack(fill="x")
        for i, (lbl, cmd, clr) in enumerate([
            ("\u25B6 Start Miner", self.start_miner, self.TEAL),
            ("\u25A0 Stop Miner", self.stop_miner, self.ERROR),
        ]):
            bf.grid_columnconfigure(i, weight=1, uniform="mbtn")
            btn = AnimatedButton(bf, text=lbl, command=cmd, base_bg="#edf0f7",
                                 hover_bg=clr, border_color=self.BORDER, fg="#1e293b",
                                 hover_fg="#ffffff", height=28, font=("Segoe UI Semibold", 8))
            btn.grid(row=0, column=i, padx=2, pady=1, sticky="ew")
            self.action_buttons.append(btn)

        panel.bind("<Configure>", lambda _: sc.configure(scrollregion=sc.bbox("all")))
        sc.bind("<Configure>", lambda e: sc.itemconfig(sw, width=e.width))
        sc.bind("<Enter>", lambda _: self._bind_mousewheel(sc))
        sc.bind("<Leave>", lambda _: self._unbind_mousewheel(sc))
        notebook.add(tab, text=" \u2692 Miner ")

    # ── Console tab ──

    def _build_console_tab(self, notebook: ttk.Notebook) -> None:
        of = tk.Frame(notebook, bg=self.PANEL, padx=6, pady=4)
        oh = tk.Frame(of, bg=self.PANEL); oh.pack(fill="x", pady=(0, 2))
        self.line_count_var = tk.StringVar(value="0 lines")
        tk.Label(oh, textvariable=self.line_count_var, bg=self.PANEL, fg="#a0aab8",
                 font=("Consolas", 7)).pack(side="right")
        tb = tk.Frame(of, bg=self.BORDER, padx=1, pady=1); tb.pack(fill="both", expand=True)
        ys = tk.Scrollbar(tb, orient="vertical"); ys.pack(side="right", fill="y")
        xs = tk.Scrollbar(tb, orient="horizontal"); xs.pack(side="bottom", fill="x")
        self.output = tk.Text(tb, bg=self.TEXT_BG, fg="#334155", insertbackground=self.FG,
                              relief="flat", wrap="none", font=("Consolas", 8), padx=6, pady=4,
                              yscrollcommand=ys.set, xscrollcommand=xs.set, borderwidth=0,
                              selectbackground=self.BLUE_LIGHT, selectforeground=self.FG)
        self.output.pack(fill="both", expand=True)
        ys.config(command=self.output.yview); xs.config(command=self.output.xview)
        for tag, color in [("ts", self.BLUE), ("bridge", "#3b82f6"), ("miner", self.SUCCESS),
                           ("system", self.ORANGE), ("err", self.ERROR)]:
            self.output.tag_configure(tag, foreground=color)
        self.output.config(state="disabled")
        notebook.add(of, text=" \u2630 Console ")

    # ── Help tab ──

    def _build_help_tab(self, notebook: ttk.Notebook) -> None:
        ho = tk.Frame(notebook, bg=self.PANEL)
        hc = tk.Canvas(ho, bg=self.PANEL, highlightthickness=0, bd=0)
        hs = tk.Scrollbar(ho, orient="vertical", command=hc.yview)
        hc.configure(yscrollcommand=hs.set); hs.pack(side="right", fill="y"); hc.pack(side="left", fill="both", expand=True)
        hi = tk.Frame(hc, bg=self.PANEL, padx=14, pady=10)
        hw = hc.create_window((0, 0), window=hi, anchor="nw")
        tk.Label(hi, text=(
            "Tip: use a valid lmt: address to enable native LMT flow.\n\n"
            "1. Set the bridge binary path to your built lmt-stratum-bridge.\n"
            "2. Optionally set the XMRig fork binary to auto-start mining.\n"
            "3. Settings are saved in config.json next to app.py.\n\n"
            "Health checks:\n"
            "  \u2022 Test RPC \u2014 TCP connectivity to gRPC node.\n"
            "  \u2022 Test Stratum \u2014 bridge listen port accepting connections.\n\n"
            "Watchdog:\n"
            "  \u2022 Auto-restart on crash with exponential backoff (max 5, resets after 60s).\n\n"
            "Sequential start:\n"
            "  \u2022 'Start miner with bridge' waits for bridge port (timeout 30s).\n\n"
            "Profiles:\n"
            "  \u2022 Multiple config profiles for quick environment switching.\n\n"
            "Address validation:\n"
            "  \u2022 Full Bech32/CashAddr checksum verification.\n\n"
            "Network protection:\n"
            "  \u2022 Warns if address prefix and RPC port suggest different networks.\n\n"
            "Diagnostics (File > / Tools > menu):\n"
            "  \u2022 Preflight Check validates all settings before launch.\n"
            "  \u2022 Copy Bridge/Miner Cmd copies the full command line.\n"
            "  \u2022 Export Logs saves rotated log files."
        ), bg=self.PANEL, fg=self.FG, font=("Segoe UI", 9),
                 justify="left", anchor="nw", wraplength=600).pack(fill="x", anchor="nw")
        hi.bind("<Configure>", lambda _: hc.configure(scrollregion=hc.bbox("all")))
        hc.bind("<Configure>", lambda e: hc.itemconfig(hw, width=e.width))
        hc.bind("<Enter>", lambda _: self._bind_mousewheel(hc))
        hc.bind("<Leave>", lambda _: self._unbind_mousewheel(hc))
        notebook.add(ho, text=" \u2753 Help ")

    def _build_metrics_tab(self, notebook: ttk.Notebook) -> None:
        mo = tk.Frame(notebook, bg=self.BG)
        mc = tk.Canvas(mo, bg=self.BG, highlightthickness=0, bd=0)
        ms = tk.Scrollbar(mo, orient="vertical", command=mc.yview)
        mc.configure(yscrollcommand=ms.set); ms.pack(side="right", fill="y"); mc.pack(side="left", fill="both", expand=True)
        mf = tk.Frame(mc, bg=self.BG, padx=8, pady=6)
        mw = mc.create_window((0, 0), window=mf, anchor="nw")

        all_keys = ("hashrate_10s", "hashrate_60s", "hashrate_15m", "hashrate_max",
                     "accepted", "rejected", "pool_latency", "reconnects",
                     "last_share", "stratum_uptime",
                     "bridge_uptime", "bridge_restarts", "bridge_status",
                     "miner_uptime", "miner_restarts", "miner_status")
        for key in all_keys:
            default = "\u2014"
            if key in ("accepted", "rejected", "bridge_restarts", "miner_restarts", "reconnects"):
                default = "0"
            elif key in ("bridge_status", "miner_status"):
                default = "Stopped"
            self._metric_vars[key] = tk.StringVar(value=default)

        self._build_metric_card(mf, "\u2692 Hash Rate", self.TEAL, [
            ("10s", self._metric_vars["hashrate_10s"]), ("60s", self._metric_vars["hashrate_60s"]),
            ("15m", self._metric_vars["hashrate_15m"]), ("Max", self._metric_vars["hashrate_max"]),
        ]).pack(fill="x", pady=(0, 4))
        self._build_metric_card(mf, "\u2713 Shares", self.SUCCESS, [
            ("\u2713 Accepted", self._metric_vars["accepted"]),
            ("\u2717 Rejected", self._metric_vars["rejected"]),
        ]).pack(fill="x", pady=(0, 4))

        r1 = tk.Frame(mf, bg=self.BG); r1.pack(fill="x", pady=(0, 4))
        self._build_metric_card(r1, "\u26A1 Bridge", self.BLUE, [
            ("Uptime", self._metric_vars["bridge_uptime"]),
            ("Restarts", self._metric_vars["bridge_restarts"]),
            ("Status", self._metric_vars["bridge_status"]),
        ]).pack(side="left", fill="both", expand=True, padx=(0, 3))
        self._build_metric_card(r1, "\u2692 Miner", self.TEAL, [
            ("Uptime", self._metric_vars["miner_uptime"]),
            ("Restarts", self._metric_vars["miner_restarts"]),
            ("Status", self._metric_vars["miner_status"]),
        ]).pack(side="left", fill="both", expand=True, padx=(3, 0))

        self._build_metric_card(mf, "\u25CF Pool", "#7c3aed", [
            ("Latency", self._metric_vars["pool_latency"]),
            ("Reconnects", self._metric_vars["reconnects"]),
            ("Last Share", self._metric_vars["last_share"]),
            ("Stratum Up", self._metric_vars["stratum_uptime"]),
        ]).pack(fill="x", pady=(0, 4))

        mf.bind("<Configure>", lambda _: mc.configure(scrollregion=mc.bbox("all")))
        mc.bind("<Configure>", lambda e: mc.itemconfig(mw, width=e.width))
        mc.bind("<Enter>", lambda _: self._bind_mousewheel(mc))
        mc.bind("<Leave>", lambda _: self._unbind_mousewheel(mc))
        notebook.add(mo, text=" \u2637 Metrics ")

    def _build_metric_card(self, parent: tk.Frame, title: str, accent: str,
                           rows: list[tuple[str, tk.StringVar]]) -> tk.Frame:
        card = tk.Frame(parent, bg=self.PANEL, padx=8, pady=5,
                        highlightbackground=self.BORDER, highlightthickness=1)
        self._section_title(card, title, accent)
        for lt, var in rows:
            r = tk.Frame(card, bg=self.PANEL); r.pack(fill="x", pady=1)
            tk.Label(r, text=lt, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8), width=10, anchor="w").pack(side="left")
            tk.Label(r, textvariable=var, bg=self.PANEL, fg=self.FG, font=("Consolas", 9), anchor="w").pack(side="left", fill="x", expand=True)
        return card

    def _section_title(self, parent: tk.Frame, text: str, accent: str) -> None:
        tb = tk.Frame(parent, bg=self.PANEL); tb.pack(fill="x", pady=(0, 4))
        dot = tk.Canvas(tb, width=7, height=7, bg=self.PANEL, highlightthickness=0, bd=0)
        dot.pack(side="left", padx=(1, 3)); dot.create_oval(1, 1, 6, 6, fill=accent, outline=accent)
        tk.Label(tb, text=text, bg=self.PANEL, fg=accent, font=("Segoe UI Semibold", 9)).pack(side="left")

    # ── Scrollable / widget helpers ──

    def _bind_mousewheel(self, canvas: tk.Canvas) -> None:
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    def _unbind_mousewheel(self, canvas: tk.Canvas) -> None:
        canvas.unbind_all("<MouseWheel>")

    def _make_entry(self, parent: tk.Frame, variable: tk.StringVar, width: int | None = None) -> tk.Entry:
        kw: dict[str, Any] = {"textvariable": variable, "bg": self.INPUT_BG, "fg": self.FG,
                              "insertbackground": self.FG, "relief": "flat", "font": ("Consolas", 8),
                              "highlightthickness": 1, "highlightcolor": self.BLUE, "highlightbackground": self.BORDER}
        if width is not None:
            kw["width"] = width
        return tk.Entry(parent, **kw)

    def _create_modal(self, title: str, accent: str = "#2563eb") -> tk.Toplevel:
        modal = tk.Toplevel(self)
        modal.title(title); modal.configure(bg=self.BG)
        modal.transient(self); modal.grab_set(); modal.resizable(True, True)
        tk.Frame(modal, bg=accent, height=4).pack(fill="x")
        tf = tk.Frame(modal, bg=self.PANEL, padx=20, pady=12); tf.pack(fill="x")
        tk.Label(tf, text=title, bg=self.PANEL, fg=self.FG, font=("Segoe UI Semibold", 14)).pack(side="left")
        cb = tk.Label(tf, text="\u2715", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 12), cursor="hand2")
        cb.pack(side="right")
        cb.bind("<Button-1>", lambda _: modal.destroy())
        cb.bind("<Enter>", lambda _: cb.config(fg=self.ERROR))
        cb.bind("<Leave>", lambda _: cb.config(fg=self.MUTED))
        tk.Frame(modal, bg=self.BORDER, height=1).pack(fill="x")
        return modal

    # ── Validation ──

    def _validate_listen(self, value: str) -> tuple[bool, str]:
        if not value:
            return False, "Listen address is required"
        parts = value.rsplit(":", 1)
        if len(parts) != 2:
            return False, "Listen must be host:port (e.g. 0.0.0.0:3333)"
        try:
            port = int(parts[1])
            if not 1 <= port <= 65535:
                return False, "Port must be between 1 and 65535"
        except ValueError:
            return False, "Port must be a number"
        return True, ""

    def _validate_rpc_url(self, value: str) -> tuple[bool, str]:
        if not value:
            return False, "RPC URL is required"
        parsed = urlparse(value)
        if parsed.scheme not in ("grpc", "grpcs", "http", "https"):
            return False, "RPC URL must start with grpc://, grpcs://, http://, or https://"
        if not parsed.hostname:
            return False, "RPC URL must include a hostname"
        return True, ""

    def _validate_pay_address(self, value: str) -> tuple[bool, str]:
        if not value:
            return False, "Pay address is required"
        ok, msg = validate_address_full(value)
        if not ok:
            return False, msg
        return True, ""

    def _validate_refresh_ms(self, value: str) -> tuple[bool, str]:
        try:
            ms = int(value)
        except ValueError:
            return False, "Refresh ms must be a number"
        if ms < 100:
            return False, "Refresh ms must be at least 100"
        if ms > 300000:
            return False, "Refresh ms must be at most 300000"
        return True, ""

    def _validate_binary_path(self, value: str, name: str) -> tuple[bool, str]:
        if not value:
            return False, f"{name} binary path is required"
        if not Path(value).exists():
            return False, f"{name} binary not found at: {value}"
        return True, ""

    def _validate_all_bridge(self) -> tuple[bool, str]:
        for ok, msg in [
            self._validate_binary_path(self.bridge_path.get().strip(), "Bridge"),
            self._validate_listen(self.listen.get().strip()),
            self._validate_rpc_url(self.rpc_url.get().strip()),
            self._validate_pay_address(self.pay_address.get().strip()),
            self._validate_refresh_ms(self.refresh_ms.get().strip()),
        ]:
            if not ok:
                return False, msg
        return True, ""

    def _validate_all_miner(self) -> tuple[bool, str]:
        ok, msg = self._validate_binary_path(self.xmrig_path.get().strip(), "XMRig")
        if not ok:
            return False, msg
        if not self.xmrig_url.get().strip():
            return False, "XMRig URL is required"
        extra = self.xmrig_extra.get().strip()
        if extra:
            try:
                shlex.split(extra)
            except ValueError as exc:
                return False, f"Invalid extra args syntax: {exc}"
        return True, ""

    def _check_network_consistency(self) -> tuple[bool, str]:
        address = self.pay_address.get().strip()
        rpc = self.rpc_url.get().strip()
        if not address or not rpc:
            return True, ""
        addr_net = _network_from_prefix(address)
        parsed = urlparse(rpc)
        port = parsed.port
        if port is None:
            return True, ""
        testnet_ports = {16310, 16410, 16510, 16610}
        mainnet_ports = {16110, 16210, 26110}
        if addr_net == "mainnet" and port in testnet_ports:
            return False, f"Address is mainnet but RPC port {port} looks like testnet"
        if addr_net == "testnet" and port in mainnet_ports:
            return False, f"Address is testnet but RPC port {port} looks like mainnet"
        return True, ""

    # ── Health checks ──

    def test_rpc(self) -> None:
        url = self.rpc_url.get().strip()
        ok, msg = self._validate_rpc_url(url)
        if not ok:
            self.toast(msg, "error"); return
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"; port = parsed.port or 26110
        self.log_message(f"[system] Testing RPC at {host}:{port}...", "system")

        def worker() -> None:
            try:
                s = socket.create_connection((host, port), timeout=5); s.close()
                self.after(0, lambda: self.toast(f"RPC reachable at {host}:{port}", "ok"))
                self.after(0, lambda: self.log_message(f"[system] RPC test OK: {host}:{port}", "system"))
            except (socket.timeout, OSError) as exc:
                self.after(0, lambda: self.toast(f"RPC unreachable: {exc}", "error"))
                self.after(0, lambda: self.log_message(f"[system] RPC test FAILED: {host}:{port} \u2014 {exc}", "system"))
        threading.Thread(target=worker, daemon=True).start()

    def test_stratum(self) -> None:
        listen = self.listen.get().strip()
        ok, msg = self._validate_listen(listen)
        if not ok:
            self.toast(msg, "error"); return
        host, port_str = listen.rsplit(":", 1); port = int(port_str)
        if host == "0.0.0.0":
            host = "127.0.0.1"
        self.log_message(f"[system] Testing Stratum at {host}:{port}...", "system")

        def worker() -> None:
            try:
                s = socket.create_connection((host, port), timeout=5); s.close()
                self.after(0, lambda: self.toast(f"Stratum reachable at {host}:{port}", "ok"))
                self.after(0, lambda: self.log_message(f"[system] Stratum test OK: {host}:{port}", "system"))
            except (socket.timeout, OSError) as exc:
                self.after(0, lambda: self.toast(f"Stratum not responding: {exc}", "error"))
                self.after(0, lambda: self.log_message(f"[system] Stratum test FAILED: {host}:{port} \u2014 {exc}", "system"))
        threading.Thread(target=worker, daemon=True).start()

    # ── Logging ──

    def log_message(self, text: str, tag: str = "system") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.output.config(state="normal")
        self.output.insert("end", f"[{ts}] ", ("ts",))
        self.output.insert("end", text.rstrip() + "\n", (tag,))
        self.output.see("end")
        self.output.config(state="disabled")
        lines = int(self.output.index("end-1c").split(".")[0])
        self.line_count_var.set(f"{lines} lines")
        _file_logger.info(text.rstrip())

    def append_log(self, text: str) -> None:
        tag = "system"
        if text.startswith("[miner]"):
            tag = "miner"
        elif text.startswith("[bridge]"):
            tag = "bridge"
        self.log_message(text, tag)

    def _start_log_pump(self) -> None:
        def pump() -> None:
            while True:
                try:
                    line = self.log_queue.get_nowait()
                except queue.Empty:
                    break
                self.append_log(line)
                if line.startswith("[miner]"):
                    self._parse_metrics_line(line)
            self.after(100, pump)
        self.after(100, pump)

    # ── Metrics parsing (extended) ──

    def _parse_metrics_line(self, line: str) -> None:
        m = _HASHRATE_RE.search(line)
        if m:
            for i, key in enumerate(("hashrate_10s", "hashrate_60s", "hashrate_15m", "hashrate_max"), 1):
                val = m.group(i)
                self._metrics[key] = f"{val} H/s" if val != "n/a" else "n/a"
        m = _SHARES_RE.search(line)
        if m:
            self._metrics["accepted"] = int(m.group(1))
            self._metrics["rejected"] = int(m.group(2))
            self._metrics["last_share"] = datetime.now().strftime("%H:%M:%S")
        m = _LATENCY_RE.search(line)
        if m:
            self._metrics["pool_latency"] = f"{m.group(1)} ms"
        if _POOL_USE_RE.search(line):
            self._metrics["reconnects"] = self._metrics.get("reconnects", 0) + 1
            self._metrics["stratum_since"] = time.time()

    def _update_metrics_display(self) -> None:
        for key in ("hashrate_10s", "hashrate_60s", "hashrate_15m", "hashrate_max",
                     "pool_latency", "last_share"):
            if key in self._metric_vars:
                self._metric_vars[key].set(str(self._metrics.get(key, "\u2014")))
        for key in ("accepted", "rejected", "reconnects"):
            if key in self._metric_vars:
                self._metric_vars[key].set(str(self._metrics.get(key, 0)))
        if "bridge_uptime" in self._metric_vars:
            if self._bridge_start_time and self.process:
                self._metric_vars["bridge_uptime"].set(_format_duration(time.time() - self._bridge_start_time))
            else:
                self._metric_vars["bridge_uptime"].set("\u2014")
        if "miner_uptime" in self._metric_vars:
            if self._miner_start_time and self.miner_process:
                self._metric_vars["miner_uptime"].set(_format_duration(time.time() - self._miner_start_time))
            else:
                self._metric_vars["miner_uptime"].set("\u2014")
        if "stratum_uptime" in self._metric_vars:
            since = self._metrics.get("stratum_since")
            if since and self.miner_process:
                self._metric_vars["stratum_uptime"].set(_format_duration(time.time() - since))
            else:
                self._metric_vars["stratum_uptime"].set("\u2014")
        if "bridge_restarts" in self._metric_vars:
            self._metric_vars["bridge_restarts"].set(str(self._bridge_restart_count))
        if "miner_restarts" in self._metric_vars:
            self._metric_vars["miner_restarts"].set(str(self._miner_restart_count))
        if "bridge_status" in self._metric_vars:
            self._metric_vars["bridge_status"].set("Running" if self.process else "Stopped")
        if "miner_status" in self._metric_vars:
            self._metric_vars["miner_status"].set("Running" if self.miner_process else "Stopped")
        if self._bridge_start_time and self.process:
            if time.time() - self._bridge_start_time > RESTART_RESET_AFTER_S and self._bridge_restart_count > 0:
                self._bridge_restart_count = 0
                self.log_message("[system] Bridge stable \u2014 restart counter reset.", "system")
        if self._miner_start_time and self.miner_process:
            if time.time() - self._miner_start_time > RESTART_RESET_AFTER_S and self._miner_restart_count > 0:
                self._miner_restart_count = 0
                self.log_message("[system] Miner stable \u2014 restart counter reset.", "system")
        self.after(1000, self._update_metrics_display)

    # ── Browse ──

    def _browse_binary(self, target: str) -> None:
        title = "Select bridge binary" if target == "bridge" else "Select XMRig binary"
        path = filedialog.askopenfilename(title=title,
                                          filetypes=[("Executable files", "*.exe"), ("All files", "*.*")])
        if path:
            (self.bridge_path if target == "bridge" else self.xmrig_path).set(path)

    # ── Graceful shutdown helper ──

    def _graceful_stop(self, proc: subprocess.Popen[str], name: str) -> None:
        try:
            proc.terminate()
            proc.wait(timeout=GRACEFUL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.after(0, lambda: self.log_message(
                f"[system] {name} did not stop in {GRACEFUL_TIMEOUT_S}s, force killing\u2026", "system"))
            self._force_kill_tree(proc)
        except OSError:
            pass

    @staticmethod
    def _force_kill_tree(proc: subprocess.Popen[str]) -> None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=5)
            else:
                proc.kill()
                proc.wait(timeout=3)
        except Exception:
            pass

    # ── Bridge process ──

    def start_bridge(self) -> None:
        if self.process:
            self.toast("Bridge is already running", "info"); return
        ok, msg = self._validate_all_bridge()
        if not ok:
            self.toast(msg, "error"); self.log_message(f"[system] Validation failed: {msg}", "system"); return
        net_ok, net_msg = self._check_network_consistency()
        if not net_ok:
            self.toast(f"\u26A0 {net_msg}", "warn")
            self.log_message(f"[system] Network warning: {net_msg}", "system")

        bridge_path = self.bridge_path.get().strip()
        cmd = [bridge_path, "--listen", self.listen.get().strip(),
               "--rpc-url", self.rpc_url.get().strip(),
               "--pay-address", self.pay_address.get().strip(),
               "--refresh-ms", self.refresh_ms.get().strip()]
        if self.extra_data_hex.get().strip():
            cmd += ["--extra-data-hex", self.extra_data_hex.get().strip()]
        if self.allow_non_daa.get():
            cmd += ["--allow-non-daa"]
        try:
            self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except OSError as exc:
            self.toast(f"Failed to start bridge: {exc}", "error")
            self.log_message(f"[system] Failed to start bridge: {exc}", "system"); return
        self._bridge_stopping = False; self._bridge_start_time = time.time()
        threading.Thread(target=self._read_bridge_logs, daemon=True).start()
        self.log_message("[bridge] Bridge started.", "bridge")
        self._set_bridge_status("running"); self.toast("Bridge started", "ok")
        if self.start_miner_with_bridge.get():
            self._wait_for_bridge_then_start_miner()

    def _read_bridge_logs(self) -> None:
        proc = self.process
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self.log_queue.put(f"[bridge] {line.rstrip()}")
        returncode = proc.wait()
        self.after(0, lambda rc=returncode: self._on_bridge_exited(rc))

    def _on_bridge_exited(self, returncode: int) -> None:
        if self._bridge_stopping:
            self._bridge_stopping = False; return
        self.process = None; self._bridge_start_time = None
        self.log_message(f"[bridge] Bridge exited unexpectedly (code {returncode}).", "bridge")
        self._set_miner_status("stopped")
        if self.miner_process:
            self.stop_miner()
        if self.auto_restart_bridge.get() and self._bridge_restart_count < MAX_RESTARTS:
            self._bridge_restart_count += 1
            backoff = min(RESTART_BACKOFF_BASE ** self._bridge_restart_count, RESTART_BACKOFF_MAX)
            self.log_message(f"[system] Auto-restart bridge in {backoff}s ({self._bridge_restart_count}/{MAX_RESTARTS})\u2026", "system")
            self.toast(f"Bridge crashed \u2014 restarting in {backoff}s", "warn")
            self._set_bridge_status("restarting")
            self.after(int(backoff * 1000), self._do_restart_bridge)
        else:
            self._set_bridge_status("idle")
            if self._bridge_restart_count >= MAX_RESTARTS:
                self.toast("Bridge max restarts reached", "error")

    def _do_restart_bridge(self) -> None:
        if not self.process:
            self.start_bridge()

    def stop_bridge(self) -> None:
        if not self.process:
            self.toast("Bridge is not running", "info"); return
        self._bridge_stopping = True; self._bridge_restart_count = 0
        proc = self.process; self.process = None; self._bridge_start_time = None
        self.log_message("[bridge] Stopping bridge\u2026", "bridge")
        self._set_bridge_status("idle"); self.toast("Bridge stopping", "info")
        def shutdown() -> None:
            self._graceful_stop(proc, "Bridge")
            self.after(0, lambda: self.log_message("[bridge] Bridge stopped.", "bridge"))
            self.after(0, lambda: self.toast("Bridge stopped", "ok"))
        threading.Thread(target=shutdown, daemon=True).start()
        if self.miner_process:
            self.stop_miner()

    # ── Sequential start ──

    def _wait_for_bridge_then_start_miner(self) -> None:
        listen = self.listen.get().strip()
        host, port_str = listen.rsplit(":", 1); port = int(port_str)
        if host == "0.0.0.0":
            host = "127.0.0.1"
        self.log_message("[system] Waiting for bridge port before starting miner\u2026", "system")
        def worker() -> None:
            for _ in range(60):
                if not self.process or self._bridge_stopping:
                    return
                try:
                    s = socket.create_connection((host, port), timeout=1); s.close()
                    self.after(0, lambda: self.log_message("[system] Bridge port ready \u2014 starting miner.", "system"))
                    self.after(0, self.start_miner); return
                except (socket.timeout, OSError):
                    time.sleep(0.5)
            self.after(0, lambda: self.toast("Timed out waiting for bridge", "error"))
            self.after(0, lambda: self.log_message("[system] Bridge port not ready after 30s.", "system"))
        threading.Thread(target=worker, daemon=True).start()

    # ── Miner process ──

    def start_miner(self) -> None:
        if self.miner_process:
            self.toast("Miner is already running", "info"); return
        ok, msg = self._validate_all_miner()
        if not ok:
            self.toast(msg, "error"); self.log_message(f"[system] Miner validation failed: {msg}", "system"); return
        xmrig_path = self.xmrig_path.get().strip()
        url = self.xmrig_url.get().strip(); address = self.pay_address.get().strip()
        cmd = [xmrig_path, "-o", url, "-u", address, "-p", "x"]
        extra = self.xmrig_extra.get().strip()
        if extra:
            try:
                cmd += shlex.split(extra)
            except ValueError as exc:
                self.toast(f"Invalid extra args: {exc}", "error"); return
        try:
            self.miner_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except OSError as exc:
            self.toast(f"Failed to start miner: {exc}", "error")
            self.log_message(f"[system] Failed to start miner: {exc}", "system")
            self.miner_process = None; return
        self._miner_stopping = False; self._miner_start_time = time.time()
        self._metrics["accepted"] = 0; self._metrics["rejected"] = 0
        self._metrics["reconnects"] = 0; self._metrics["stratum_since"] = None
        self._metrics["pool_latency"] = "\u2014"; self._metrics["last_share"] = "\u2014"
        for k in ("hashrate_10s", "hashrate_60s", "hashrate_15m", "hashrate_max"):
            self._metrics[k] = "\u2014"
        threading.Thread(target=self._read_miner_logs, daemon=True).start()
        self.log_message("[miner] Miner started.", "miner")
        self._set_miner_status("running"); self.toast("Miner started", "ok")

    def _read_miner_logs(self) -> None:
        proc = self.miner_process
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self.log_queue.put(f"[miner] {line.rstrip()}")
        returncode = proc.wait()
        self.after(0, lambda rc=returncode: self._on_miner_exited(rc))

    def _on_miner_exited(self, returncode: int) -> None:
        if self._miner_stopping:
            self._miner_stopping = False; return
        self.miner_process = None; self._miner_start_time = None
        self.log_message(f"[miner] Miner exited unexpectedly (code {returncode}).", "miner")
        self._set_miner_status("stopped")
        if self.auto_restart_miner.get() and self._miner_restart_count < MAX_RESTARTS:
            self._miner_restart_count += 1
            backoff = min(RESTART_BACKOFF_BASE ** self._miner_restart_count, RESTART_BACKOFF_MAX)
            self.log_message(f"[system] Auto-restart miner in {backoff}s ({self._miner_restart_count}/{MAX_RESTARTS})\u2026", "system")
            self.toast(f"Miner crashed \u2014 restarting in {backoff}s", "warn")
            self._set_miner_status("restarting")
            self.after(int(backoff * 1000), self._do_restart_miner)
        elif self._miner_restart_count >= MAX_RESTARTS:
            self.toast("Miner max restarts reached", "error")

    def _do_restart_miner(self) -> None:
        if not self.miner_process:
            self.start_miner()

    def stop_miner(self) -> None:
        if not self.miner_process:
            self.toast("Miner is not running", "info"); return
        self._miner_stopping = True; self._miner_restart_count = 0
        proc = self.miner_process; self.miner_process = None; self._miner_start_time = None
        self.log_message("[miner] Stopping miner\u2026", "miner")
        self._set_miner_status("stopped"); self.toast("Miner stopping", "info")
        def shutdown() -> None:
            self._graceful_stop(proc, "Miner")
            self.after(0, lambda: self.log_message("[miner] Miner stopped.", "miner"))
            self.after(0, lambda: self.toast("Miner stopped", "ok"))
        threading.Thread(target=shutdown, daemon=True).start()

    # ── Profile management ──

    def _current_profile_data(self) -> dict[str, Any]:
        return {
            "bridge_path": self.bridge_path.get(), "listen": self.listen.get(),
            "rpc_url": self.rpc_url.get(), "pay_address": self.pay_address.get(),
            "extra_data_hex": self.extra_data_hex.get(), "allow_non_daa": self.allow_non_daa.get(),
            "refresh_ms": int(self.refresh_ms.get() or 5000),
            "xmrig_path": self.xmrig_path.get(), "xmrig_url": self.xmrig_url.get(),
            "xmrig_extra": self.xmrig_extra.get(),
            "start_miner_with_bridge": self.start_miner_with_bridge.get(),
            "auto_restart_bridge": self.auto_restart_bridge.get(),
            "auto_restart_miner": self.auto_restart_miner.get(),
        }

    def _apply_profile(self, profile: dict[str, Any]) -> None:
        for key, var in [("bridge_path", self.bridge_path), ("listen", self.listen),
                         ("rpc_url", self.rpc_url), ("pay_address", self.pay_address),
                         ("extra_data_hex", self.extra_data_hex), ("xmrig_path", self.xmrig_path),
                         ("xmrig_url", self.xmrig_url), ("xmrig_extra", self.xmrig_extra)]:
            var.set(profile.get(key, _PROFILE_DEFAULTS.get(key, "")))
        self.refresh_ms.set(str(profile.get("refresh_ms", 5000)))
        for key, var in [("allow_non_daa", self.allow_non_daa),
                         ("start_miner_with_bridge", self.start_miner_with_bridge),
                         ("auto_restart_bridge", self.auto_restart_bridge),
                         ("auto_restart_miner", self.auto_restart_miner)]:
            var.set(profile.get(key, _PROFILE_DEFAULTS.get(key, False)))

    def _switch_profile(self, name: str) -> None:
        profiles = self._config.get("profiles", {})
        if name not in profiles:
            self.toast(f"Profile '{name}' not found", "error"); return
        self._config["active_profile"] = name; save_config(self._config)
        self._apply_profile(profiles[name])
        self.toast(f"Switched to profile: {name}", "ok")
        self.log_message(f"[system] Profile switched to: {name}", "system")

    def _save_as_profile(self) -> None:
        modal = self._create_modal("Save As Profile", accent=self.BLUE)
        modal.geometry("420x220"); modal.minsize(350, 200)
        content = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14); content.pack(fill="both", expand=True)
        name_var = tk.StringVar()
        tk.Label(content, text="Profile name", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))
        entry = self._make_entry(content, name_var)
        entry.pack(fill="x", ipady=7); entry.focus_set()
        footer = tk.Frame(content, bg=self.PANEL); footer.pack(fill="x", pady=(14, 0))
        footer.grid_columnconfigure(0, weight=1); footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="\u2715 Cancel", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        def do_save() -> None:
            n = name_var.get().strip()
            if not n:
                self.toast("Profile name is required", "error"); return
            profiles = self._config.setdefault("profiles", {})
            profiles[n] = self._current_profile_data()
            self._config["active_profile"] = n; save_config(self._config)
            self.profile_var.set(n)
            self.profile_combo["values"] = list(profiles.keys())
            modal.destroy(); self.toast(f"Profile '{n}' saved", "ok")
            self.log_message(f"[system] Profile saved: {n}", "system")
        AnimatedButton(footer, text="\u2713 Save", command=do_save,
                       base_bg="#dcfce7", hover_bg=self.SUCCESS, border_color="#86efac", fg="#166534").grid(row=0, column=1, padx=(6, 0), sticky="ew")

    def _delete_profile(self) -> None:
        name = self.profile_var.get()
        if name == "default":
            self.toast("Cannot delete the default profile", "info"); return
        profiles = self._config.get("profiles", {})
        if name in profiles:
            del profiles[name]
        self._config["active_profile"] = "default"; save_config(self._config)
        self.profile_var.set("default")
        self.profile_combo["values"] = list(profiles.keys())
        self._apply_profile(profiles.get("default", _PROFILE_DEFAULTS))
        self.toast(f"Profile '{name}' deleted", "ok")
        self.log_message(f"[system] Profile deleted: {name}", "system")

    # ── Diagnostic actions ──

    def _build_bridge_cmd(self) -> list[str]:
        bp = self.bridge_path.get().strip()
        cmd = [bp, "--listen", self.listen.get().strip(), "--rpc-url", self.rpc_url.get().strip(),
               "--pay-address", self.pay_address.get().strip(), "--refresh-ms", self.refresh_ms.get().strip()]
        if self.extra_data_hex.get().strip():
            cmd += ["--extra-data-hex", self.extra_data_hex.get().strip()]
        if self.allow_non_daa.get():
            cmd += ["--allow-non-daa"]
        return cmd

    def _build_miner_cmd(self) -> list[str]:
        xp = self.xmrig_path.get().strip()
        cmd = [xp, "-o", self.xmrig_url.get().strip(), "-u", self.pay_address.get().strip(), "-p", "x"]
        extra = self.xmrig_extra.get().strip()
        if extra:
            try:
                cmd += shlex.split(extra)
            except ValueError:
                pass
        return cmd

    def _copy_bridge_cmd(self) -> None:
        bp = self.bridge_path.get().strip()
        if not bp:
            self.toast("Bridge path not set", "error"); return
        self.clipboard_clear(); self.clipboard_append(shlex.join(self._build_bridge_cmd()))
        self.toast("Bridge command copied", "ok")

    def _copy_miner_cmd(self) -> None:
        xp = self.xmrig_path.get().strip()
        if not xp:
            self.toast("XMRig path not set", "error"); return
        self.clipboard_clear(); self.clipboard_append(shlex.join(self._build_miner_cmd()))
        self.toast("Miner command copied", "ok")

    def _open_data_dir(self) -> None:
        d = str(Path(__file__).parent)
        if os.name == "nt":
            os.startfile(d)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", d])
        self.toast("Opened data directory", "ok")

    def _export_logs(self) -> None:
        log_file = LOG_DIR / "miner_gui.log"
        if not log_file.exists():
            self.toast("No log file found yet", "info"); return
        dest = filedialog.asksaveasfilename(
            title="Export logs", defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=f"miner_gui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        if not dest:
            return
        try:
            shutil.copy2(str(log_file), dest)
            self.toast(f"Logs exported to {Path(dest).name}", "ok")
            self.log_message(f"[system] Logs exported to: {dest}", "system")
        except OSError as exc:
            self.toast(f"Export failed: {exc}", "error")

    def _preflight_check(self) -> None:
        self.log_message("[system] \u2550\u2550\u2550 PREFLIGHT CHECK \u2550\u2550\u2550", "system")
        all_ok = True
        checks: list[tuple[str, tuple[bool, str]]] = [
            ("Bridge binary", self._validate_binary_path(self.bridge_path.get().strip(), "Bridge")),
            ("Listen address", self._validate_listen(self.listen.get().strip())),
            ("RPC URL", self._validate_rpc_url(self.rpc_url.get().strip())),
            ("Pay address", self._validate_pay_address(self.pay_address.get().strip())),
            ("Refresh ms", self._validate_refresh_ms(self.refresh_ms.get().strip())),
            ("Network match", self._check_network_consistency()),
        ]
        xp = self.xmrig_path.get().strip()
        if xp:
            checks.append(("XMRig binary", self._validate_binary_path(xp, "XMRig")))
        for name, (ok, msg) in checks:
            if ok:
                self.log_message(f"  \u2713 {name}: OK", "system")
            else:
                self.log_message(f"  \u2717 {name}: {msg}", "system")
                all_ok = False
        if all_ok:
            self.log_message("[system] \u2550\u2550\u2550 ALL CHECKS PASSED \u2550\u2550\u2550", "system")
            self.toast("Preflight check passed", "ok")
        else:
            self.log_message("[system] \u2550\u2550\u2550 SOME CHECKS FAILED \u2550\u2550\u2550", "system")
            self.toast("Preflight check has failures", "error")

    # ── Settings ──

    def save_settings(self) -> None:
        refresh_str = self.refresh_ms.get().strip()
        try:
            int(refresh_str or "5000")
        except ValueError:
            self.toast("Refresh ms must be a number", "error"); return
        name = self._config.get("active_profile", "default")
        profiles = self._config.setdefault("profiles", {})
        profiles[name] = self._current_profile_data()
        save_config(self._config)
        self.log_message("[system] Settings saved.", "system")
        self.toast("Settings saved", "ok")

    def clear_log(self) -> None:
        self.output.config(state="normal"); self.output.delete("1.0", "end"); self.output.config(state="disabled")
        self.line_count_var.set("0 lines"); self.toast("Console cleared", "ok")

    # ── Dual status pills ──

    def _set_bridge_status(self, status: str) -> None:
        if status == "running":
            self.pill_bridge.config(text=" \u25CF  BRIDGE: ON ", bg="#dcfce7", fg=self.SUCCESS)
            self.status_var.set("\u25B8 Bridge running"); self.state_hint_var.set("Bridge active")
            self._sb_bridge_var.set("Bridge: running")
        elif status == "restarting":
            self.pill_bridge.config(text=" \u25CF  BRIDGE: RESTART ", bg=self.ORANGE_LIGHT, fg=self.ORANGE)
            self.status_var.set("\u25B8 Restarting\u2026")
            self.state_hint_var.set(f"Attempt {self._bridge_restart_count}/{MAX_RESTARTS}")
            self._sb_bridge_var.set(f"Bridge: restart {self._bridge_restart_count}/{MAX_RESTARTS}")
        else:
            self.pill_bridge.config(text=" \u25CF  BRIDGE: IDLE ", bg=self.BLUE_LIGHT, fg=self.BLUE)
            self.status_var.set("\u25B8 Bridge stopped"); self.state_hint_var.set("LMT native stratum mode")
            self._sb_bridge_var.set("Bridge: idle")

    def _set_miner_status(self, status: str) -> None:
        if status == "running":
            self.pill_miner.config(text=" \u25CF  MINER: ON ", bg="#dcfce7", fg=self.SUCCESS)
            self._sb_miner_var.set("Miner: running")
        elif status == "restarting":
            self.pill_miner.config(text=" \u25CF  MINER: RESTART ", bg=self.ORANGE_LIGHT, fg=self.ORANGE)
            self._sb_miner_var.set(f"Miner: restart {self._miner_restart_count}/{MAX_RESTARTS}")
        else:
            self.pill_miner.config(text=" \u25CF  MINER: OFF ", bg=self.BLUE_LIGHT, fg=self.MUTED)
            self._sb_miner_var.set("Miner: off")

    def _animate_status(self) -> None:
        if self.process:
            self._status_tick = not self._status_tick
            self.pill_bridge.config(fg=self.SUCCESS if self._status_tick else "#4ade80")
        if self.miner_process:
            self.pill_miner.config(fg=self.SUCCESS if self._status_tick else "#4ade80")
        self.after(600, self._animate_status)

    # ── Toast ──

    def toast(self, message: str, kind: str = "info") -> None:
        icons = {"ok": "\u2713", "error": "\u2717", "info": "\u25CF", "warn": "\u26A0"}
        colors = {"ok": ("#f0fdf4", "#166534", "#16a34a"), "error": ("#fef2f2", "#991b1b", "#dc2626"),
                  "info": ("#eff6ff", "#1e3a5f", "#2563eb"), "warn": ("#fffbeb", "#92400e", "#d97706")}
        bg, fg, accent = colors.get(kind, colors["info"]); icon = icons.get(kind, "\u25CF")
        tw = tk.Toplevel(self); tw.overrideredirect(True); tw.attributes("-topmost", True); tw.attributes("-alpha", 0.0)
        w, h = 380, 44; x = self.winfo_rootx() + self.winfo_width() - w - 20; y = self.winfo_rooty() + 20
        tw.geometry(f"{w}x{h}+{x}+{y}")
        border = tk.Frame(tw, bg=self.BORDER, padx=1, pady=1); border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg=bg); inner.pack(fill="both", expand=True)
        tk.Frame(inner, bg=accent, width=4).pack(side="left", fill="y")
        tk.Label(inner, text=f"  {icon}  {message}", bg=bg, fg=fg,
                 font=("Segoe UI Semibold", 10), anchor="w").pack(fill="both", expand=True, padx=(4, 14))
        def fade_in(a: float = 0.0) -> None:
            if a >= 0.97:
                tw.attributes("-alpha", 0.97); tw.after(2200, fade_out, 0.97); return
            tw.attributes("-alpha", a); tw.after(16, fade_in, a + 0.10)
        def fade_out(a: float) -> None:
            if a <= 0.0:
                tw.destroy(); return
            tw.attributes("-alpha", a); tw.after(16, fade_out, a - 0.12)
        fade_in()

    # ── Cleanup ──

    def on_close(self) -> None:
        procs: list[tuple[subprocess.Popen[str], str]] = []
        if self.process:
            self._bridge_stopping = True; procs.append((self.process, "Bridge")); self.process = None
        if self.miner_process:
            self._miner_stopping = True; procs.append((self.miner_process, "Miner")); self.miner_process = None
        if procs:
            def cleanup() -> None:
                for proc, name in procs:
                    self._graceful_stop(proc, name)
                self.after(0, self.destroy)
            threading.Thread(target=cleanup, daemon=True).start()
        else:
            self.destroy()


def main():
    app = BridgeGui()
    app.mainloop()


if __name__ == "__main__":
    main()
