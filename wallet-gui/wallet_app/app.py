from __future__ import annotations

import re
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from tkinter import filedialog, ttk

from .cli_bridge import (
    is_wallet_open_from_output,
    launch_interactive,
    map_cli_error,
    parse_node_sync_hint,
    run_capture,
)
from .contacts import Contact, load_contacts, save_contacts_to_config
from .config import DEFAULT_NETWORK, NETWORK_CHOICES, load_config, save_config
from .history import HistoryPanel, HistoryStore
from .state import WalletState
from .tx_history import TransactionsPanel, parse_history_output
from .ui_components import AnimatedButton
from .validators import parse_nonnegative_fee, parse_positive_amount, validate_address

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
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
    MAX_WALLET_NAME = 64
    MAX_CONTACT_NAME = 48
    MAX_ADDRESS_TEXT = 120
    MAX_NOTE_TEXT = 140
    MAX_NUMERIC_TEXT = 24
    MAX_ACCOUNT_TEXT = 64

    def __init__(self) -> None:
        super().__init__()
        self.config_data = load_config()
        self.action_buttons: list[AnimatedButton] = []
        self.send_modal: tk.Toplevel | None = None
        self.transfer_modal: tk.Toplevel | None = None
        self.contacts_modal: tk.Toplevel | None = None
        self.account_suggestions: list[str] = []
        self.contacts: list[Contact] = load_contacts(self.config_data)
        self.contact_choices_var = tk.StringVar()

        self.ws = WalletState(network=self.config_data.get("network", DEFAULT_NETWORK))
        self.ws.refresh_cli(self.config_data)
        self.ws.add_listener(self._on_state_change)

        self.history_store = HistoryStore()
        self.history_panel: HistoryPanel | None = None
        self.tx_panel: TransactionsPanel | None = None

        self.title("Lapis Monetae Wallet")
        self.geometry("1050x780")
        self.minsize(640, 480)
        self.configure(bg=self.BG)
        self._set_window_icon()
        self._build_style()
        self._build_layout()
        self._sync_ui_to_state()
        self.log("Welcome to Lapis Monetae Wallet. Configure CLI and network, then run an action.")
        self.history_store.add("system", "GUI started", "ok")
        if self.history_panel:
            self.history_panel.refresh()
        self.after(2000, self._poll_node_status)

    # ── Window icon ──

    def _set_window_icon(self) -> None:
        ico_path = ASSETS_DIR / "lmt_icon.ico"
        png_path = ASSETS_DIR / "lmt_icon_64.png"
        try:
            self.iconbitmap(str(ico_path))
        except tk.TclError:
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
        style.configure(
            "Light.TCombobox",
            fieldbackground=self.INPUT_BG, background="#ffffff",
            foreground=self.FG, arrowcolor=self.MUTED,
            bordercolor=self.BORDER, lightcolor="#ffffff", darkcolor=self.BORDER,
            selectbackground=self.BLUE, selectforeground="#ffffff",
        )
        style.map(
            "Light.TCombobox",
            fieldbackground=[("readonly", self.INPUT_BG)],
            foreground=[("readonly", self.FG)],
            bordercolor=[("focus", self.BLUE)],
        )

    # ── Layout ──

    def _build_layout(self) -> None:
        outer = tk.Frame(self, bg=self.BG, padx=16, pady=10)
        outer.pack(fill="both", expand=True)

        self._build_header(outer)
        self._build_config_panel(outer)
        self._build_status_row(outer)
        self._build_action_buttons(outer)
        self._build_output_and_history(outer)

    def _build_header(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=self.BG)
        header.pack(fill="x", pady=(0, 2))
        title_row = tk.Frame(header, bg=self.BG)
        title_row.pack(fill="x")

        header_png = ASSETS_DIR / "lmt_header.png"
        try:
            self._header_logo = tk.PhotoImage(file=str(header_png))
            tk.Label(title_row, image=self._header_logo, bg=self.BG).pack(side="left", padx=(0, 10))
        except tk.TclError:
            pass

        tk.Label(title_row, text="Lapis Monetae Wallet", bg=self.BG, fg=self.FG,
                 font=("Segoe UI Semibold", 18)).pack(side="left")
        self.pill_status = tk.Label(title_row, text=" \u25CF  READY ", bg=self.BLUE_LIGHT,
                                    fg=self.BLUE, font=("Segoe UI Semibold", 8), padx=10, pady=3)
        self.pill_status.pack(side="right")

        accent_line = tk.Canvas(parent, bg=self.BG, height=2, highlightthickness=0, bd=0)
        accent_line.pack(fill="x", pady=(2, 6))
        accent_line.bind("<Configure>", lambda e: self._draw_gradient_line(accent_line, e.width))

    def _build_config_panel(self, parent: tk.Frame) -> None:
        top_panel = tk.Frame(parent, bg=self.PANEL, padx=12, pady=8,
                             highlightbackground=self.BORDER, highlightthickness=1)
        top_panel.pack(fill="x")

        # ── Row 1: CLI path ──
        row1 = tk.Frame(top_panel, bg=self.PANEL)
        row1.pack(fill="x", pady=(0, 6))
        tk.Label(row1, text="CLI Path", bg=self.PANEL, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        entry_row = tk.Frame(row1, bg=self.PANEL)
        entry_row.pack(fill="x")
        self.cli_path_var = tk.StringVar(value=self.config_data.get("cli_path", ""))
        tk.Entry(entry_row, textvariable=self.cli_path_var, bg=self.INPUT_BG, fg=self.FG,
                 insertbackground=self.FG, relief="flat", font=("Consolas", 9),
                 highlightthickness=1, highlightcolor=self.BLUE,
                 highlightbackground=self.BORDER).pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
        AnimatedButton(entry_row, text="\u2026 Browse", command=self.on_browse_cli,
                       base_bg="#edf0f7", hover_bg=self.BLUE, border_color=self.BORDER, height=32,
                       ).pack(side="left", padx=(0, 4))
        AnimatedButton(entry_row, text="\u2713 Save", command=self.on_save_cli_path,
                       base_bg="#edf0f7", hover_bg="#16a34a", border_color=self.BORDER, height=32,
                       ).pack(side="left")

        # ── Row 2: Network + Wallet name ──
        row2 = tk.Frame(top_panel, bg=self.PANEL)
        row2.pack(fill="x")

        net_frame = tk.Frame(row2, bg=self.PANEL)
        net_frame.pack(side="left", fill="x", padx=(0, 12))
        tk.Label(net_frame, text="Network", bg=self.PANEL, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.network_var = tk.StringVar(value=self.ws.network)
        network_box = ttk.Combobox(net_frame, values=NETWORK_CHOICES, textvariable=self.network_var,
                                   state="readonly", style="Light.TCombobox", width=12)
        network_box.pack(anchor="w", ipady=2)
        network_box.bind("<<ComboboxSelected>>", lambda _e: self.on_network_change())

        wallet_frame = tk.Frame(row2, bg=self.PANEL)
        wallet_frame.pack(side="left", fill="x", expand=True)
        tk.Label(wallet_frame, text="Wallet Name (optional)", bg=self.PANEL, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.wallet_name_var = tk.StringVar(value=self.config_data.get("last_wallet", ""))
        wallet_name_entry = tk.Entry(
            wallet_frame,
            textvariable=self.wallet_name_var,
            bg=self.INPUT_BG,
            fg=self.FG,
            insertbackground=self.FG,
            relief="flat",
            font=("Segoe UI", 9),
            highlightthickness=1,
            highlightcolor=self.BLUE,
            highlightbackground=self.BORDER,
        )
        self._bind_max_length(wallet_name_entry, self.MAX_WALLET_NAME)
        wallet_name_entry.pack(fill="x", ipady=5)

    def _build_status_row(self, parent: tk.Frame) -> None:
        self.status_var = tk.StringVar()
        self.node_status_var = tk.StringVar(value="Node: unknown")
        row = tk.Frame(parent, bg=self.BG)
        row.pack(fill="x", pady=(4, 4))
        tk.Label(row, textvariable=self.status_var, bg=self.BG, fg=self.MUTED,
                 font=("Consolas", 8)).pack(side="left")
        tk.Label(row, textvariable=self.node_status_var, bg=self.BG, fg=self.MUTED,
                 font=("Consolas", 8)).pack(side="right")

    def _build_action_buttons(self, parent: tk.Frame) -> None:
        actions_panel = tk.Frame(parent, bg=self.PANEL, padx=10, pady=8,
                                 highlightbackground=self.BORDER, highlightthickness=1)
        actions_panel.pack(fill="x", pady=(0, 6))

        self._build_button_row(actions_panel, "\u26BF Wallet", self.BLUE, [
            ("\u2726 Create", self.action_create, self.BLUE),
            ("\u2B07 Import", self.action_import, "#3b82f6"),
            ("\u2750 Open", self.action_open, "#2563eb"),
            ("\u21BA Open Last", self.action_open_last_wallet, "#1d4ed8"),
        ])
        self._build_button_row(actions_panel, "\u2637 Accounts", "#0891b2", [
            ("\u2630 List", lambda: self._guarded_capture(["wallet", "list"], "wallet", "Wallet list"), "#0891b2"),
            ("\u2261 Balances", self.action_list_balances, "#0e7490"),
            ("\u2316 Address", lambda: self._guarded_capture(["address"], "address", "Show address"), "#0d9488"),
            ("\u271A New Addr", lambda: self._guarded_capture(["address", "new"], "address", "Generate new address"), "#059669"),
        ])
        self._build_button_row(actions_panel, "\u26A1 Transactions", self.ORANGE, [
            ("\u27A4 Send", self.open_send_modal, "#d97706"),
            ("\u21C4 Transfer", self.open_transfer_modal, "#ea580c"),
            ("\u2630 Tx History", self.refresh_transactions, "#ca8a04"),
            ("\u260E Contacts", self.open_contacts_modal, "#7c3aed"),
            ("\u2715 Clear", self.clear_output, "#9333ea"),
        ])

    def _build_output_and_history(self, parent: tk.Frame) -> None:
        """Output log and history in a tabbed Notebook — never hidden."""
        style = ttk.Style()
        style.configure("Bottom.TNotebook", background=self.BG, borderwidth=0)
        style.configure("Bottom.TNotebook.Tab", font=("Segoe UI Semibold", 9),
                        padding=[12, 4], background=self.BG, foreground=self.MUTED)
        style.map("Bottom.TNotebook.Tab",
                  background=[("selected", self.PANEL)],
                  foreground=[("selected", self.BLUE)])

        notebook = ttk.Notebook(parent, style="Bottom.TNotebook")
        notebook.pack(fill="both", expand=True)

        # ── Tab 1: Command Output ──
        output_frame = tk.Frame(notebook, bg=self.PANEL, padx=10, pady=8)
        out_header = tk.Frame(output_frame, bg=self.PANEL)
        out_header.pack(fill="x", pady=(0, 4))
        self.line_count_var = tk.StringVar(value="0 lines")
        tk.Label(out_header, textvariable=self.line_count_var, bg=self.PANEL, fg="#a0aab8",
                 font=("Consolas", 8)).pack(side="right")

        text_border = tk.Frame(output_frame, bg=self.BORDER, padx=1, pady=1)
        text_border.pack(fill="both", expand=True)
        y_scroll = tk.Scrollbar(text_border, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        x_scroll = tk.Scrollbar(text_border, orient="horizontal")
        x_scroll.pack(side="bottom", fill="x")
        self.output = tk.Text(text_border, bg=self.TEXT_BG, fg="#334155",
                              insertbackground=self.FG, relief="flat", wrap="none",
                              font=("Consolas", 9), padx=10, pady=8,
                              yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set,
                              borderwidth=0, selectbackground=self.BLUE_LIGHT,
                              selectforeground=self.FG)
        self.output.pack(fill="both", expand=True)
        y_scroll.config(command=self.output.yview)
        x_scroll.config(command=self.output.xview)
        self.output.tag_configure("ts", foreground=self.BLUE)
        self.output.tag_configure("err", foreground=self.ERROR)
        self.output.tag_configure("ok", foreground=self.SUCCESS)
        self.output.config(state="disabled")
        notebook.add(output_frame, text=" \u2630  Output ")

        # ── Tab 2: Operation History ──
        history_frame = tk.Frame(notebook, bg=self.BG)
        self.history_panel = HistoryPanel(history_frame, self.history_store)
        notebook.add(history_frame, text=" \u2637  History ")

        # ── Tab 3: Transactions ──
        tx_frame = tk.Frame(notebook, bg=self.BG)
        self.tx_panel = TransactionsPanel(tx_frame)
        notebook.add(tx_frame, text=" \u27A6  Transactions ")

    # ── Widget helpers ──

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

    def _build_button_row(self, parent: tk.Frame, title: str, accent: str,
                          buttons: list[tuple[str, Any, str]]) -> None:
        row = tk.Frame(parent, bg=self.GROUP_BG, padx=4, pady=3,
                       highlightbackground=self.BORDER, highlightthickness=1)
        row.pack(fill="x", pady=2)

        title_bar = tk.Frame(row, bg=self.GROUP_BG)
        title_bar.pack(fill="x", pady=(0, 3))
        dot = tk.Canvas(title_bar, width=8, height=8, bg=self.GROUP_BG, highlightthickness=0, bd=0)
        dot.pack(side="left", padx=(2, 4))
        dot.create_oval(1, 1, 7, 7, fill=accent, outline=accent)
        tk.Label(title_bar, text=title, bg=self.GROUP_BG, fg=accent,
                 font=("Segoe UI Semibold", 9)).pack(side="left")

        btn_grid = tk.Frame(row, bg=self.GROUP_BG)
        btn_grid.pack(fill="x")
        for i, (label, command, hover) in enumerate(buttons):
            btn_grid.grid_columnconfigure(i, weight=1, uniform="btn")
            btn = AnimatedButton(btn_grid, text=label, command=command, base_bg="#edf0f7",
                                 hover_bg=hover, border_color=self.BORDER, fg="#1e293b",
                                 hover_fg="#ffffff", height=32)
            btn.grid(row=0, column=i, padx=2, pady=1, sticky="ew")
            self.action_buttons.append(btn)

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
        text, bg, fg = self.ws.pill_info()
        self.pill_status.config(text=text, bg=bg, fg=fg)
        btn_state = "disabled" if self.ws.busy else "normal"
        for btn in self.action_buttons:
            btn.config(state=btn_state)

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
        path = filedialog.askopenfilename(
            title="Select CLI executable",
            filetypes=[("Executable files", "*.exe")],
        )
        if path:
            self.cli_path_var.set(path)

    def on_save_cli_path(self) -> None:
        self.config_data["cli_path"] = self.cli_path_var.get().strip()
        save_config(self.config_data)
        self.ws.refresh_cli(self.config_data)
        self.log("CLI path saved.")
        self.toast("CLI path saved", "ok")
        self.history_panel and self.history_panel.add_and_refresh("system", "CLI path saved", "ok")

    def _save_last_wallet(self, wallet_name: str) -> None:
        normalized = wallet_name.strip()
        if not normalized:
            return
        self.config_data["last_wallet"] = normalized
        save_config(self.config_data)

    def _save_contacts(self) -> None:
        save_contacts_to_config(self.config_data, self.contacts)
        save_config(self.config_data)

    def on_network_change(self) -> None:
        net = self.network_var.get().strip() or DEFAULT_NETWORK
        self.config_data["network"] = net
        save_config(self.config_data)
        self.ws.set_network(net)
        self.log(f"Network saved: {net}")
        self.toast(f"Active network: {net}", "info")
        self.history_panel and self.history_panel.add_and_refresh("network", f"Network changed to {net}", "ok")

    # ── Guarded action runners ──

    def _require_cli(self) -> str | None:
        self.ws.refresh_cli(self.config_data)
        if not self.ws.cli_available:
            self.log("ERROR: CLI binary not found. Set a path or define LMT_CLI_BIN.")
            self.toast("CLI was not found", "error")
            return None
        return self.ws.cli_binary

    def _guarded_capture(self, args: list[str], category: str, description: str,
                         ensure_network: bool = False) -> None:
        ok, reason = self.ws.can_run_action()
        if not ok:
            self.toast(reason, "info")
            return
        self.history_panel and self.history_panel.add_and_refresh(category, description, "pending")  # type: ignore[arg-type]
        self.run_capture_action(args, ensure_network=ensure_network)

    def run_capture_action(
        self,
        args: list[str],
        ensure_network: bool = False,
        on_complete: Callable[[int, str], None] | None = None,
    ) -> None:
        binary = self._require_cli()
        if not binary:
            return
        self.ws.set_busy(True)

        def worker() -> None:
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
            friendly = map_cli_error(code, out)
            toast_msg = "Command completed" if code == 0 else friendly
            self.after(0, lambda: self.toast(toast_msg, status))
            if on_complete:
                self.after(0, lambda: on_complete(code, out))
            detail = f"Exit code: {code}" if code == 0 else f"{friendly} (exit code: {code})"
            self.after(0, lambda: self._finish_action(status, detail))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_action(self, status: str, detail: str = "") -> None:
        self.ws.set_busy(False)
        if self.history_panel:
            self.history_panel.update_last_and_refresh(status, detail)  # type: ignore[arg-type]

    def run_interactive_action(self, args: list[str], category: str = "wallet",
                               description: str = "Interactive command") -> None:
        ok, reason = self.ws.can_run_action()
        if not ok:
            self.toast(reason, "info")
            return
        binary = self._require_cli()
        if not binary:
            return

        self.run_capture_action(["network", self.ws.network], ensure_network=False)
        launched, message = launch_interactive(binary, args)
        self.log(message)
        status = "ok" if launched else "error"
        self.toast(
            "Interactive command launched" if launched else "Error opening interactive console",
            "info" if launched else "error",
        )
        self.history_panel and self.history_panel.add_and_refresh(
            category, description, status, message,  # type: ignore[arg-type]
        )
        if launched and len(args) >= 2 and args[0] == "wallet" and args[1] == "open":
            target_name = args[2] if len(args) >= 3 else self._wallet_name()
            self.ws.set_wallet_open_pending(target_name)
            self._verify_wallet_open_async(target_name)

    # ── Wallet actions ──

    def _wallet_name(self) -> str:
        return self.wallet_name_var.get().strip()

    def action_create(self) -> None:
        args = ["wallet", "create"]
        name = self._wallet_name()
        if name:
            args.append(name)
            self._save_last_wallet(name)
        self.run_interactive_action(args, "wallet", f"Create wallet{f' ({name})' if name else ''}")

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
        last_wallet = str(self.config_data.get("last_wallet", "")).strip()
        if not last_wallet:
            self.toast("No last wallet is saved yet", "info")
            return
        self.wallet_name_var.set(last_wallet)
        self.run_interactive_action(["wallet", "open", last_wallet], "wallet",
                                    f"Open last wallet ({last_wallet})")

    def action_list_balances(self) -> None:
        self._guarded_capture(["list"], "wallet", "List account balances", ensure_network=True)

    def _verify_wallet_open_async(self, wallet_name: str) -> None:
        binary = self._require_cli()
        if not binary:
            self.ws.close_wallet()
            return

        def worker() -> None:
            verified = False
            for _ in range(6):
                code, out = run_capture(binary, ["list"])
                if is_wallet_open_from_output(code, out):
                    verified = True
                    break
                # wait in main loop, not busy wait
                event = threading.Event()
                event.wait(2.0)
            if verified:
                self.after(0, lambda: self.ws.open_wallet(wallet_name))
                self.after(0, lambda: self.toast(f"Wallet '{wallet_name or 'default'}' verified open", "ok"))
                self.after(0, lambda: self.history_panel and self.history_panel.add_and_refresh("wallet", "Wallet open verified", "ok"))
            else:
                self.after(0, self.ws.close_wallet)
                self.after(0, lambda: self.toast("Wallet open could not be verified yet", "warn"))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_node_status(self) -> None:
        self.ws.refresh_cli(self.config_data)
        binary = self.ws.cli_binary
        if not binary or self.ws.busy:
            self.after(12000, self._poll_node_status)
            return

        def worker() -> None:
            ping_code, ping_out = run_capture(binary, ["ping"])
            if ping_code != 0:
                self.after(0, lambda: self.ws.set_node_status(False, None))
                self.after(12000, self._poll_node_status)
                return
            list_code, list_out = run_capture(binary, ["list"])
            if list_code == 0:
                connected, synced = parse_node_sync_hint(list_out)
            else:
                connected, synced = True, None
            self.after(0, lambda: self.ws.set_node_status(connected, synced))
            self.after(12000, self._poll_node_status)

        threading.Thread(target=worker, daemon=True).start()

    # ── Send modal ──

    def open_send_modal(self) -> None:
        ok, reason = self.ws.can_send()
        if not ok:
            self.toast(reason, "info")
            return
        if self.send_modal and self.send_modal.winfo_exists():
            self.send_modal.focus_force()
            return
        modal = self._create_modal("\u27A4  Send LMT", accent=self.ORANGE)
        modal.geometry("620x500")
        modal.minsize(560, 420)
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
            contact_combo = self._labeled_combo(content, row, "Saved contact (optional)", contact_choice_var, contact_values)
            row += 1

            def apply_contact(_event: tk.Event[tk.Misc]) -> None:
                selected = contact_choice_var.get().strip()
                if selected:
                    recipient_var.set(self._resolve_contact_address(selected))

            contact_combo.bind("<<ComboboxSelected>>", apply_contact)
        self._labeled_entry(content, row, "Recipient address", recipient_var, self.MAX_ADDRESS_TEXT)
        self._labeled_entry(content, row + 1, "Amount (LMT)", amount_var, self.MAX_NUMERIC_TEXT)
        self._labeled_entry(content, row + 2, "Priority fee (LMT, optional)", fee_var, self.MAX_NUMERIC_TEXT)

        footer = tk.Frame(content, bg=self.PANEL)
        footer.grid(row=row + 3, column=0, sticky="ew", pady=(14, 0))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="\u2715  Cancel", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER
                       ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(footer, text="\u27A4  Confirm & Send",
                       command=lambda: self._submit_send(recipient_var.get(), amount_var.get(), fee_var.get(), modal),
                       base_bg=self.ORANGE_LIGHT, hover_bg=self.ORANGE, border_color="#fbbf24", fg="#92400e",
                       ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

    # ── Transfer modal ──

    def open_transfer_modal(self) -> None:
        ok, reason = self.ws.can_send()
        if not ok:
            self.toast(reason, "info")
            return
        if self.transfer_modal and self.transfer_modal.winfo_exists():
            self.transfer_modal.focus_force()
            return
        modal = self._create_modal("\u21C4  Transfer Between Accounts", accent=self.BLUE)
        modal.geometry("620x500")
        modal.minsize(560, 420)
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
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="\u2715  Cancel", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER
                       ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(footer, text="\u21C4  Confirm & Transfer",
                       command=lambda: self._submit_transfer(account_var.get(), amount_var.get(), fee_var.get(), modal),
                       base_bg=self.BLUE_LIGHT, hover_bg=self.BLUE, border_color="#93c5fd", fg="#1e3a5f",
                       ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        if not self.account_suggestions:
            self.refresh_account_suggestions(silent=True)

    # ── Modal / form helpers ──

    def _create_modal(self, title: str, accent: str = "#2563eb") -> tk.Toplevel:
        modal = tk.Toplevel(self)
        modal.title(title)
        modal.configure(bg=self.BG)
        modal.transient(self)
        modal.grab_set()
        modal.geometry("620x460")
        modal.minsize(520, 360)
        modal.resizable(True, True)
        tk.Frame(modal, bg=accent, height=4).pack(fill="x")
        title_frame = tk.Frame(modal, bg=self.PANEL, padx=20, pady=12)
        title_frame.pack(fill="x")
        tk.Label(title_frame, text=title, bg=self.PANEL, fg=self.FG,
                 font=("Segoe UI Semibold", 14)).pack(side="left")
        close_btn = tk.Label(title_frame, text="\u2715", bg=self.PANEL, fg=self.MUTED,
                             font=("Segoe UI", 12), cursor="hand2")
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _: modal.destroy())
        close_btn.bind("<Enter>", lambda _: close_btn.config(fg=self.ERROR))
        close_btn.bind("<Leave>", lambda _: close_btn.config(fg=self.MUTED))
        tk.Frame(modal, bg=self.BORDER, height=1).pack(fill="x")
        return modal

    def _labeled_entry(
        self,
        parent: tk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        max_length: int | None = None,
    ) -> None:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.grid(row=row, column=0, sticky="ew", pady=5)
        tk.Label(frame, text=label, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 3))
        entry = tk.Entry(
            frame,
            textvariable=variable,
            bg=self.INPUT_BG,
            fg=self.FG,
            insertbackground=self.FG,
            relief="flat",
            font=("Consolas", 11),
            highlightthickness=1,
            highlightcolor=self.BLUE,
            highlightbackground=self.BORDER,
        )
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
        combo = ttk.Combobox(frame, textvariable=variable, values=values,
                             style="Light.TCombobox")
        combo.pack(fill="x", ipady=6)
        parent.grid_columnconfigure(0, weight=1)
        return combo

    # ── Submit handlers ──

    def _submit_send(self, address: str, amount: str, fee: str, modal: tk.Toplevel) -> None:
        result = validate_address(address, self.ws.network)
        if not result:
            self.toast(result.error, "error")
            return
        parsed_amount = parse_positive_amount(amount)
        if parsed_amount is None:
            self.toast("Amount must be a positive number", "error")
            return
        parsed_fee = parse_nonnegative_fee(fee)
        if parsed_fee is None:
            self.toast("Priority fee must be a non-negative number", "error")
            return

        normalized_address = address.strip().lower()
        modal.destroy()
        self._confirm_action(
            "Confirm Send",
            [f"Address: {normalized_address}",
             f"Amount: {parsed_amount:.8f} LMT",
             f"Priority fee: {parsed_fee:.8f} LMT",
             "", "This will open an interactive CLI console for wallet secrets."],
            lambda: self.run_interactive_action(
                ["send", normalized_address, f"{parsed_amount:.8f}", f"{parsed_fee:.8f}"],
                "send", f"Send {parsed_amount:.8f} LMT",
            ),
        )

    def _submit_transfer(self, target_account: str, amount: str, fee: str, modal: tk.Toplevel) -> None:
        account = target_account.strip()
        if not account:
            self.toast("Target account is required", "error")
            return
        if len(account) > self.MAX_ACCOUNT_TEXT:
            self.toast(f"Target account is too long (max {self.MAX_ACCOUNT_TEXT} chars)", "error")
            return
        parsed_amount = parse_positive_amount(amount)
        if parsed_amount is None:
            self.toast("Amount must be a positive number", "error")
            return
        parsed_fee = parse_nonnegative_fee(fee)
        if parsed_fee is None:
            self.toast("Priority fee must be a non-negative number", "error")
            return

        modal.destroy()
        self._confirm_action(
            "Confirm Transfer",
            [f"Target account: {account}",
             f"Amount: {parsed_amount:.8f} LMT",
             f"Priority fee: {parsed_fee:.8f} LMT",
             "", "This will open an interactive CLI console for wallet secrets."],
            lambda: self.run_interactive_action(
                ["transfer", account, f"{parsed_amount:.8f}", f"{parsed_fee:.8f}"],
                "transfer", f"Transfer {parsed_amount:.8f} LMT to {account}",
            ),
        )

    def _confirm_action(self, title: str, lines: list[str], on_confirm: Callable[[], None]) -> None:
        modal = self._create_modal(title, accent=self.ORANGE)
        modal.geometry("620x380")
        modal.minsize(560, 320)
        container = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        container.pack(fill="both", expand=True)
        for line in lines:
            fg = self.FG if line and not line.startswith(" ") else self.MUTED
            tk.Label(container, text=line, bg=self.PANEL, fg=fg,
                     font=("Segoe UI", 10), justify="left").pack(anchor="w", pady=1)
        footer = tk.Frame(container, bg=self.PANEL)
        footer.pack(fill="x", pady=(18, 0))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="\u2715  Cancel", command=modal.destroy,
                       base_bg="#f1f5f9", hover_bg="#94a3b8", border_color=self.BORDER
                       ).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(footer, text="\u2713  Proceed",
                       command=lambda: (modal.destroy(), on_confirm()),
                       base_bg="#dcfce7", hover_bg=self.SUCCESS, border_color="#86efac", fg="#166534",
                       ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

    # ── Account suggestions ──

    def _extract_account_suggestions(self, output: str) -> list[str]:
        suggestions: list[str] = []
        seen: set[str] = set()
        for raw_line in output.splitlines():
            line = ANSI_ESCAPE_RE.sub("", raw_line)
            match = re.match(r"^\s{2,}•\s+(.+)$", line)
            if not match:
                continue
            candidate = match.group(1).strip()
            if ":" in candidate and candidate.split(":", 1)[0] in {"lmt", "lmttest", "lmtsim", "lmtdev"}:
                continue
            if candidate.startswith("• "):
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
            self.toast(reason, "info")
            return
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

        self.run_capture_action(["history", "list", "30"], ensure_network=True, on_complete=on_history_complete)

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
            self.contacts_modal.focus_force()
            return
        modal = self._create_modal("\u260E  Manage Contacts", accent="#7c3aed")
        modal.geometry("760x620")
        modal.minsize(640, 500)
        self.contacts_modal = modal

        container = tk.Frame(modal, bg=self.PANEL, padx=20, pady=14)
        container.pack(fill="both", expand=True)

        listbox = tk.Listbox(container, bg=self.TEXT_BG, fg=self.FG, relief="flat", font=("Segoe UI", 9))
        listbox.pack(fill="both", expand=True, pady=(0, 10))

        form = tk.Frame(container, bg=self.PANEL)
        form.pack(fill="x")

        def refresh_listbox() -> None:
            listbox.delete(0, "end")
            for c in self.contacts:
                text = f"{c.name}  |  {c.address}"
                if c.note:
                    text += f"  |  {c.note}"
                listbox.insert("end", text)

        name_var = tk.StringVar()
        addr_var = tk.StringVar()
        note_var = tk.StringVar()
        self._labeled_entry(form, 0, "Name", name_var, self.MAX_CONTACT_NAME)
        self._labeled_entry(form, 1, "Address", addr_var, self.MAX_ADDRESS_TEXT)
        self._labeled_entry(form, 2, "Note (optional)", note_var, self.MAX_NOTE_TEXT)

        actions = tk.Frame(form, bg=self.PANEL)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        def add_contact() -> None:
            result = validate_address(addr_var.get(), self.ws.network)
            if not result:
                self.toast(result.error, "error")
                return
            name = name_var.get().strip()
            if not name:
                self.toast("Contact name is required", "error")
                return
            if len(name) > self.MAX_CONTACT_NAME:
                self.toast(f"Contact name too long (max {self.MAX_CONTACT_NAME})", "error")
                return
            self.contacts.append(Contact(name=name, address=addr_var.get().strip(), note=note_var.get().strip()))
            self._save_contacts()
            refresh_listbox()
            self.toast("Contact saved", "ok")

        def remove_selected() -> None:
            selected = listbox.curselection()
            if not selected:
                return
            idx = selected[0]
            if 0 <= idx < len(self.contacts):
                self.contacts.pop(idx)
                self._save_contacts()
                refresh_listbox()
                self.toast("Contact removed", "ok")

        AnimatedButton(actions, text="+ Add Contact", command=add_contact, base_bg="#ede9fe", hover_bg="#7c3aed", border_color="#ddd6fe").grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(actions, text="- Remove Selected", command=remove_selected, base_bg="#fee2e2", hover_bg="#dc2626", border_color="#fecaca").grid(row=0, column=1, padx=(6, 0), sticky="ew")

        refresh_listbox()

    # ── Misc ──

    def clear_output(self) -> None:
        self.output.config(state="normal")
        self.output.delete("1.0", "end")
        self.output.config(state="disabled")
        self.line_count_var.set("0 lines")
        self.toast("Output cleared", "ok")

    def toast(self, message: str, kind: str = "info") -> None:
        icons = {"ok": "\u2713", "error": "\u2717", "info": "\u25CF", "warn": "\u26A0"}
        colors = {
            "ok": ("#f0fdf4", "#166534", "#16a34a"),
            "error": ("#fef2f2", "#991b1b", "#dc2626"),
            "info": ("#eff6ff", "#1e3a5f", "#2563eb"),
            "warn": ("#fffbeb", "#92400e", "#d97706"),
        }
        bg, fg, accent = colors.get(kind, colors["info"])
        icon = icons.get(kind, "\u25CF")

        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.attributes("-alpha", 0.0)
        width, height = 360, 44
        x = self.winfo_rootx() + self.winfo_width() - width - 20
        y = self.winfo_rooty() + 20
        toast.geometry(f"{width}x{height}+{x}+{y}")

        border = tk.Frame(toast, bg=self.BORDER, padx=1, pady=1)
        border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg=bg)
        inner.pack(fill="both", expand=True)
        tk.Frame(inner, bg=accent, width=4).pack(side="left", fill="y")
        tk.Label(inner, text=f"  {icon}  {message}", bg=bg, fg=fg,
                 font=("Segoe UI Semibold", 10), anchor="w").pack(fill="both", expand=True, padx=(4, 14))

        def fade_in(alpha: float = 0.0) -> None:
            if alpha >= 0.97:
                toast.attributes("-alpha", 0.97)
                toast.after(2200, fade_out, 0.97)
                return
            toast.attributes("-alpha", alpha)
            toast.after(16, fade_in, alpha + 0.10)

        def fade_out(alpha: float) -> None:
            if alpha <= 0.0:
                toast.destroy()
                return
            toast.attributes("-alpha", alpha)
            toast.after(16, fade_out, alpha - 0.12)

        fade_in()
