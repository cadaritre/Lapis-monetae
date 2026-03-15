from __future__ import annotations

import csv
import json
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import filedialog, ttk

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
TXID_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
AMOUNT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s+(?:LMT|KAS)\b")


@dataclass
class TxRow:
    when: str
    txid: str  # display (truncated)
    full_txid: str  # full 64-char for copy/export
    direction: str
    amount: str
    status: str
    raw: str


def parse_history_output(output: str) -> list[TxRow]:
    rows: list[TxRow] = []
    now = datetime.now().strftime("%H:%M:%S")
    for raw_line in output.splitlines():
        line = ANSI_ESCAPE_RE.sub("", raw_line).strip()
        if not line or line.startswith(">") or line.lower().startswith("exit code"):
            continue
        match_txid = TXID_RE.search(line)
        if not match_txid:
            continue
        full_txid = match_txid.group(0)
        txid_display = full_txid[:12] + "..." if len(full_txid) >= 16 else full_txid
        amount_match = AMOUNT_RE.search(line)
        amount = amount_match.group(1) if amount_match else "-"
        lower = line.lower()
        if "received" in lower or "inbound" in lower:
            direction = "in"
        elif "sent" in lower or "outbound" in lower:
            direction = "out"
        else:
            direction = "-"
        if "pending" in lower:
            status = "pending"
        elif "confirm" in lower:
            status = "confirmed"
        else:
            status = "-"
        rows.append(TxRow(when=now, txid=txid_display, full_txid=full_txid, direction=direction, amount=amount, status=status, raw=line))
    return rows


class TransactionsPanel:
    def __init__(self, parent: tk.Frame) -> None:
        self.rows: list[TxRow] = []
        self._filtered: list[TxRow] = []
        self.detail_var = tk.StringVar(value="")
        self._build(parent)

    def _build(self, parent: tk.Frame) -> None:
        wrapper = tk.Frame(parent, bg="#ffffff", padx=10, pady=6, highlightbackground="#dce1ea", highlightthickness=1)
        wrapper.pack(fill="both", expand=True, pady=(4, 0))

        header = tk.Frame(wrapper, bg="#ffffff")
        header.pack(fill="x", pady=(0, 4))
        tk.Label(header, text="Transactions (CLI History)", bg="#ffffff", fg="#6b7a94", font=("Segoe UI Semibold", 9)).pack(side="left")

        filter_row = tk.Frame(wrapper, bg="#ffffff")
        filter_row.pack(fill="x", pady=(0, 4))
        tk.Label(filter_row, text="Status:", bg="#ffffff", fg="#6b7a94", font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        self.filter_status_var = tk.StringVar(value="all")
        status_combo = ttk.Combobox(filter_row, textvariable=self.filter_status_var, values=("all", "pending", "confirmed", "-"), state="readonly", width=10)
        status_combo.pack(side="left", padx=(0, 12))
        tk.Label(filter_row, text="Address/TxID:", bg="#ffffff", fg="#6b7a94", font=("Segoe UI", 8)).pack(side="left", padx=(12, 4))
        self.filter_text_var = tk.StringVar()
        filter_entry = tk.Entry(filter_row, textvariable=self.filter_text_var, bg="#eaecf2", font=("Consolas", 9), width=24)
        filter_entry.pack(side="left", padx=(0, 8))
        filter_entry.bind("<KeyRelease>", lambda _: self._apply_filter())
        status_combo.bind("<<ComboboxSelected>>", lambda _: self._apply_filter())
        tk.Button(filter_row, text="Copy TxID", command=self._copy_selected_txid, bg="#edf0f7", fg="#1e293b", font=("Segoe UI", 8), relief="flat", cursor="hand2").pack(side="left", padx=(8, 4))
        tk.Button(filter_row, text="Export CSV", command=self._export_csv, bg="#edf0f7", fg="#1e293b", font=("Segoe UI", 8), relief="flat", cursor="hand2").pack(side="left", padx=(0, 4))
        tk.Button(filter_row, text="Export JSON", command=self._export_json, bg="#edf0f7", fg="#1e293b", font=("Segoe UI", 8), relief="flat", cursor="hand2").pack(side="left", padx=(0, 4))

        tree_frame = tk.Frame(wrapper, bg="#dce1ea", padx=1, pady=1)
        tree_frame.pack(fill="both", expand=True)

        cols = ("time", "txid", "direction", "amount", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("time", text="Time")
        self.tree.heading("txid", text="TxID")
        self.tree.heading("direction", text="Dir")
        self.tree.heading("amount", text="Amount")
        self.tree.heading("status", text="Status")
        self.tree.column("time", width=70, stretch=False)
        self.tree.column("txid", width=170, stretch=False)
        self.tree.column("direction", width=60, stretch=False, anchor="center")
        self.tree.column("amount", width=110, stretch=False)
        self.tree.column("status", width=100, stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        tk.Label(wrapper, textvariable=self.detail_var, bg="#ffffff", fg="#6b7a94", font=("Consolas", 8), anchor="w").pack(fill="x", pady=(2, 0))

    def _apply_filter(self) -> None:
        status = (self.filter_status_var.get() or "all").strip().lower()
        text = (self.filter_text_var.get() or "").strip().lower()
        self._filtered = []
        for row in self.rows:
            if status != "all" and status != row.status:
                continue
            if text and text not in row.raw.lower() and text not in row.full_txid.lower():
                continue
            self._filtered.append(row)
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(self._filtered):
            self.tree.insert("", "end", iid=str(idx), values=(row.when, row.txid, row.direction, row.amount, row.status))
        if not self._filtered:
            self.detail_var.set("No transactions (or none match the filter).")

    def set_rows(self, rows: list[TxRow]) -> None:
        self.rows = rows
        self._filtered = list(rows)
        self._apply_filter()
        if not rows:
            self.detail_var.set("No transactions parsed from history output yet.")

    def _copy_selected_txid(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if 0 <= idx < len(self._filtered):
            root = self.tree.winfo_toplevel()
            root.clipboard_clear()
            root.clipboard_append(self._filtered[idx].full_txid)
            if hasattr(root, "toast"):
                root.toast("TxID copied", "ok")

    def _export_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Time", "TxID", "Direction", "Amount", "Status", "Raw"])
                for row in self._filtered:
                    w.writerow([row.when, row.full_txid, row.direction, row.amount, row.status, row.raw])
        except OSError:
            pass

    def _export_json(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = [
                {"time": r.when, "txid": r.full_txid, "direction": r.direction,
                 "amount": r.amount, "status": r.status, "raw": r.raw}
                for r in self._filtered
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            root = self.tree.winfo_toplevel()
            if hasattr(root, "toast"):
                root.toast(f"Exported {len(data)} transactions as JSON", "ok")
        except OSError:
            pass

    def _on_select(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.tree.selection()
        if not selection:
            self.detail_var.set("")
            return
        try:
            idx = int(selection[0])
        except ValueError:
            self.detail_var.set("")
            return
        if 0 <= idx < len(self._filtered):
            self.detail_var.set(self._filtered[idx].raw)
