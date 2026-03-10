from __future__ import annotations

import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import ttk

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
TXID_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
AMOUNT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s+(?:LMT|KAS)\b")


@dataclass
class TxRow:
    when: str
    txid: str
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
        txid = match_txid.group(0)
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
        rows.append(TxRow(when=now, txid=txid[:12] + "...", direction=direction, amount=amount, status=status, raw=line))
    return rows


class TransactionsPanel:
    def __init__(self, parent: tk.Frame) -> None:
        self.rows: list[TxRow] = []
        self.detail_var = tk.StringVar(value="")
        self._build(parent)

    def _build(self, parent: tk.Frame) -> None:
        wrapper = tk.Frame(parent, bg="#ffffff", padx=10, pady=6, highlightbackground="#dce1ea", highlightthickness=1)
        wrapper.pack(fill="both", expand=True, pady=(4, 0))

        header = tk.Frame(wrapper, bg="#ffffff")
        header.pack(fill="x", pady=(0, 4))
        tk.Label(header, text="Transactions (CLI History)", bg="#ffffff", fg="#6b7a94", font=("Segoe UI Semibold", 9)).pack(side="left")

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

    def set_rows(self, rows: list[TxRow]) -> None:
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(idx), values=(row.when, row.txid, row.direction, row.amount, row.status))
        if not rows:
            self.detail_var.set("No transactions parsed from history output yet.")

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
        if 0 <= idx < len(self.rows):
            self.detail_var.set(self.rows[idx].raw)
