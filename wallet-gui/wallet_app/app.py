from __future__ import annotations

import os
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from tkinter import filedialog, ttk

from .cli_bridge import (
    is_wallet_open_from_output,
    launch_interactive,
    map_cli_error,
    map_cli_error_action,
    parse_node_rich_info,
    parse_node_sync_hint,
    run_capture,
    run_capture_timed,
)
from .contacts import Contact, load_contacts, save_contacts_to_config
from .config import (
    CONFIG_PATH,
    DEFAULT_NETWORK,
    NETWORK_CHOICES,
    PROFILE_DEFAULTS,
    SESSION_TIMEOUT_CHOICES,
    active_profile,
    load_config,
    save_config,
)
from .history import HistoryPanel, HistoryStore
from .state import WalletState
from .tx_history import TransactionsPanel, parse_history_output
from .ui_components import AnimatedButton
from .validators import parse_nonnegative_fee, parse_positive_amount, validate_address

import sys as _sys
_FROZEN = getattr(_sys, "frozen", False)
_BUNDLE_DIR = Path(getattr(_sys, "_MEIPASS", "")) if _FROZEN else None
ASSETS_DIR = _BUNDLE_DIR / "assets" if _FROZEN else Path(__file__).resolve().parent.parent / "assets"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


class WalletGui(tk.Tk):
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
    MAX_WALLET_NAME = 64
    MAX_CONTACT_NAME = 48
    MAX_ADDRESS_TEXT = 120
    MAX_NOTE_TEXT = 140
    MAX_NUMERIC_TEXT = 24
    MAX_ACCOUNT_TEXT = 64

    def __init__(self) -> None:
        super().__init__()
        self._config = load_config()
        self._profile = active_profile(self._config)
        self.config_data = self._profile
        self.action_buttons: list[AnimatedButton] = []
        self.send_modal: tk.Toplevel | None = None
        self.transfer_modal: tk.Toplevel | None = None
        self.contacts_modal: tk.Toplevel | None = None
        self.account_suggestions: list[str] = []
        self.contacts: list[Contact] = load_contacts(self._profile)
        self.contact_choices_var = tk.StringVar()

        self.ws = WalletState(network=self._profile.get("network", DEFAULT_NETWORK))
        self.ws.refresh_cli(self._config)
        self.ws.add_listener(self._on_state_change)

        self.history_store = HistoryStore()
        self.history_panel: HistoryPanel | None = None
        self.tx_panel: TransactionsPanel | None = None
        self._node_vars: dict[str, tk.StringVar] = {}

        self._last_activity_time: float = time.time()
        self._session_timeout_after_id: str | None = None
        self._session_timeout_lock_dialog_open = False

        self.title("Lapis Monetae Wallet")
        self.geometry("700x600")
        self.minsize(480, 600)
        self.configure(bg=self.BG)
        self._set_window_icon()
        self._build_style()
        self._build_menubar()
        self._build_layout()
        self._sync_ui_to_state()
        self.log("Welcome to Lapis Monetae Wallet. Configure CLI and network, then run an action.")
        self.history_store.add("system", "GUI started", "ok")
        if self.history_panel:
            self.history_panel.refresh()
        self.after(2000, self._poll_node_status)
        self._schedule_session_timeout()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ── Activity / session timeout ──

    def _record_activity(self) -> None:
        self._last_activity_time = time.time()

    def _schedule_session_timeout(self) -> None:
        if self._session_timeout_after_id:
            self.after_cancel(self._session_timeout_after_id)
            self._session_timeout_after_id = None
        timeout_min = self._profile.get("session_timeout_minutes", 0) or 0
        if timeout_min <= 0:
            return
        self._session_timeout_after_id = self.after(60_000, self._session_timeout_check)

    def _session_timeout_check(self) -> None:
        self._session_timeout_after_id = None
        timeout_min = self._profile.get("session_timeout_minutes", 0) or 0
        if timeout_min <= 0 or not self.ws.wallet_open or self._session_timeout_lock_dialog_open:
            self._schedule_session_timeout()
            return
        elapsed_min = (time.time() - self._last_activity_time) / 60.0
        if elapsed_min < timeout_min:
            self._schedule_session_timeout()
            return
        auto = self._profile.get("auto_lock_on_timeout", True)
        if auto:
            self.action_lock()
            self.toast("Wallet locked due to inactivity", "info")
            self._schedule_session_timeout()
            return
        self._session_timeout_lock_dialog_open = True

        def on_lock_now() -> None:
            self._session_timeout_lock_dialog_open = False
            self.action_lock()
            self.toast("Wallet locked", "info")

        def on_stay() -> None:
            self._session_timeout_lock_dialog_open = False
            self._record_activity()
            self._schedule_session_timeout()

        self._show_choice_modal(
            "Session timeout",
            f"Wallet inactive for {timeout_min}+ min. Lock now?",
            [("Lock now", on_lock_now), ("Stay unlocked", on_stay)],
        )

    def _show_choice_modal(self, title: str, message: str,
                           buttons: list[tuple[str, Callable[[], None]]]) -> None:
        modal = self._create_modal(title, accent=self.ORANGE)
        modal.geometry("420x180")
        tk.Label(modal, text=message, bg=self.PANEL, fg=self.FG,
                 font=("Segoe UI", 10), wraplength=380, justify="left").pack(padx=20, pady=14, fill="x")
        bf = tk.Frame(modal, bg=self.PANEL)
        bf.pack(fill="x", padx=20, pady=(0, 14))
        for i, (label, cmd) in enumerate(buttons):
            AnimatedButton(bf, text=label, command=lambda c=cmd: (modal.destroy(), c()),
                           base_bg="#edf0f7", hover_bg=self.BLUE, border_color=self.BORDER).pack(side="left", padx=(0, 8))

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
        style.configure("Light.TCombobox", fieldbackground=self.INPUT_BG, background="#ffffff",
                        foreground=self.FG, arrowcolor=self.MUTED, bordercolor=self.BORDER,
                        lightcolor="#ffffff", darkcolor=self.BORDER,
                        selectbackground=self.BLUE, selectforeground="#ffffff")
        style.map("Light.TCombobox", fieldbackground=[("readonly", self.INPUT_BG)],
                  foreground=[("readonly", self.FG)], bordercolor=[("focus", self.BLUE)])
        style.configure("Light.TCheckbutton", background=self.PANEL, foreground=self.FG, font=("Segoe UI", 8))
        style.map("Light.TCheckbutton", background=[("active", self.PANEL)])

    # ── Menubar ──

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self, bg=self.PANEL, fg=self.FG, activebackground=self.BLUE,
                          activeforeground="#ffffff", font=("Segoe UI", 9), relief="flat")
        file_menu = tk.Menu(menubar, tearoff=0, bg=self.PANEL, fg=self.FG,
                            activebackground=self.BLUE, activeforeground="#ffffff",
                            font=("Segoe UI", 9))
        file_menu.add_command(label="\u2699  Settings", command=self._open_settings_modal)
        file_menu.add_command(label="Open config folder", command=self._open_config_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0, bg=self.PANEL, fg=self.FG,
                             activebackground=self.BLUE, activeforeground="#ffffff",
                             font=("Segoe UI", 9))
        tools_menu.add_command(label="\u2713  Preflight Check", command=self._preflight_check)
        tools_menu.add_command(label="\u2715  Clear Output", command=self.clear_output)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.config(menu=menubar)

    # ── Layout ──

    def _build_layout(self) -> None:
        outer = tk.Frame(self, bg=self.BG, padx=8, pady=4)
        outer.pack(fill="both", expand=True)
        self._build_header(outer)
        self._build_profile_bar(outer)
        self._build_main_notebook(outer)
        self._build_statusbar()

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
        tk.Label(title_row, text="Lapis Monetae Wallet", bg=self.BG, fg=self.FG,
                 font=("Segoe UI Semibold", 14)).pack(side="left")
        self.pill_status = tk.Label(title_row, text=" \u25CF  READY ", bg=self.BLUE_LIGHT,
                                    fg=self.BLUE, font=("Segoe UI Semibold", 7), padx=6, pady=1)
        self.pill_status.pack(side="right")
        self.pill_backup = tk.Label(title_row, text="", bg=self.BG, fg=self.BG,
                                    font=("Segoe UI Semibold", 7), padx=4, pady=1)
        self.pill_backup.pack(side="right", padx=(0, 4))
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

    # ── Status bar (bottom) ──

    def _build_statusbar(self) -> None:
        tk.Frame(self, bg=self.BORDER, height=1).pack(side="bottom", fill="x")
        sb = tk.Frame(self, bg=self.PANEL, padx=8, pady=2)
        sb.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar()
        self.node_status_var = tk.StringVar(value="Node: unknown")
        self.node_detail_var = tk.StringVar(value="")
        tk.Label(sb, textvariable=self.status_var, bg=self.PANEL, fg=self.MUTED,
                 font=("Consolas", 7)).pack(side="left", padx=(0, 10))
        tk.Label(sb, textvariable=self.node_status_var, bg=self.PANEL, fg=self.MUTED,
                 font=("Consolas", 7)).pack(side="right")

    # ── Main notebook ──

    def _build_main_notebook(self, parent: tk.Frame) -> None:
        style = ttk.Style()
        style.configure("Main.TNotebook", background=self.BG, borderwidth=0)
        style.configure("Main.TNotebook.Tab", font=("Segoe UI Semibold", 8),
                        padding=[8, 3], background=self.BG, foreground=self.MUTED)
        style.map("Main.TNotebook.Tab", background=[("selected", self.PANEL)],
                  foreground=[("selected", self.BLUE)])
        self.notebook = ttk.Notebook(parent, style="Main.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        self._build_config_tab(self.notebook)
        self._build_actions_tab(self.notebook)
        self._build_output_tab(self.notebook)
        self._build_history_tab(self.notebook)
        self._build_tx_tab(self.notebook)
        self._build_node_tab(self.notebook)

    # ── Config tab ──

    def _build_config_tab(self, notebook: ttk.Notebook) -> None:
        tab = tk.Frame(notebook, bg=self.BG)
        sc = tk.Canvas(tab, bg=self.BG, highlightthickness=0, bd=0)
        ss = tk.Scrollbar(tab, orient="vertical", command=sc.yview)
        sc.configure(yscrollcommand=ss.set)
        ss.pack(side="right", fill="y"); sc.pack(side="left", fill="both", expand=True)
        panel = tk.Frame(sc, bg=self.PANEL, padx=10, pady=6)
        sw = sc.create_window((0, 0), window=panel, anchor="nw")

        tk.Label(panel, text="CLI Path", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        er = tk.Frame(panel, bg=self.PANEL); er.pack(fill="x", pady=(0, 4))
        self.cli_path_var = tk.StringVar(value=self._profile.get("cli_path", ""))
        tk.Entry(er, textvariable=self.cli_path_var, bg=self.INPUT_BG, fg=self.FG,
                 insertbackground=self.FG, relief="flat", font=("Consolas", 8),
                 highlightthickness=1, highlightcolor=self.BLUE,
                 highlightbackground=self.BORDER).pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 4))
        AnimatedButton(er, text="\u2026", command=self.on_browse_cli,
                       base_bg="#edf0f7", hover_bg=self.BLUE, border_color=self.BORDER,
                       height=26, font=("Segoe UI Semibold", 8)).pack(side="left", padx=(0, 4))
        AnimatedButton(er, text="\u2713 Save", command=self.on_save_cli_path,
                       base_bg="#edf0f7", hover_bg="#16a34a", border_color=self.BORDER,
                       height=26, font=("Segoe UI Semibold", 8)).pack(side="left")

        r2 = tk.Frame(panel, bg=self.PANEL); r2.pack(fill="x", pady=(0, 4))
        nf = tk.Frame(r2, bg=self.PANEL); nf.pack(side="left", fill="x", padx=(0, 8))
        tk.Label(nf, text="Network", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self.network_var = tk.StringVar(value=self.ws.network)
        nb = ttk.Combobox(nf, values=NETWORK_CHOICES, textvariable=self.network_var,
                          state="readonly", style="Light.TCombobox", width=10)
        nb.pack(anchor="w", ipady=1)
        nb.bind("<<ComboboxSelected>>", lambda _: self.on_network_change())

        wf = tk.Frame(r2, bg=self.PANEL); wf.pack(side="left", fill="x", expand=True)
        tk.Label(wf, text="Wallet Name (optional)", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        self.wallet_name_var = tk.StringVar(value=self._profile.get("last_wallet", ""))
        wne = tk.Entry(wf, textvariable=self.wallet_name_var, bg=self.INPUT_BG, fg=self.FG,
                       insertbackground=self.FG, relief="flat", font=("Segoe UI", 8),
                       highlightthickness=1, highlightcolor=self.BLUE, highlightbackground=self.BORDER)
        self._bind_max_length(wne, self.MAX_WALLET_NAME)
        wne.pack(fill="x", ipady=4)

        panel.bind("<Configure>", lambda _: sc.configure(scrollregion=sc.bbox("all")))
        sc.bind("<Configure>", lambda e: sc.itemconfig(sw, width=e.width))
        notebook.add(tab, text=" \u2699 Config ")

    # ── Actions tab (Wallet / Accounts / Transactions buttons) ──

    def _build_actions_tab(self, notebook: ttk.Notebook) -> None:
        tab = tk.Frame(notebook, bg=self.BG)
        sc = tk.Canvas(tab, bg=self.BG, highlightthickness=0, bd=0)
        ss = tk.Scrollbar(tab, orient="vertical", command=sc.yview)
        sc.configure(yscrollcommand=ss.set)
        ss.pack(side="right", fill="y"); sc.pack(side="left", fill="both", expand=True)
        panel = tk.Frame(sc, bg=self.BG, padx=6, pady=4)
        sw = sc.create_window((0, 0), window=panel, anchor="nw")

        self._build_button_row(panel, "\u26BF Wallet", self.BLUE, [
            ("\u2726 Create", self.action_create, self.BLUE),
            ("\u2B07 Import", self.action_import, "#3b82f6"),
            ("\u2750 Open", self.action_open, "#2563eb"),
            ("\u21BA Open Last", self.action_open_last_wallet, "#1d4ed8"),
            ("Lock", self.action_lock, "#64748b"),
            ("\u2691 Backup", self.action_backup, "#7c3aed"),
        ])
        self._build_button_row(panel, "\u2637 Accounts", self.TEAL, [
            ("\u2630 List", lambda: self._guarded_capture(["wallet", "list"], "wallet", "Wallet list", require_wallet=False), self.TEAL),
            ("\u2261 Balances", self.action_list_balances, "#0e7490"),
            ("\u2316 Address", lambda: self._guarded_capture(["address"], "address", "Show address", require_wallet=True), "#0d9488"),
            ("\u271A New Addr", lambda: self._guarded_capture(["address", "new"], "address", "Generate new address", require_wallet=True), "#059669"),
        ])
        self._build_button_row(panel, "\u26A1 Transactions", self.ORANGE, [
            ("\u27A4 Send", self.open_send_modal, "#d97706"),
            ("\u21C4 Transfer", self.open_transfer_modal, "#ea580c"),
            ("\u2630 Tx History", self.refresh_transactions, "#ca8a04"),
            ("\u260E Contacts", self.open_contacts_modal, "#7c3aed"),
        ])

        panel.bind("<Configure>", lambda _: sc.configure(scrollregion=sc.bbox("all")))
        sc.bind("<Configure>", lambda e: sc.itemconfig(sw, width=e.width))
        sc.bind("<Enter>", lambda _: sc.bind_all("<MouseWheel>", lambda ev: sc.yview_scroll(int(-1 * (ev.delta / 120)), "units")))
        sc.bind("<Leave>", lambda _: sc.unbind_all("<MouseWheel>"))
        notebook.add(tab, text=" \u26A1 Actions ")

    def _build_button_row(self, parent: tk.Frame, title: str, accent: str,
                          buttons: list[tuple[str, Any, str]]) -> None:
        row = tk.Frame(parent, bg=self.GROUP_BG, padx=4, pady=3,
                       highlightbackground=self.BORDER, highlightthickness=1)
        row.pack(fill="x", pady=2)
        tb = tk.Frame(row, bg=self.GROUP_BG)
        tb.pack(fill="x", pady=(0, 2))
        dot = tk.Canvas(tb, width=7, height=7, bg=self.GROUP_BG, highlightthickness=0, bd=0)
        dot.pack(side="left", padx=(1, 3))
        dot.create_oval(1, 1, 6, 6, fill=accent, outline=accent)
        tk.Label(tb, text=title, bg=self.GROUP_BG, fg=accent, font=("Segoe UI Semibold", 8)).pack(side="left")
        bg = tk.Frame(row, bg=self.GROUP_BG)
        bg.pack(fill="x")
        for i, (label, command, hover) in enumerate(buttons):
            bg.grid_columnconfigure(i, weight=1, uniform="btn")
            btn = AnimatedButton(bg, text=label, command=command, base_bg="#edf0f7",
                                 hover_bg=hover, border_color=self.BORDER, fg="#1e293b",
                                 hover_fg="#ffffff", height=28, font=("Segoe UI Semibold", 8))
            btn.grid(row=0, column=i, padx=2, pady=1, sticky="ew")
            self.action_buttons.append(btn)

    # ── Output tab ──

    def _build_output_tab(self, notebook: ttk.Notebook) -> None:
        of = tk.Frame(notebook, bg=self.PANEL, padx=6, pady=4)
        oh = tk.Frame(of, bg=self.PANEL); oh.pack(fill="x", pady=(0, 2))
        self.line_count_var = tk.StringVar(value="0 lines")
        tk.Label(oh, textvariable=self.line_count_var, bg=self.PANEL, fg="#a0aab8",
                 font=("Consolas", 7)).pack(side="right")
        tb = tk.Frame(of, bg=self.BORDER, padx=1, pady=1)
        tb.pack(fill="both", expand=True)
        ys = tk.Scrollbar(tb, orient="vertical"); ys.pack(side="right", fill="y")
        xs = tk.Scrollbar(tb, orient="horizontal"); xs.pack(side="bottom", fill="x")
        self.output = tk.Text(tb, bg=self.TEXT_BG, fg="#334155", insertbackground=self.FG,
                              relief="flat", wrap="none", font=("Consolas", 8), padx=6, pady=4,
                              yscrollcommand=ys.set, xscrollcommand=xs.set, borderwidth=0,
                              selectbackground=self.BLUE_LIGHT, selectforeground=self.FG)
        self.output.pack(fill="both", expand=True)
        ys.config(command=self.output.yview); xs.config(command=self.output.xview)
        self.output.tag_configure("ts", foreground=self.BLUE)
        self.output.tag_configure("err", foreground=self.ERROR)
        self.output.tag_configure("ok", foreground=self.SUCCESS)
        self.output.config(state="disabled")
        notebook.add(of, text=" \u2630 Output ")

    # ── History tab ──

    def _build_history_tab(self, notebook: ttk.Notebook) -> None:
        hf = tk.Frame(notebook, bg=self.BG)
        self.history_panel = HistoryPanel(hf, self.history_store)
        notebook.add(hf, text=" \u2637 History ")

    # ── Transactions tab ──

    def _build_tx_tab(self, notebook: ttk.Notebook) -> None:
        tf = tk.Frame(notebook, bg=self.BG)
        self.tx_panel = TransactionsPanel(tf)
        notebook.add(tf, text=" \u27A6 Tx ")

    # ── Node tab ──

    def _build_node_tab(self, notebook: ttk.Notebook) -> None:
        no = tk.Frame(notebook, bg=self.BG)
        nc = tk.Canvas(no, bg=self.BG, highlightthickness=0, bd=0)
        ns = tk.Scrollbar(no, orient="vertical", command=nc.yview)
        nc.configure(yscrollcommand=ns.set)
        ns.pack(side="right", fill="y"); nc.pack(side="left", fill="both", expand=True)
        nf = tk.Frame(nc, bg=self.BG, padx=8, pady=6)
        nw = nc.create_window((0, 0), window=nf, anchor="nw")

        keys = ("node_status", "latency", "last_update", "daa_score", "tip_hash",
                "header_count", "block_count", "peers", "difficulty", "network_name")
        for k in keys:
            self._node_vars[k] = tk.StringVar(value="\u2014")
        self._node_vars["node_status"].set("Unknown")

        self._build_node_card(nf, "\u25CF Connection", self.BLUE, [
            ("Status", self._node_vars["node_status"]),
            ("Latency", self._node_vars["latency"]),
            ("Updated", self._node_vars["last_update"]),
        ]).pack(fill="x", pady=(0, 4))
        self._build_node_card(nf, "\u2637 DAG", self.TEAL, [
            ("DAA Score", self._node_vars["daa_score"]),
            ("Tip Hash", self._node_vars["tip_hash"]),
            ("Headers", self._node_vars["header_count"]),
            ("Blocks", self._node_vars["block_count"]),
        ]).pack(fill="x", pady=(0, 4))
        self._build_node_card(nf, "\u26A1 Network", self.ORANGE, [
            ("Peers", self._node_vars["peers"]),
            ("Difficulty", self._node_vars["difficulty"]),
            ("Network", self._node_vars["network_name"]),
        ]).pack(fill="x", pady=(0, 4))

        nf.bind("<Configure>", lambda _: nc.configure(scrollregion=nc.bbox("all")))
        nc.bind("<Configure>", lambda e: nc.itemconfig(nw, width=e.width))
        nc.bind("<Enter>", lambda _: nc.bind_all("<MouseWheel>", lambda ev: nc.yview_scroll(int(-1 * (ev.delta / 120)), "units")))
        nc.bind("<Leave>", lambda _: nc.unbind_all("<MouseWheel>"))
        notebook.add(no, text=" \u25CF Node ")

    def _build_node_card(self, parent: tk.Frame, title: str, accent: str,
                         rows: list[tuple[str, tk.StringVar]]) -> tk.Frame:
        card = tk.Frame(parent, bg=self.PANEL, padx=8, pady=5,
                        highlightbackground=self.BORDER, highlightthickness=1)
        tb = tk.Frame(card, bg=self.PANEL)
        tb.pack(fill="x", pady=(0, 4))
        dot = tk.Canvas(tb, width=7, height=7, bg=self.PANEL, highlightthickness=0, bd=0)
        dot.pack(side="left", padx=(1, 3))
        dot.create_oval(1, 1, 6, 6, fill=accent, outline=accent)
        tk.Label(tb, text=title, bg=self.PANEL, fg=accent, font=("Segoe UI Semibold", 9)).pack(side="left")
        for lt, var in rows:
            r = tk.Frame(card, bg=self.PANEL); r.pack(fill="x", pady=1)
            tk.Label(r, text=lt, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8), width=10, anchor="w").pack(side="left")
            tk.Label(r, textvariable=var, bg=self.PANEL, fg=self.FG, font=("Consolas", 9), anchor="w").pack(side="left", fill="x", expand=True)
        return card

    # ── Widget helpers ──

    def _create_modal(self, title: str, accent: str = "#2563eb") -> tk.Toplevel:
        modal = tk.Toplevel(self)
        modal.title(title); modal.configure(bg=self.BG)
        modal.transient(self); modal.grab_set()
        modal.geometry("620x460"); modal.minsize(520, 360); modal.resizable(True, True)
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

    def _labeled_entry(self, parent: tk.Frame, row: int, label: str,
                       variable: tk.StringVar, max_length: int | None = None) -> None:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.grid(row=row, column=0, sticky="ew", pady=5)
        tk.Label(frame, text=label, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 3))
        entry = tk.Entry(frame, textvariable=variable, bg=self.INPUT_BG, fg=self.FG,
                         insertbackground=self.FG, relief="flat", font=("Consolas", 11),
                         highlightthickness=1, highlightcolor=self.BLUE, highlightbackground=self.BORDER)
        if max_length is not None:
            self._bind_max_length(entry, max_length)
        entry.pack(fill="x", ipady=7)
        parent.grid_columnconfigure(0, weight=1)

    def _bind_max_length(self, entry: tk.Entry, max_length: int) -> None:
        vcmd = (self.register(lambda proposed: len(proposed) <= max_length), "%P")
        entry.configure(validate="key", validatecommand=vcmd)

    def _labeled_combo(self, parent: tk.Frame, row: int, label: str,
                       variable: tk.StringVar, values: list[str]) -> ttk.Combobox:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.grid(row=row, column=0, sticky="ew", pady=6)
        tk.Label(frame, text=label, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 4))
        combo = ttk.Combobox(frame, textvariable=variable, values=values, style="Light.TCombobox")
        combo.pack(fill="x", ipady=6)
        parent.grid_columnconfigure(0, weight=1)
        return combo

    # ── State synchronisation ──

    def _on_state_change(self) -> None:
        self.after(0, self._sync_ui_to_state)

    def _sync_ui_to_state(self) -> None:
        self.status_var.set(f"\u25B8 {self.ws.status_text()}")
        if not self.ws.node_connected:
            self.node_status_var.set("Node: disconnected")
        elif self.ws.node_synced is None:
            self.node_status_var.set("Node: connected")
        elif self.ws.node_synced:
            self.node_status_var.set("Node: synced")
        else:
            self.node_status_var.set("Node: syncing")
        parts: list[str] = []
        ri = self.ws.node_rich_info
        if ri:
            if ri.daa_score:
                parts.append(f"DAA: {ri.daa_score}")
            if ri.peers:
                parts.append(f"Peers: {ri.peers}")
            if ri.tip_hash:
                parts.append(f"Tip: {ri.tip_hash}")
            if ri.latency_ms > 0:
                parts.append(f"Latency: {ri.latency_ms:.0f}ms")
            self._node_vars.get("node_status", tk.StringVar()).set(
                "Synced" if self.ws.node_synced else ("Syncing" if self.ws.node_synced is False else "Connected") if self.ws.node_connected else "Disconnected")
            self._node_vars.get("latency", tk.StringVar()).set(f"{ri.latency_ms:.0f} ms" if ri.latency_ms > 0 else "\u2014")
            self._node_vars.get("daa_score", tk.StringVar()).set(ri.daa_score or "\u2014")
            self._node_vars.get("tip_hash", tk.StringVar()).set(ri.tip_hash or "\u2014")
            self._node_vars.get("header_count", tk.StringVar()).set(ri.header_count or "\u2014")
            self._node_vars.get("block_count", tk.StringVar()).set(ri.block_count or "\u2014")
            self._node_vars.get("peers", tk.StringVar()).set(ri.peers or "\u2014")
            self._node_vars.get("difficulty", tk.StringVar()).set(ri.difficulty or "\u2014")
            self._node_vars.get("network_name", tk.StringVar()).set(ri.network_name or "\u2014")
        else:
            for k in self._node_vars:
                if k == "node_status":
                    self._node_vars[k].set("Disconnected" if not self.ws.node_connected else "Unknown")
                else:
                    self._node_vars[k].set("\u2014")
        if self.ws.node_status_updated_at:
            parts.append(f"Updated: {self.ws.node_status_updated_at}")
            self._node_vars.get("last_update", tk.StringVar()).set(self.ws.node_status_updated_at)
        self.node_detail_var.set("  |  ".join(parts) if parts else "")
        text, bg, fg = self.ws.pill_info()
        self.pill_status.config(text=text, bg=bg, fg=fg)
        self._update_backup_pill()
        btn_state = "disabled" if self.ws.busy else "normal"
        for i, btn in enumerate(self.action_buttons):
            if i == 4:
                btn.config(state="normal" if (self.ws.wallet_open and not self.ws.busy) else "disabled")
            else:
                btn.config(state=btn_state)

    def _update_backup_pill(self) -> None:
        if self.ws.wallet_open and self.ws.wallet_name:
            backups = self._profile.get("seed_backup_confirmed", {})
            if not backups.get(self.ws.wallet_name):
                self.pill_backup.config(text=" \u26A0 BACKUP ", bg="#fef3c7", fg="#92400e")
                return
        self.pill_backup.config(text="", bg=self.BG, fg=self.BG)

    # ── Logging ──

    def log(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.output.config(state="normal")
        self.output.insert("end", f"[{ts}] ", ("ts",))
        stripped = text.rstrip()
        tag: tuple[str, ...] = ()
        if stripped.startswith("ERROR") or "[stderr]" in stripped:
            tag = ("err",)
        elif "Exit code: 0" in stripped:
            tag = ("ok",)
        self.output.insert("end", stripped + "\n", tag)
        self.output.see("end")
        self.output.config(state="disabled")
        lines = int(self.output.index("end-1c").split(".")[0])
        self.line_count_var.set(f"{lines} lines")

    # ── CLI configuration ──

    def on_browse_cli(self) -> None:
        path = filedialog.askopenfilename(title="Select CLI executable",
                                          filetypes=[("Executable files", "*.exe"), ("All files", "*.*")])
        if path:
            self.cli_path_var.set(path)

    def on_save_cli_path(self) -> None:
        self._profile["cli_path"] = self.cli_path_var.get().strip()
        self._persist_profile()
        self.ws.refresh_cli(self._config)
        self.log("CLI path saved.")
        self.toast("CLI path saved", "ok")
        self.history_panel and self.history_panel.add_and_refresh("system", "CLI path saved", "ok")

    def _save_last_wallet(self, wallet_name: str) -> None:
        normalized = wallet_name.strip()
        if not normalized:
            return
        self._profile["last_wallet"] = normalized
        self._persist_profile()

    def _save_contacts(self) -> None:
        save_contacts_to_config(self._profile, self.contacts)
        self._persist_profile()

    def on_network_change(self) -> None:
        net = self.network_var.get().strip() or DEFAULT_NETWORK
        self._profile["network"] = net
        self._persist_profile()
        self.ws.set_network(net)
        self.log(f"Network saved: {net}")
        self.toast(f"Active network: {net}", "info")
        self.history_panel and self.history_panel.add_and_refresh("network", f"Network changed to {net}", "ok")

    def _persist_profile(self) -> None:
        name = self._config.get("active_profile", "default")
        self._config.setdefault("profiles", {})[name] = self._profile
        save_config(self._config)

    # ── Profile management ──

    def _switch_profile(self, name: str) -> None:
        profiles = self._config.get("profiles", {})
        if name not in profiles:
            self.toast(f"Profile '{name}' not found", "error"); return
        self._config["active_profile"] = name
        save_config(self._config)
        self._profile = profiles[name]
        self.config_data = self._profile
        self.cli_path_var.set(self._profile.get("cli_path", ""))
        self.network_var.set(self._profile.get("network", DEFAULT_NETWORK))
        self.wallet_name_var.set(self._profile.get("last_wallet", ""))
        self.contacts = load_contacts(self._profile)
        self.ws.refresh_cli(self._config)
        self.ws.set_network(self._profile.get("network", DEFAULT_NETWORK))
        self._schedule_session_timeout()
        self.toast(f"Switched to profile: {name}", "ok")
        self.log(f"Profile switched to: {name}")

    def _save_as_profile(self) -> None:
        modal = self._create_modal("Save As Profile", accent=self.BLUE)
        modal.geometry("420x220"); modal.minsize(350, 200)
        content = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        content.pack(fill="both", expand=True)
        name_var = tk.StringVar()
        tk.Label(content, text="Profile name", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))
        entry = tk.Entry(content, textvariable=name_var, bg=self.INPUT_BG, fg=self.FG,
                         insertbackground=self.FG, relief="flat", font=("Consolas", 11),
                         highlightthickness=1, highlightcolor=self.BLUE, highlightbackground=self.BORDER)
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
            profiles[n] = dict(self._profile)
            self._config["active_profile"] = n
            self._profile = profiles[n]; self.config_data = self._profile
            save_config(self._config)
            self.profile_var.set(n)
            self.profile_combo["values"] = list(profiles.keys())
            modal.destroy(); self.toast(f"Profile '{n}' saved", "ok")
        AnimatedButton(footer, text="\u2713 Save", command=do_save,
                       base_bg="#dcfce7", hover_bg=self.SUCCESS, border_color="#86efac", fg="#166534").grid(row=0, column=1, padx=(6, 0), sticky="ew")

    def _delete_profile(self) -> None:
        name = self.profile_var.get()
        if name == "default":
            self.toast("Cannot delete the default profile", "info"); return
        profiles = self._config.get("profiles", {})
        if name in profiles:
            del profiles[name]
        self._config["active_profile"] = "default"
        save_config(self._config)
        self._profile = profiles.get("default", dict(PROFILE_DEFAULTS))
        self.config_data = self._profile
        self.profile_var.set("default")
        self.profile_combo["values"] = list(profiles.keys())
        self._switch_profile("default")
        self.toast(f"Profile '{name}' deleted", "ok")

    # ── Settings modal ──

    def _open_settings_modal(self) -> None:
        modal = self._create_modal("\u2699  Settings", accent=self.MUTED)
        modal.geometry("520x380"); modal.minsize(460, 320)
        content = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        content.pack(fill="both", expand=True)

        tk.Label(content, text="Session lock (inactivity)", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))
        tf = tk.Frame(content, bg=self.PANEL); tf.pack(fill="x", pady=(0, 8))
        timeout_var = tk.StringVar(value=str(self._profile.get("session_timeout_minutes", 0)))
        tc = ttk.Combobox(tf, values=[str(m) for m in SESSION_TIMEOUT_CHOICES],
                          textvariable=timeout_var, state="readonly", style="Light.TCombobox", width=6)
        tc.pack(side="left", padx=(0, 8))
        tk.Label(tf, text="min (0 = off)", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(0, 12))
        auto_lock_var = tk.BooleanVar(value=bool(self._profile.get("auto_lock_on_timeout", True)))
        ttk.Checkbutton(tf, text="Auto-lock on timeout", variable=auto_lock_var,
                        style="Light.TCheckbutton").pack(side="left")

        tk.Frame(content, bg=self.BORDER, height=1).pack(fill="x", pady=10)

        af = tk.Frame(content, bg=self.PANEL); af.pack(fill="x", pady=(0, 8))
        AnimatedButton(af, text="Copy CLI path", command=lambda: self._copy_to_clipboard(self.cli_path_var.get()),
                       base_bg="#edf0f7", hover_bg=self.MUTED, border_color=self.BORDER, height=32).pack(side="left", padx=(0, 8))
        AnimatedButton(af, text="Open config folder", command=self._open_config_folder,
                       base_bg="#edf0f7", hover_bg=self.BLUE, border_color=self.BORDER, height=32).pack(side="left")

        tk.Frame(content, bg=self.BORDER, height=1).pack(fill="x", pady=10)

        def save_settings() -> None:
            try:
                m = int(timeout_var.get().strip())
            except ValueError:
                m = 0
            if m not in SESSION_TIMEOUT_CHOICES:
                m = 0
            self._profile["session_timeout_minutes"] = m
            self._profile["auto_lock_on_timeout"] = auto_lock_var.get()
            self._persist_profile()
            self._schedule_session_timeout()
            modal.destroy()
            self.toast("Settings saved", "ok")

        footer = tk.Frame(content, bg=self.PANEL); footer.pack(fill="x", pady=(8, 0))
        AnimatedButton(footer, text="\u2715 Close", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER).pack(side="left", padx=(0, 8))
        AnimatedButton(footer, text="\u2713 Save Settings", command=save_settings,
                       base_bg="#dcfce7", hover_bg=self.SUCCESS, border_color="#86efac", fg="#166534").pack(side="left")

    # ── Guarded action runners ──

    def _require_cli(self) -> str | None:
        self.ws.refresh_cli(self._config)
        if not self.ws.cli_available:
            self.log("ERROR: CLI binary not found. Set a path or define LMT_CLI_BIN.")
            self.toast("CLI was not found", "error")
            return None
        return self.ws.cli_binary

    def _guarded_capture(self, args: list[str], category: str, description: str,
                         ensure_network: bool = False, require_wallet: bool = False) -> None:
        self._record_activity()
        ok, reason = self.ws.can_run_action()
        if not ok:
            self.toast(reason, "info"); return
        if require_wallet:
            ok_w, reason_w = self.ws.can_send()
            if not ok_w:
                self.toast(reason_w, "info"); return
        self.history_panel and self.history_panel.add_and_refresh(category, description, "pending")  # type: ignore[arg-type]
        self.run_capture_action(args, ensure_network=ensure_network, require_wallet=require_wallet)

    def run_capture_action(self, args: list[str], ensure_network: bool = False,
                           on_complete: Callable[[int, str], None] | None = None,
                           require_wallet: bool = False) -> None:
        binary = self._require_cli()
        if not binary:
            return
        if require_wallet:
            ok_w, reason_w = self.ws.can_send()
            if not ok_w:
                self.toast(reason_w, "info"); return
        self.ws.set_busy(True)

        def worker() -> None:
            try:
                if ensure_network:
                    net_code, net_out = run_capture(binary, ["network", self.ws.network])
                    self.after(0, lambda: self.log(net_out))
                    if net_code != 0:
                        self.after(0, lambda: self.toast("Failed to select network", "error"))
                        self.after(0, lambda: self._finish_action("error", "Network selection failed"))
                        return
                code, out = run_capture(binary, args)
                self.after(0, lambda: self.log(out))
                self.after(0, lambda: self.log(f"Exit code: {code}\n"))
                status = "ok" if code == 0 else "error"
                friendly, action_key = map_cli_error_action(code, out)
                toast_msg = "Command completed" if code == 0 else friendly
                self.after(0, lambda: self.toast(toast_msg, status))
                if code != 0 and action_key:
                    self.after(0, lambda: self._show_error_action_dialog(friendly, action_key))
                if on_complete:
                    self.after(0, lambda: on_complete(code, out))
                detail = f"Exit code: {code}" if code == 0 else f"{friendly} (exit code: {code})"
                self.after(0, lambda: self._finish_action(status, detail))
            except Exception as e:
                self.after(0, lambda: self.log(f"ERROR: {e}\n"))
                self.after(0, lambda: self.toast("Command failed unexpectedly", "error"))
                self.after(0, lambda: self._finish_action("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_error_action_dialog(self, message: str, action_key: str) -> None:
        actions = {
            "open_wallet": ("Open wallet", self._focus_open_wallet),
            "select_network": ("Change network", self._focus_network),
            "wait_sync": ("OK", lambda: None),
            "check_node": ("Check node connection", self._focus_status),
        }
        label, cmd = actions.get(action_key, ("OK", lambda: None))
        modal = self._create_modal("Action suggested", accent=self.ORANGE)
        modal.geometry("400x160")
        tk.Label(modal, text=message, bg=self.PANEL, fg=self.FG,
                 font=("Segoe UI", 10), wraplength=360).pack(padx=20, pady=14, fill="x")
        bf = tk.Frame(modal, bg=self.PANEL); bf.pack(fill="x", padx=20, pady=(0, 14))
        AnimatedButton(bf, text=label, command=lambda: (modal.destroy(), cmd()),
                       base_bg=self.ORANGE_LIGHT, hover_bg=self.ORANGE, border_color="#fbbf24").pack(side="left", padx=(0, 8))
        AnimatedButton(bf, text="Dismiss", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER).pack(side="left")

    def _focus_open_wallet(self) -> None:
        self.focus_set()
        self.toast("Use 'Open' or 'Open Last' to open a wallet", "info")

    def _focus_network(self) -> None:
        self.focus_set()
        self.toast("Select network in the config panel above", "info")

    def _focus_status(self) -> None:
        self.focus_set()
        self.toast("Check Node status and ensure the node is running with --utxoindex", "info")

    def _finish_action(self, status: str, detail: str = "") -> None:
        self.ws.set_busy(False)
        if self.history_panel:
            self.history_panel.update_last_and_refresh(status, detail)  # type: ignore[arg-type]

    # ── Preflight check ──

    def _preflight_interactive(self) -> tuple[bool, list[str]]:
        warnings: list[str] = []
        hard_fail = False
        self.ws.refresh_cli(self._config)
        if not self.ws.cli_available:
            warnings.append("\u2717 CLI binary not found")
            hard_fail = True
        else:
            warnings.append("\u2713 CLI binary: OK")
        if self.ws.node_connected:
            if self.ws.node_synced:
                warnings.append("\u2713 Node: synced")
            elif self.ws.node_synced is False:
                warnings.append("\u26A0 Node: syncing (operations may fail)")
            else:
                warnings.append("\u2713 Node: connected")
        else:
            warnings.append("\u2717 Node: disconnected")
            hard_fail = True
        if self.ws.wallet_open:
            warnings.append(f"\u2713 Wallet open: {self.ws.wallet_name}")
        else:
            warnings.append("\u25CF Wallet: not open")
        return not hard_fail, warnings

    def _preflight_check(self) -> None:
        ok, checks = self._preflight_interactive()
        self.log("[preflight] \u2550\u2550\u2550 PREFLIGHT CHECK \u2550\u2550\u2550")
        for c in checks:
            self.log(f"  {c}")
        if ok:
            self.log("[preflight] \u2550\u2550\u2550 ALL CHECKS PASSED \u2550\u2550\u2550")
            self.toast("Preflight check passed", "ok")
        else:
            self.log("[preflight] \u2550\u2550\u2550 SOME CHECKS FAILED \u2550\u2550\u2550")
            self.toast("Preflight has failures", "error")

    def run_interactive_action(self, args: list[str], category: str = "wallet",
                               description: str = "Interactive command") -> None:
        self._record_activity()
        ok, reason = self.ws.can_run_action()
        if not ok:
            self.toast(reason, "info"); return
        binary = self._require_cli()
        if not binary:
            return

        pf_ok, pf_msgs = self._preflight_interactive()
        if not pf_ok:
            for m in pf_msgs:
                if m.startswith("\u2717"):
                    self.toast(m, "error")
            return

        soft_warns = [m for m in pf_msgs if m.startswith("\u26A0")]
        if soft_warns:
            for m in soft_warns:
                self.log(f"[preflight] {m}")
            self.toast(soft_warns[0], "warn")

        self.run_capture_action(["network", self.ws.network], ensure_network=False)
        launched, message = launch_interactive(binary, args)
        self.log(message)
        status = "ok" if launched else "error"
        self.toast("Interactive command launched" if launched else "Error opening interactive console",
                   "info" if launched else "error")
        self.history_panel and self.history_panel.add_and_refresh(category, description, status, message)  # type: ignore[arg-type]
        if launched and len(args) >= 2 and args[0] == "wallet" and args[1] == "open":
            target_name = args[2] if len(args) >= 3 else self._wallet_name()
            self.ws.set_wallet_open_pending(target_name)
            self._verify_wallet_open_async(target_name)
        if launched and len(args) >= 2 and args[0] == "wallet" and args[1] == "create":
            target_name = args[2] if len(args) >= 3 else self._wallet_name()
            self.after(5000, lambda: self._post_creation_backup_reminder(target_name))

    # ── Wallet actions ──

    def _wallet_name(self) -> str:
        return self.wallet_name_var.get().strip()

    def action_create(self) -> None:
        name = self._wallet_name()
        self._show_seed_backup_checklist(name)

    def _show_seed_backup_checklist(self, name: str) -> None:
        modal = self._create_modal("\u2691  Seed Backup Checklist", accent="#7c3aed")
        modal.geometry("540x380"); modal.minsize(480, 340)
        content = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        content.pack(fill="both", expand=True)
        tk.Label(content, text="Before creating a wallet, confirm the following:",
                 bg=self.PANEL, fg=self.FG, font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(0, 10))

        checks = [
            tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar(),
        ]
        labels = [
            "I have a safe place to write down my seed phrase",
            "I understand the seed is shown only once during creation",
            "I will not screenshot or store the seed digitally",
        ]
        for var, text in zip(checks, labels):
            ttk.Checkbutton(content, text=text, variable=var, style="Light.TCheckbutton").pack(anchor="w", pady=2)

        proceed_btn = AnimatedButton(content, text="\u2726  Proceed to Create", command=lambda: None,
                                     base_bg="#dcfce7", hover_bg=self.SUCCESS, border_color="#86efac", fg="#166534")
        proceed_btn.pack(fill="x", pady=(14, 0))
        proceed_btn.config(state="disabled")

        def check_all() -> None:
            if all(v.get() for v in checks):
                proceed_btn.config(state="normal")
            else:
                proceed_btn.config(state="disabled")

        for v in checks:
            v.trace_add("write", lambda *_: check_all())

        def do_create() -> None:
            modal.destroy()
            args = ["wallet", "create"]
            if name:
                args.append(name)
                self._save_last_wallet(name)
            self.run_interactive_action(args, "wallet", f"Create wallet{f' ({name})' if name else ''}")

        proceed_btn.command = do_create
        proceed_btn.bind("<ButtonRelease-1>", lambda _: do_create() if all(v.get() for v in checks) else None)

    def _post_creation_backup_reminder(self, wallet_name: str) -> None:
        if not wallet_name:
            wallet_name = self._wallet_name() or "default"

        def on_yes() -> None:
            backups = self._profile.setdefault("seed_backup_confirmed", {})
            backups[wallet_name] = True
            self._persist_profile()
            self.toast("Backup confirmed", "ok")
            self._update_backup_pill()

        def on_no() -> None:
            self.toast("Please back up your seed phrase as soon as possible!", "warn")

        self._show_choice_modal(
            "Seed Backup Confirmation",
            f"Did you write down the 24-word seed phrase for wallet '{wallet_name}'?",
            [("Yes, I saved it", on_yes), ("No, not yet", on_no)],
        )

    def action_backup(self) -> None:
        self._record_activity()
        if not self.ws.wallet_open:
            self.toast("Open a wallet first", "info"); return
        self.run_interactive_action(["wallet", "export"], "wallet", "Export wallet seed")

    def action_import(self) -> None:
        args = ["wallet", "import"]
        name = self._wallet_name()
        if name:
            args.append(name)
            self._save_last_wallet(name)
        self.run_interactive_action(args, "wallet", f"Import wallet{f' ({name})' if name else ''}")

    def action_open(self) -> None:
        args = ["wallet", "open"]
        name = self._wallet_name()
        if name:
            args.append(name)
            self._save_last_wallet(name)
        self.run_interactive_action(args, "wallet", f"Open wallet{f' ({name})' if name else ''}")

    def action_open_last_wallet(self) -> None:
        self._record_activity()
        last_wallet = str(self._profile.get("last_wallet", "")).strip()
        if not last_wallet:
            self.toast("No last wallet is saved yet", "info"); return
        self.wallet_name_var.set(last_wallet)
        self.run_interactive_action(["wallet", "open", last_wallet], "wallet",
                                    f"Open last wallet ({last_wallet})")

    def action_lock(self) -> None:
        self._record_activity()
        ok, reason = self.ws.can_run_action()
        if not ok:
            self.toast(reason, "info"); return
        if not self.ws.wallet_open:
            self.toast("Wallet is not open", "info"); return
        binary = self._require_cli()
        if not binary:
            return
        self.ws.set_busy(True)
        self.history_panel and self.history_panel.add_and_refresh("wallet", "Lock wallet", "pending")  # type: ignore[arg-type]

        def worker() -> None:
            code, out = run_capture(binary, ["wallet", "close"])
            self.after(0, lambda: self.log(out))
            self.after(0, lambda: self.log(f"Exit code: {code}\n"))
            if code == 0:
                self.after(0, self.ws.close_wallet)
                self.after(0, lambda: self.toast("Wallet locked", "ok"))
                self.after(0, lambda: self._finish_action("ok", "Wallet closed"))
            else:
                friendly = map_cli_error(code, out)
                self.after(0, lambda: self.toast(friendly or "Failed to close wallet", "error"))
                self.after(0, lambda: self._finish_action("error", friendly or "Close failed"))

        threading.Thread(target=worker, daemon=True).start()

    def action_list_balances(self) -> None:
        self._guarded_capture(["list"], "wallet", "List account balances", ensure_network=True, require_wallet=True)

    def _verify_wallet_open_async(self, wallet_name: str) -> None:
        binary = self._require_cli()
        if not binary:
            self.ws.close_wallet(); return

        def worker() -> None:
            verified = False
            for _ in range(6):
                code, out = run_capture(binary, ["list"])
                if is_wallet_open_from_output(code, out):
                    verified = True; break
                threading.Event().wait(2.0)
            if verified:
                self.after(0, lambda: self.ws.open_wallet(wallet_name))
                self.after(0, self._record_activity)
                self.after(0, self._schedule_session_timeout)
                self.after(0, lambda: self.toast(f"Wallet '{wallet_name or 'default'}' verified open", "ok"))
                self.after(0, lambda: self.history_panel and self.history_panel.add_and_refresh("wallet", "Wallet open verified", "ok"))
            else:
                self.after(0, self.ws.close_wallet)
                self.after(0, lambda: self.toast("Wallet open could not be verified yet", "warn"))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_node_status(self) -> None:
        self.ws.refresh_cli(self._config)
        binary = self.ws.cli_binary
        if not binary or self.ws.busy:
            self.after(12000, self._poll_node_status); return

        def worker() -> None:
            ping_code, _ping_out, latency = run_capture_timed(binary, ["ping"])
            if ping_code != 0:
                self.after(0, lambda: self.ws.set_node_status(False, None))
                self.after(0, lambda: self.ws.set_node_rich_info(None, ""))
                self.after(12000, self._poll_node_status); return
            list_code, list_out = run_capture(binary, ["list"])
            connected, synced = parse_node_sync_hint(list_out) if list_code == 0 else (True, None)
            self.after(0, lambda: self.ws.set_node_status(connected, synced))
            dag_out = peers_out = ""
            try:
                dag_code, dag_out = run_capture(binary, ["rpc", "get_block_dag_info"])
                if dag_code != 0:
                    dag_out = ""
                peer_code, peers_out = run_capture(binary, ["rpc", "get_connected_peer_info"])
                if peer_code != 0:
                    peers_out = ""
            except Exception:
                pass
            updated_at = datetime.now().strftime("%H:%M:%S")
            rich = parse_node_rich_info(list_out, dag_out, peers_out, latency_ms=latency)
            self.after(0, lambda: self.ws.set_node_rich_info(rich, updated_at))
            self.after(12000, self._poll_node_status)

        threading.Thread(target=worker, daemon=True).start()

    # ── Send modal ──

    def open_send_modal(self) -> None:
        self._record_activity()
        ok, reason = self.ws.can_send()
        if not ok:
            self.toast(reason, "info"); return
        if self.send_modal and self.send_modal.winfo_exists():
            self.send_modal.focus_force(); return
        modal = self._create_modal("\u27A4  Send LMT", accent=self.ORANGE)
        modal.geometry("620x500"); modal.minsize(560, 420)
        self.send_modal = modal
        content = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        content.pack(fill="both", expand=True)
        recipient_var = tk.StringVar()
        amount_var = tk.StringVar()
        fee_var = tk.StringVar(value="0")
        contact_choice_var = tk.StringVar()
        contact_values = self._contact_display_values()
        row = 0
        if contact_values:
            cc = self._labeled_combo(content, row, "Saved contact (optional)", contact_choice_var, contact_values)
            row += 1
            cc.bind("<<ComboboxSelected>>", lambda _: recipient_var.set(self._resolve_contact_address(contact_choice_var.get().strip())))
        self._labeled_entry(content, row, "Recipient address", recipient_var, self.MAX_ADDRESS_TEXT)
        self._labeled_entry(content, row + 1, "Amount (LMT)", amount_var, self.MAX_NUMERIC_TEXT)
        self._labeled_entry(content, row + 2, "Priority fee (LMT, optional)", fee_var, self.MAX_NUMERIC_TEXT)
        footer = tk.Frame(content, bg=self.PANEL)
        footer.grid(row=row + 3, column=0, sticky="ew", pady=(14, 0))
        footer.grid_columnconfigure(0, weight=1); footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="\u2715  Cancel", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(footer, text="\u27A4  Confirm & Send",
                       command=lambda: self._submit_send(recipient_var.get(), amount_var.get(), fee_var.get(), modal),
                       base_bg=self.ORANGE_LIGHT, hover_bg=self.ORANGE, border_color="#fbbf24", fg="#92400e").grid(row=0, column=1, padx=(6, 0), sticky="ew")

    # ── Transfer modal ──

    def open_transfer_modal(self) -> None:
        self._record_activity()
        ok, reason = self.ws.can_send()
        if not ok:
            self.toast(reason, "info"); return
        if self.transfer_modal and self.transfer_modal.winfo_exists():
            self.transfer_modal.focus_force(); return
        modal = self._create_modal("\u21C4  Transfer Between Accounts", accent=self.BLUE)
        modal.geometry("620x500"); modal.minsize(560, 420)
        self.transfer_modal = modal
        content = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        content.pack(fill="both", expand=True)
        account_var = tk.StringVar()
        amount_var = tk.StringVar()
        fee_var = tk.StringVar(value="0")
        self._labeled_combo(content, 0, "Target account (name or id)", account_var, self.account_suggestions)
        self._labeled_entry(content, 1, "Amount (LMT)", amount_var, self.MAX_NUMERIC_TEXT)
        self._labeled_entry(content, 2, "Priority fee (LMT, optional)", fee_var, self.MAX_NUMERIC_TEXT)
        footer = tk.Frame(content, bg=self.PANEL)
        footer.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        footer.grid_columnconfigure(0, weight=1); footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="\u2715  Cancel", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(footer, text="\u21C4  Confirm & Transfer",
                       command=lambda: self._submit_transfer(account_var.get(), amount_var.get(), fee_var.get(), modal),
                       base_bg=self.BLUE_LIGHT, hover_bg=self.BLUE, border_color="#93c5fd", fg="#1e3a5f").grid(row=0, column=1, padx=(6, 0), sticky="ew")
        if not self.account_suggestions:
            self.refresh_account_suggestions(silent=True)

    # ── Submit handlers ──

    def _submit_send(self, address: str, amount: str, fee: str, modal: tk.Toplevel) -> None:
        result = validate_address(address, self.ws.network)
        if not result:
            self.toast(result.error, "error"); return
        parsed_amount = parse_positive_amount(amount)
        if parsed_amount is None:
            self.toast("Amount must be a positive number", "error"); return
        parsed_fee = parse_nonnegative_fee(fee)
        if parsed_fee is None:
            self.toast("Priority fee must be a non-negative number", "error"); return
        normalized = address.strip().lower()
        total = parsed_amount + parsed_fee
        if ":" in normalized:
            prefix, payload = normalized.split(":", 1)
            addr_hi = f"{prefix}:{payload[:10]}...{payload[-10:]}" if len(payload) >= 24 else normalized
        else:
            addr_hi = normalized
        modal.destroy()
        self._confirm_send_action(self.ws.network, addr_hi, normalized, parsed_amount, parsed_fee, total,
                                  lambda: self.run_interactive_action(["send", normalized, f"{parsed_amount:.8f}", f"{parsed_fee:.8f}"], "send", f"Send {parsed_amount:.8f} LMT"))

    def _submit_transfer(self, target_account: str, amount: str, fee: str, modal: tk.Toplevel) -> None:
        account = target_account.strip()
        if not account:
            self.toast("Target account is required", "error"); return
        if len(account) > self.MAX_ACCOUNT_TEXT:
            self.toast(f"Target account is too long (max {self.MAX_ACCOUNT_TEXT})", "error"); return
        parsed_amount = parse_positive_amount(amount)
        if parsed_amount is None:
            self.toast("Amount must be a positive number", "error"); return
        parsed_fee = parse_nonnegative_fee(fee)
        if parsed_fee is None:
            self.toast("Priority fee must be a non-negative number", "error"); return
        modal.destroy()
        self._confirm_action("Confirm Transfer",
                             [f"Target account: {account}", f"Amount: {parsed_amount:.8f} LMT",
                              f"Priority fee: {parsed_fee:.8f} LMT", "",
                              "This will open an interactive CLI console for wallet secrets."],
                             lambda: self.run_interactive_action(["transfer", account, f"{parsed_amount:.8f}", f"{parsed_fee:.8f}"],
                                                                "transfer", f"Transfer {parsed_amount:.8f} LMT to {account}"))

    def _confirm_action(self, title: str, lines: list[str], on_confirm: Callable[[], None]) -> None:
        modal = self._create_modal(title, accent=self.ORANGE)
        modal.geometry("620x380"); modal.minsize(560, 320)
        container = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        container.pack(fill="both", expand=True)
        for line in lines:
            fg = self.FG if line and not line.startswith(" ") else self.MUTED
            tk.Label(container, text=line, bg=self.PANEL, fg=fg, font=("Segoe UI", 10), justify="left").pack(anchor="w", pady=1)
        footer = tk.Frame(container, bg=self.PANEL)
        footer.pack(fill="x", pady=(18, 0))
        footer.grid_columnconfigure(0, weight=1); footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="\u2715  Cancel", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(footer, text="\u2713  Proceed", command=lambda: (modal.destroy(), on_confirm()),
                       base_bg="#dcfce7", hover_bg=self.SUCCESS, border_color="#86efac", fg="#166534").grid(row=0, column=1, padx=(6, 0), sticky="ew")

    def _confirm_send_action(self, network: str, address_display: str, address_full: str,
                             amount: float, fee: float, total: float, on_confirm: Callable[[], None]) -> None:
        modal = self._create_modal("Confirm Send", accent=self.ORANGE)
        modal.geometry("640x420"); modal.minsize(560, 380)
        container = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        container.pack(fill="both", expand=True)
        for line in [f"Network: {network}", f"Estimated fee: {fee:.8f} LMT",
                     f"Amount: {amount:.8f} LMT", f"Total (amount + fee): {total:.8f} LMT", "",
                     "Address (verify before sending):", address_display, "", "Full address:",
                     address_full[:40] + "..." if len(address_full) > 40 else address_full, "",
                     "This will open an interactive CLI console for wallet secrets."]:
            fg = self.FG if line and not line.startswith(" ") else self.MUTED
            tk.Label(container, text=line, bg=self.PANEL, fg=fg, font=("Segoe UI", 10), justify="left").pack(anchor="w", pady=1)
        footer = tk.Frame(container, bg=self.PANEL)
        footer.pack(fill="x", pady=(18, 0))
        footer.grid_columnconfigure(0, weight=1); footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="\u2715  Cancel", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(footer, text="\u2713  Proceed", command=lambda: (modal.destroy(), on_confirm()),
                       base_bg="#dcfce7", hover_bg=self.SUCCESS, border_color="#86efac", fg="#166534").grid(row=0, column=1, padx=(6, 0), sticky="ew")

    # ── Account suggestions ──

    def _extract_account_suggestions(self, output: str) -> list[str]:
        suggestions: list[str] = []
        seen: set[str] = set()
        for raw_line in output.splitlines():
            line = ANSI_ESCAPE_RE.sub("", raw_line)
            match = re.match(r"^\s{2,}\u2022\s+(.+)$", line)
            if not match:
                continue
            candidate = match.group(1).strip()
            if ":" in candidate and candidate.split(":", 1)[0] in {"lmt", "lmttest", "lmtsim", "lmtdev"}:
                continue
            if candidate.startswith("\u2022 "):
                continue
            if candidate and candidate not in seen:
                seen.add(candidate)
                suggestions.append(candidate)
        return suggestions

    def refresh_account_suggestions(self, silent: bool = False) -> None:
        ok, reason = self.ws.can_run_action()
        if not ok:
            if not silent:
                self.toast(reason, "info")
            return
        binary = self._require_cli()
        if not binary:
            return

        def worker() -> None:
            net_code, net_out = run_capture(binary, ["network", self.ws.network])
            if net_code != 0:
                self.after(0, lambda: self.log(net_out))
                if not silent:
                    self.after(0, lambda: self.toast("Failed to select network for account refresh", "error"))
                return
            code, out = run_capture(binary, ["list"])
            suggestions = self._extract_account_suggestions(out) if code == 0 else []

            def apply_results() -> None:
                self.log(out)
                if suggestions:
                    self.account_suggestions = suggestions
                    if self.transfer_modal and self.transfer_modal.winfo_exists():
                        self.transfer_modal.destroy()
                        self.open_transfer_modal()
                    if not silent:
                        self.toast(f"Loaded {len(suggestions)} account suggestions", "ok")
                elif not silent:
                    self.toast("No account suggestions found (open wallet first)", "info")

            self.after(0, apply_results)

        threading.Thread(target=worker, daemon=True).start()

    # ── Transactions tab refresh ──

    def refresh_transactions(self) -> None:
        ok, reason = self.ws.can_run_action()
        if not ok:
            self.toast(reason, "info"); return
        self.history_panel and self.history_panel.add_and_refresh("wallet", "Refresh transactions", "pending")  # type: ignore[arg-type]

        def on_history_complete(code: int, out: str) -> None:
            if not self.tx_panel:
                return
            rows = parse_history_output(out) if code == 0 else []
            self.tx_panel.set_rows(rows)
            if code == 0 and rows:
                self.toast(f"Loaded {len(rows)} transaction rows", "ok")
            elif code == 0:
                self.toast("No transactions parsed. Try using wallet history first.", "info")

        self.run_capture_action(["history", "list", "30"], ensure_network=True,
                                on_complete=on_history_complete, require_wallet=True)

    # ── Contacts / address book ──

    def _contact_display_values(self) -> list[str]:
        return [f"{c.name} ({c.address[:20]}...)" for c in self.contacts]

    def _resolve_contact_address(self, selected: str) -> str:
        for contact in self.contacts:
            label = f"{contact.name} ({contact.address[:20]}...)"
            if selected == label:
                return contact.address
        return selected

    def open_contacts_modal(self) -> None:
        if self.contacts_modal and self.contacts_modal.winfo_exists():
            self.contacts_modal.focus_force(); return
        modal = self._create_modal("\u260E  Manage Contacts", accent="#7c3aed")
        modal.geometry("760x620"); modal.minsize(720, 500)
        self.contacts_modal = modal
        container = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        container.pack(fill="both", expand=True)
        listbox = tk.Listbox(container, bg=self.TEXT_BG, fg=self.FG, relief="flat", font=("Segoe UI", 9))
        listbox.pack(fill="both", expand=True, pady=(0, 10))
        form = tk.Frame(container, bg=self.PANEL); form.pack(fill="x")

        def refresh_listbox() -> None:
            listbox.delete(0, "end")
            for c in self.contacts:
                text = f"{c.name}  |  {c.address}"
                if c.note:
                    text += f"  |  {c.note}"
                listbox.insert("end", text)

        name_var = tk.StringVar(); addr_var = tk.StringVar(); note_var = tk.StringVar()
        self._labeled_entry(form, 0, "Name", name_var, self.MAX_CONTACT_NAME)
        self._labeled_entry(form, 1, "Address", addr_var, self.MAX_ADDRESS_TEXT)
        self._labeled_entry(form, 2, "Note (optional)", note_var, self.MAX_NOTE_TEXT)
        actions = tk.Frame(form, bg=self.PANEL)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        for i in range(5):
            actions.grid_columnconfigure(i, weight=1, minsize=80)
        editing_index: list[int] = []

        def add_contact() -> None:
            result = validate_address(addr_var.get(), self.ws.network)
            if not result:
                self.toast(result.error, "error"); return
            name = name_var.get().strip()
            if not name:
                self.toast("Contact name is required", "error"); return
            addr = addr_var.get().strip(); note = note_var.get().strip()
            al = addr.lower(); nl = name.lower()
            self.contacts = [c for c in self.contacts if c.address.strip().lower() != al and c.name.strip().lower() != nl]
            self.contacts.append(Contact(name=name, address=addr, note=note))
            self._save_contacts(); refresh_listbox(); editing_index.clear()
            name_var.set(""); addr_var.set(""); note_var.set("")
            self.toast("Contact saved", "ok")

        def update_contact() -> None:
            if not editing_index or editing_index[0] < 0 or editing_index[0] >= len(self.contacts):
                self.toast("Select a contact to edit first", "info"); return
            result = validate_address(addr_var.get(), self.ws.network)
            if not result:
                self.toast(result.error, "error"); return
            name = name_var.get().strip()
            if not name:
                self.toast("Contact name is required", "error"); return
            self.contacts[editing_index[0]] = Contact(name=name, address=addr_var.get().strip(), note=note_var.get().strip())
            self._save_contacts(); refresh_listbox(); editing_index.clear()
            name_var.set(""); addr_var.set(""); note_var.set("")
            self.toast("Contact updated", "ok")

        def edit_selected() -> None:
            sel = listbox.curselection()
            if not sel:
                self.toast("Select a contact to edit", "info"); return
            idx = sel[0]
            if 0 <= idx < len(self.contacts):
                c = self.contacts[idx]
                name_var.set(c.name); addr_var.set(c.address); note_var.set(c.note)
                editing_index[:] = [idx]

        def copy_selected_address() -> None:
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            if 0 <= idx < len(self.contacts):
                self.clipboard_clear(); self.clipboard_append(self.contacts[idx].address)
                self.toast("Address copied", "ok")

        def remove_selected() -> None:
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            if 0 <= idx < len(self.contacts):
                self.contacts.pop(idx); self._save_contacts(); refresh_listbox(); editing_index.clear()
                name_var.set(""); addr_var.set(""); note_var.set("")
                self.toast("Contact removed", "ok")

        AnimatedButton(actions, text="+ Add", command=add_contact, base_bg="#ede9fe", hover_bg="#7c3aed", border_color="#ddd6fe").grid(row=0, column=0, padx=(0, 4), sticky="ew")
        AnimatedButton(actions, text="Edit", command=edit_selected, base_bg="#dbeafe", hover_bg="#2563eb", border_color="#93c5fd").grid(row=0, column=1, padx=4, sticky="ew")
        AnimatedButton(actions, text="Update", command=update_contact, base_bg="#dcfce7", hover_bg="#16a34a", border_color="#86efac").grid(row=0, column=2, padx=4, sticky="ew")
        AnimatedButton(actions, text="Copy addr", command=copy_selected_address, base_bg="#f1f5f9", hover_bg="#64748b", border_color=self.BORDER).grid(row=0, column=3, padx=4, sticky="ew")
        AnimatedButton(actions, text="- Remove", command=remove_selected, base_bg="#fee2e2", hover_bg="#dc2626", border_color="#fecaca").grid(row=0, column=4, padx=(4, 0), sticky="ew")
        refresh_listbox()

    # ── Misc ──

    def _copy_to_clipboard(self, text: str) -> None:
        if not (text and text.strip()):
            return
        self.clipboard_clear()
        self.clipboard_append(text.strip())
        self.toast("Copied to clipboard", "ok")

    def _open_config_folder(self) -> None:
        folder = CONFIG_PATH.parent
        if not folder.exists():
            self.toast("Config folder not found", "warn"); return
        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            else:
                import subprocess as sp
                sp.run(["open", str(folder)] if os.name == "darwin" else ["xdg-open", str(folder)], check=False)
        except (OSError, Exception):
            self.toast("Could not open folder", "error")

    def clear_output(self) -> None:
        self.output.config(state="normal")
        self.output.delete("1.0", "end")
        self.output.config(state="disabled")
        self.line_count_var.set("0 lines")
        self.toast("Output cleared", "ok")

    def toast(self, message: str, kind: str = "info") -> None:
        icons = {"ok": "\u2713", "error": "\u2717", "info": "\u25CF", "warn": "\u26A0"}
        colors = {"ok": ("#f0fdf4", "#166534", "#16a34a"), "error": ("#fef2f2", "#991b1b", "#dc2626"),
                  "info": ("#eff6ff", "#1e3a5f", "#2563eb"), "warn": ("#fffbeb", "#92400e", "#d97706")}
        bg, fg, accent = colors.get(kind, colors["info"])
        icon = icons.get(kind, "\u25CF")
        tw = tk.Toplevel(self); tw.overrideredirect(True); tw.attributes("-topmost", True); tw.attributes("-alpha", 0.0)
        w, h = 380, 44
        x = self.winfo_rootx() + self.winfo_width() - w - 20
        y = self.winfo_rooty() + 20
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
