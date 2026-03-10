"""Operation history model and Tkinter widget.

Stores a list of HistoryEntry records and renders them in a filterable
ttk.Treeview table inside the main GUI.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from tkinter import ttk
from typing import Literal

StatusType = Literal["ok", "error", "pending", "info"]
ActionCategory = Literal["wallet", "address", "send", "transfer", "network", "system"]

CATEGORY_LABELS: dict[ActionCategory, str] = {
    "wallet": "\u26BF Wallet",
    "address": "\u2316 Address",
    "send": "\u27A4 Send",
    "transfer": "\u21C4 Transfer",
    "network": "\u25CF Network",
    "system": "\u2630 System",
}

STATUS_SYMBOL: dict[StatusType, str] = {
    "ok": "\u2713",
    "error": "\u2717",
    "pending": "\u2026",
    "info": "\u25CF",
}

MAX_HISTORY = 200


@dataclass
class HistoryEntry:
    timestamp: str
    category: ActionCategory
    description: str
    status: StatusType
    detail: str = ""
    id: int = 0


class HistoryStore:
    """In-memory list of operation records with auto-incrementing ID."""

    def __init__(self) -> None:
        self._entries: list[HistoryEntry] = []
        self._next_id = 1

    def add(
        self,
        category: ActionCategory,
        description: str,
        status: StatusType = "info",
        detail: str = "",
    ) -> HistoryEntry:
        entry = HistoryEntry(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            category=category,
            description=description,
            status=status,
            detail=detail,
            id=self._next_id,
        )
        self._next_id += 1
        self._entries.append(entry)
        if len(self._entries) > MAX_HISTORY:
            self._entries = self._entries[-MAX_HISTORY:]
        return entry

    def update_last_status(self, status: StatusType, detail: str = "") -> None:
        if self._entries:
            self._entries[-1].status = status
            if detail:
                self._entries[-1].detail = detail

    @property
    def entries(self) -> list[HistoryEntry]:
        return list(self._entries)

    def filtered(self, category: str | None = None, status: str | None = None) -> list[HistoryEntry]:
        out = self._entries
        if category and category != "all":
            out = [e for e in out if e.category == category]
        if status and status != "all":
            out = [e for e in out if e.status == status]
        return out

    def clear(self) -> None:
        self._entries.clear()


# ── Colors (light theme) ──

_STATUS_COLORS: dict[StatusType, tuple[str, str]] = {
    "ok": ("#16a34a", "#f0fdf4"),
    "error": ("#dc2626", "#fef2f2"),
    "pending": ("#d97706", "#fffbeb"),
    "info": ("#2563eb", "#eff6ff"),
}

_PANEL_BG = "#ffffff"
_BG = "#f2f4f8"
_FG = "#1a2138"
_MUTED = "#6b7a94"
_BORDER = "#dce1ea"
_BLUE = "#2563eb"


@dataclass
class _WidgetRefs:
    """Holds widget references so the panel methods can reach them."""
    tree: ttk.Treeview | None = None
    filter_cat_var: tk.StringVar = field(default_factory=tk.StringVar)
    filter_status_var: tk.StringVar = field(default_factory=tk.StringVar)
    detail_var: tk.StringVar = field(default_factory=tk.StringVar)


class HistoryPanel:
    """Builds and manages a history panel inside a given parent frame."""

    def __init__(self, parent: tk.Frame, store: HistoryStore) -> None:
        self.store = store
        self._refs = _WidgetRefs()
        self._build(parent)

    def _build(self, parent: tk.Frame) -> None:
        wrapper = tk.Frame(parent, bg=_PANEL_BG, padx=10, pady=6,
                           highlightbackground=_BORDER, highlightthickness=1)
        wrapper.pack(fill="both", expand=True, pady=(4, 0))

        # ── Header with filters ──
        header = tk.Frame(wrapper, bg=_PANEL_BG)
        header.pack(fill="x", pady=(0, 4))
        tk.Label(header, text="\u2630  Operation History", bg=_PANEL_BG, fg=_MUTED,
                 font=("Segoe UI Semibold", 9)).pack(side="left")

        filter_frame = tk.Frame(header, bg=_PANEL_BG)
        filter_frame.pack(side="right")

        self._refs.filter_cat_var.set("all")
        tk.Label(filter_frame, text="Category:", bg=_PANEL_BG, fg=_MUTED,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        cat_vals = ["all"] + list(CATEGORY_LABELS.keys())
        cat_box = ttk.Combobox(filter_frame, values=cat_vals,
                               textvariable=self._refs.filter_cat_var,
                               state="readonly", width=10, font=("Segoe UI", 8))
        cat_box.pack(side="left", padx=(0, 10))
        cat_box.bind("<<ComboboxSelected>>", lambda _: self.refresh())

        self._refs.filter_status_var.set("all")
        tk.Label(filter_frame, text="Status:", bg=_PANEL_BG, fg=_MUTED,
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        st_vals = ["all", "ok", "error", "pending", "info"]
        st_box = ttk.Combobox(filter_frame, values=st_vals,
                              textvariable=self._refs.filter_status_var,
                              state="readonly", width=8, font=("Segoe UI", 8))
        st_box.pack(side="left")
        st_box.bind("<<ComboboxSelected>>", lambda _: self.refresh())

        # ── Treeview ──
        tree_frame = tk.Frame(wrapper, bg=_BORDER, padx=1, pady=1)
        tree_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.configure("History.Treeview",
                        background=_PANEL_BG, foreground=_FG,
                        fieldbackground=_PANEL_BG, borderwidth=0,
                        font=("Segoe UI", 8), rowheight=22)
        style.configure("History.Treeview.Heading",
                        background=_BG, foreground=_MUTED,
                        font=("Segoe UI Semibold", 8))
        style.map("History.Treeview",
                  background=[("selected", "#dbeafe")],
                  foreground=[("selected", _BLUE)])

        cols = ("time", "status", "category", "description")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                            style="History.Treeview", selectmode="browse")
        tree.heading("time", text="Time")
        tree.heading("status", text="")
        tree.heading("category", text="Category")
        tree.heading("description", text="Description")
        tree.column("time", width=70, minwidth=60, stretch=False)
        tree.column("status", width=30, minwidth=30, stretch=False, anchor="center")
        tree.column("category", width=100, minwidth=80, stretch=False)
        tree.column("description", width=400, minwidth=200, stretch=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", self._on_select)

        self._refs.tree = tree

        # ── Detail row ──
        self._refs.detail_var.set("")
        detail_label = tk.Label(wrapper, textvariable=self._refs.detail_var, bg=_PANEL_BG,
                                fg=_MUTED, font=("Consolas", 8), anchor="w", justify="left")
        detail_label.pack(fill="x", pady=(2, 0))

    def _on_select(self, _event: tk.Event[tk.Misc]) -> None:
        tree = self._refs.tree
        if tree is None:
            return
        selection = tree.selection()
        if not selection:
            self._refs.detail_var.set("")
            return
        item = tree.item(selection[0])
        entry_id = item.get("tags", ("",))[0] if item.get("tags") else ""
        for entry in self.store.entries:
            if str(entry.id) == str(entry_id):
                self._refs.detail_var.set(entry.detail or "(no details)")
                return
        self._refs.detail_var.set("")

    def refresh(self) -> None:
        tree = self._refs.tree
        if tree is None:
            return
        tree.delete(*tree.get_children())
        cat_filter = self._refs.filter_cat_var.get()
        status_filter = self._refs.filter_status_var.get()
        entries = self.store.filtered(cat_filter, status_filter)
        for entry in reversed(entries):
            symbol = STATUS_SYMBOL.get(entry.status, "\u25CF")
            cat_label = CATEGORY_LABELS.get(entry.category, entry.category)
            tree.insert("", "end",
                        values=(entry.timestamp, symbol, cat_label, entry.description),
                        tags=(str(entry.id),))

    def add_and_refresh(
        self,
        category: ActionCategory,
        description: str,
        status: StatusType = "info",
        detail: str = "",
    ) -> HistoryEntry:
        entry = self.store.add(category, description, status, detail)
        self.refresh()
        return entry

    def update_last_and_refresh(self, status: StatusType, detail: str = "") -> None:
        self.store.update_last_status(status, detail)
        self.refresh()
