from __future__ import annotations

import re
import threading
import tkinter as tk
from datetime import datetime
from typing import Any, Callable
from tkinter import filedialog, ttk

from .cli_bridge import launch_interactive, run_capture
from .config import DEFAULT_NETWORK, NETWORK_CHOICES, load_config, resolve_cli_binary, save_config
from .ui_components import AnimatedButton

MIN_ADDRESS_LEN = 24
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
BECH32_CHARS = set("023456789acdefghjklmnpqrstuvwxyz")
NETWORK_PREFIX = {
    "mainnet": "lmt",
    "testnet-10": "lmttest",
    "testnet-11": "lmttest",
}


class WalletGui(tk.Tk):
    BG = "#0f111a"
    PANEL = "#171b2b"
    INPUT_BG = "#22283d"
    TEXT_BG = "#121829"
    FG = "#ecf1ff"
    MUTED = "#9aa8ca"
    SUCCESS = "#2ac98c"
    ERROR = "#ff5f7a"

    def __init__(self) -> None:
        super().__init__()
        self.config_data = load_config()
        self.action_buttons: list[AnimatedButton] = []
        self._busy = False
        self.send_modal: tk.Toplevel | None = None
        self.transfer_modal: tk.Toplevel | None = None
        self.account_suggestions: list[str] = []
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
            text="Phase 2 - Structured dark mode GUI",
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
        tk.Entry(
            top_panel,
            textvariable=self.cli_path_var,
            bg=self.INPUT_BG,
            fg=self.FG,
            insertbackground=self.FG,
            relief="flat",
            font=("Consolas", 10),
        ).grid(row=1, column=0, sticky="ew", padx=(0, 8), ipady=8)

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
        self.wallet_name_var = tk.StringVar(value=self.config_data.get("last_wallet", ""))
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
        tk.Label(outer, textvariable=self.status_var, bg=self.BG, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 8))

        actions_shell = tk.Frame(outer, bg="#0c0f18", padx=1, pady=1)
        actions_shell.pack(fill="x", pady=(0, 12))
        actions = tk.Frame(actions_shell, bg=self.PANEL, padx=10, pady=10)
        actions.pack(fill="x")

        row1 = tk.Frame(actions, bg=self.PANEL)
        row1.pack(fill="x", pady=(0, 8))
        row2 = tk.Frame(actions, bg=self.PANEL)
        row2.pack(fill="x")
        row3 = tk.Frame(actions, bg=self.PANEL)
        row3.pack(fill="x")

        self._add_action_button(row1, 0, "Create Wallet", self.action_create, "#465bff")
        self._add_action_button(row1, 1, "Import Wallet", self.action_import, "#4f67ff")
        self._add_action_button(row1, 2, "Open Wallet", self.action_open, "#5a72ff")
        self._add_action_button(row1, 3, "Open Last Wallet", self.action_open_last_wallet, "#3f7bff")
        self._add_action_button(row2, 0, "Wallet List", lambda: self.run_capture_action(["wallet", "list"]), "#2f9df0")
        self._add_action_button(row2, 1, "Show Address", lambda: self.run_capture_action(["address"]), "#27bb9c")
        self._add_action_button(row2, 2, "New Address", lambda: self.run_capture_action(["address", "new"]), "#31c27b")
        self._add_action_button(row2, 3, "Accounts/Balances", self.action_list_balances, "#1fa9cc")
        self._add_action_button(row3, 0, "Send LMT", self.open_send_modal, "#c056ff")
        self._add_action_button(row3, 1, "Transfer Between Accounts", self.open_transfer_modal, "#f27767")
        self._add_action_button(row3, 2, "Refresh Account Suggestions", self.refresh_account_suggestions, "#f0a340")
        self._add_action_button(row3, 3, "Clear Output", self.clear_output, "#7d4df2")
        for col in range(4):
            row1.grid_columnconfigure(col, weight=1)
            row2.grid_columnconfigure(col, weight=1)
            row3.grid_columnconfigure(col, weight=1)

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

    def _save_last_wallet(self, wallet_name: str) -> None:
        normalized = wallet_name.strip()
        if not normalized:
            return
        self.config_data["last_wallet"] = normalized
        save_config(self.config_data)

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
                net_code, net_out = run_capture(binary, ["network", self.config_data.get("network", DEFAULT_NETWORK)])
                self.after(0, lambda: self.log(net_out))
                if net_code != 0:
                    self.after(0, lambda: self.toast("Failed to select network", "error"))
                    self.after(0, lambda: self._set_busy(False))
                    return
            code, out = run_capture(binary, args)
            self.after(0, lambda: self.log(out))
            self.after(0, lambda: self.log(f"Exit code: {code}\n"))
            self.after(0, lambda: self.toast("Command completed", "ok" if code == 0 else "error"))
            self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def run_interactive_action(self, args: list[str]) -> None:
        if self._busy:
            self.toast("Please wait for the current command to finish", "info")
            return
        binary = self.require_cli()
        if not binary:
            return

        self.run_capture_action(["network", self.config_data.get("network", DEFAULT_NETWORK)], ensure_network=False)
        ok, message = launch_interactive(binary, args)
        self.log(message)
        self.toast(
            "Interactive command launched" if ok else "Error opening interactive console",
            "info" if ok else "error",
        )

    def _wallet_name(self) -> str:
        return self.wallet_name_var.get().strip()

    def action_create(self) -> None:
        args = ["wallet", "create"]
        name = self._wallet_name()
        if name:
            args.append(name)
            self._save_last_wallet(name)
        self.run_interactive_action(args)

    def action_import(self) -> None:
        args = ["wallet", "import"]
        name = self._wallet_name()
        if name:
            args.append(name)
            self._save_last_wallet(name)
        self.run_interactive_action(args)

    def action_open(self) -> None:
        args = ["wallet", "open"]
        name = self._wallet_name()
        if name:
            args.append(name)
            self._save_last_wallet(name)
        self.run_interactive_action(args)

    def action_open_last_wallet(self) -> None:
        last_wallet = str(self.config_data.get("last_wallet", "")).strip()
        if not last_wallet:
            self.toast("No last wallet is saved yet", "info")
            return
        self.wallet_name_var.set(last_wallet)
        self.run_interactive_action(["wallet", "open", last_wallet])

    def action_list_balances(self) -> None:
        self.run_capture_action(["list"], ensure_network=True)

    def open_send_modal(self) -> None:
        if self.send_modal and self.send_modal.winfo_exists():
            self.send_modal.focus_force()
            return
        modal = self._create_modal("Send LMT")
        self.send_modal = modal

        content = tk.Frame(modal, bg=self.PANEL, padx=14, pady=12)
        content.pack(fill="both", expand=True)

        recipient_var = tk.StringVar()
        amount_var = tk.StringVar()
        fee_var = tk.StringVar(value="0")

        self._labeled_entry(content, 0, "Recipient address", recipient_var)
        self._labeled_entry(content, 1, "Amount (LMT)", amount_var)
        self._labeled_entry(content, 2, "Priority fee (LMT, optional)", fee_var)

        footer = tk.Frame(content, bg=self.PANEL)
        footer.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="Cancel", command=modal.destroy, base_bg="#334", hover_bg="#445").grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(
            footer,
            text="Confirm and Send",
            command=lambda: self._submit_send(recipient_var.get(), amount_var.get(), fee_var.get(), modal),
            base_bg="#6c2cff",
            hover_bg="#8749ff",
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

    def open_transfer_modal(self) -> None:
        if self.transfer_modal and self.transfer_modal.winfo_exists():
            self.transfer_modal.focus_force()
            return
        modal = self._create_modal("Transfer Between Accounts")
        self.transfer_modal = modal

        content = tk.Frame(modal, bg=self.PANEL, padx=14, pady=12)
        content.pack(fill="both", expand=True)

        account_var = tk.StringVar()
        amount_var = tk.StringVar()
        fee_var = tk.StringVar(value="0")

        self._labeled_combo(content, 0, "Target account (name or id)", account_var, self.account_suggestions)
        self._labeled_entry(content, 1, "Amount (LMT)", amount_var)
        self._labeled_entry(content, 2, "Priority fee (LMT, optional)", fee_var)

        footer = tk.Frame(content, bg=self.PANEL)
        footer.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="Cancel", command=modal.destroy, base_bg="#334", hover_bg="#445").grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(
            footer,
            text="Confirm and Transfer",
            command=lambda: self._submit_transfer(account_var.get(), amount_var.get(), fee_var.get(), modal),
            base_bg="#df5a45",
            hover_bg="#f27767",
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

        if not self.account_suggestions:
            self.refresh_account_suggestions(silent=True)

    def _create_modal(self, title: str) -> tk.Toplevel:
        modal = tk.Toplevel(self)
        modal.title(title)
        modal.configure(bg="#0c0f18")
        modal.transient(self)
        modal.grab_set()
        modal.geometry("520x300")
        modal.resizable(False, False)
        return modal

    def _labeled_entry(self, parent: tk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.grid(row=row, column=0, sticky="ew", pady=6)
        tk.Label(frame, text=label, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 4))
        tk.Entry(
            frame,
            textvariable=variable,
            bg=self.INPUT_BG,
            fg=self.FG,
            insertbackground=self.FG,
            relief="flat",
            font=("Consolas", 11),
        ).pack(fill="x", ipady=8)
        parent.grid_columnconfigure(0, weight=1)

    def _labeled_combo(self, parent: tk.Frame, row: int, label: str, variable: tk.StringVar, values: list[str]) -> None:
        frame = tk.Frame(parent, bg=self.PANEL)
        frame.grid(row=row, column=0, sticky="ew", pady=6)
        tk.Label(frame, text=label, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 4))
        combo = ttk.Combobox(frame, textvariable=variable, values=values, style="Dark.TCombobox")
        combo.pack(fill="x", ipady=6)
        parent.grid_columnconfigure(0, weight=1)

    def _parse_positive_amount(self, value: str) -> float | None:
        try:
            amount = float(value.strip())
        except ValueError:
            return None
        return amount if amount > 0 else None

    def _parse_nonnegative_fee(self, value: str) -> float | None:
        raw = value.strip()
        if raw == "":
            return 0.0
        try:
            fee = float(raw)
        except ValueError:
            return None
        return fee if fee >= 0 else None

    def _valid_lmt_address(self, address: str) -> bool:
        normalized = address.strip().lower()
        if len(normalized) < MIN_ADDRESS_LEN or ":" not in normalized:
            return False
        expected_prefix = NETWORK_PREFIX.get(str(self.config_data.get("network", DEFAULT_NETWORK)), "lmt")
        prefix, payload = normalized.split(":", 1)
        if prefix != expected_prefix or not payload:
            return False
        return all(ch in BECH32_CHARS for ch in payload)

    def _extract_account_suggestions(self, output: str) -> list[str]:
        suggestions: list[str] = []
        seen: set[str] = set()
        for raw_line in output.splitlines():
            line = ANSI_ESCAPE_RE.sub("", raw_line)
            match = re.match(r"^\s{2,}•\s+(.+)$", line)
            if not match:
                continue
            candidate = match.group(1).strip()
            # Exclude address lines and feature descriptors.
            if ":" in candidate and candidate.split(":", 1)[0] in {"lmt", "lmttest", "lmtsim", "lmtdev"}:
                continue
            if candidate.startswith("• "):
                continue
            if candidate and candidate not in seen:
                seen.add(candidate)
                suggestions.append(candidate)
        return suggestions

    def refresh_account_suggestions(self, silent: bool = False) -> None:
        if self._busy:
            if not silent:
                self.toast("Please wait for the current command to finish", "info")
            return
        binary = self.require_cli()
        if not binary:
            return

        def worker() -> None:
            net_code, net_out = run_capture(binary, ["network", self.config_data.get("network", DEFAULT_NETWORK)])
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

    def _confirm_action(self, title: str, lines: list[str], on_confirm: Callable[[], None]) -> None:
        modal = self._create_modal(title)
        modal.geometry("520x260")
        container = tk.Frame(modal, bg=self.PANEL, padx=14, pady=12)
        container.pack(fill="both", expand=True)
        tk.Label(container, text=title, bg=self.PANEL, fg=self.FG, font=("Segoe UI Semibold", 14)).pack(anchor="w", pady=(0, 8))
        for line in lines:
            tk.Label(container, text=line, bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 10), justify="left").pack(anchor="w")

        footer = tk.Frame(container, bg=self.PANEL)
        footer.pack(fill="x", pady=(18, 0))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=1)
        AnimatedButton(footer, text="Cancel", command=modal.destroy, base_bg="#334", hover_bg="#445").grid(row=0, column=0, padx=(0, 6), sticky="ew")
        AnimatedButton(
            footer,
            text="Proceed",
            command=lambda: (modal.destroy(), on_confirm()),
            base_bg="#3d5aff",
            hover_bg="#5a72ff",
        ).grid(row=0, column=1, padx=(6, 0), sticky="ew")

    def _submit_send(self, address: str, amount: str, fee: str, modal: tk.Toplevel) -> None:
        normalized_address = address.strip()
        parsed_amount = self._parse_positive_amount(amount)
        parsed_fee = self._parse_nonnegative_fee(fee)

        if not self._valid_lmt_address(normalized_address):
            self.toast("Invalid destination address", "error")
            return
        if parsed_amount is None:
            self.toast("Amount must be a positive number", "error")
            return
        if parsed_fee is None:
            self.toast("Priority fee must be a non-negative number", "error")
            return

        modal.destroy()
        self._confirm_action(
            "Confirm Send",
            [
                f"Address: {normalized_address}",
                f"Amount: {parsed_amount:.8f} LMT",
                f"Priority fee: {parsed_fee:.8f} LMT",
                "",
                "This will open an interactive CLI console for wallet secrets.",
            ],
            lambda: self.run_interactive_action(["send", normalized_address, f"{parsed_amount:.8f}", f"{parsed_fee:.8f}"]),
        )

    def _submit_transfer(self, target_account: str, amount: str, fee: str, modal: tk.Toplevel) -> None:
        account = target_account.strip()
        parsed_amount = self._parse_positive_amount(amount)
        parsed_fee = self._parse_nonnegative_fee(fee)

        if not account:
            self.toast("Target account is required", "error")
            return
        if parsed_amount is None:
            self.toast("Amount must be a positive number", "error")
            return
        if parsed_fee is None:
            self.toast("Priority fee must be a non-negative number", "error")
            return

        modal.destroy()
        self._confirm_action(
            "Confirm Transfer",
            [
                f"Target account: {account}",
                f"Amount: {parsed_amount:.8f} LMT",
                f"Priority fee: {parsed_fee:.8f} LMT",
                "",
                "This will open an interactive CLI console for wallet secrets.",
            ],
            lambda: self.run_interactive_action(["transfer", account, f"{parsed_amount:.8f}", f"{parsed_fee:.8f}"]),
        )

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
