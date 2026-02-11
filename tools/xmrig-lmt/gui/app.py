import json
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


class BridgeGui:
    BG = "#0f1115"
    PANEL = "#171a21"
    PANEL_ALT = "#1d2230"
    FG = "#e6e8ef"
    MUTED = "#9aa3b2"
    ACCENT = "#5da9ff"
    SUCCESS = "#37d67a"
    WARN = "#ffcc66"

    def __init__(self, root):
        self.root = root
        self.root.title("LMT Miner Control Center")
        self.root.geometry("1120x760")
        self.root.minsize(980, 660)
        self.root.configure(bg=self.BG)
        self.process = None
        self.miner_process = None
        self.log_queue = queue.Queue()
        self._status_tick = False

        config = load_config()

        self.bridge_path = tk.StringVar(value=config.get("bridge_path", ""))
        self.listen = tk.StringVar(value=config.get("listen", "0.0.0.0:3333"))
        self.rpc_url = tk.StringVar(value=config.get("rpc_url", "grpc://127.0.0.1:26110"))
        self.pay_address = tk.StringVar(value=config.get("pay_address", ""))
        self.extra_data_hex = tk.StringVar(value=config.get("extra_data_hex", ""))
        self.allow_non_daa = tk.BooleanVar(value=config.get("allow_non_daa", True))
        self.refresh_ms = tk.StringVar(value=str(config.get("refresh_ms", 5000)))
        self.xmrig_path = tk.StringVar(value=config.get("xmrig_path", ""))
        self.xmrig_url = tk.StringVar(value=config.get("xmrig_url", "stratum+tcp://127.0.0.1:3333"))
        self.xmrig_extra = tk.StringVar(value=config.get("xmrig_extra", ""))
        self.start_miner_with_bridge = tk.BooleanVar(value=config.get("start_miner_with_bridge", False))

        self._configure_theme()
        self._build_layout()
        self._start_log_pump()
        self._animate_status()

    def _configure_theme(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=self.BG)
        style.configure("Card.TLabelframe", background=self.PANEL, foreground=self.FG, bordercolor=self.PANEL_ALT, borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=self.PANEL, foreground=self.FG)
        style.configure("TLabel", background=self.BG, foreground=self.FG)
        style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED)
        style.configure("Field.TEntry", fieldbackground=self.PANEL_ALT, foreground=self.FG, insertcolor=self.FG)
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#0a0c10", padding=(10, 6))
        style.map("Accent.TButton", background=[("active", "#7cbcff")])
        style.configure("TCheckbutton", background=self.PANEL, foreground=self.FG)
        style.map("TCheckbutton", background=[("active", self.PANEL)])

    def _build_layout(self):
        container = tk.Frame(self.root, bg=self.BG, padx=16, pady=14)
        container.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(container, bg=self.BG)
        header.pack(fill=tk.X, pady=(0, 10))

        title = tk.Label(header, text="LMT Miner Control Center", bg=self.BG, fg=self.FG, font=("Segoe UI", 18, "bold"))
        title.pack(side=tk.LEFT)

        self.status_label = tk.Label(
            header,
            text="● IDLE",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 11, "bold"),
            padx=8,
            pady=2,
        )
        self.status_label.pack(side=tk.RIGHT)

        subtitle = tk.Label(
            container,
            text="Bridge + XMRig launcher for LMT native stratum",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 10),
        )
        subtitle.pack(fill=tk.X, pady=(0, 10))

        content = tk.Frame(container, bg=self.BG)
        content.pack(fill=tk.BOTH, expand=True)

        form_col = tk.Frame(content, bg=self.BG)
        form_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        log_col = tk.Frame(content, bg=self.BG)
        log_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(8, 0))

        bridge_card = ttk.LabelFrame(form_col, text="Bridge settings", style="Card.TLabelframe", padding=10)
        bridge_card.pack(fill=tk.X, pady=(0, 8))

        row = 0
        self._add_row(bridge_card, row, "Bridge binary", self.bridge_path, browse=True)
        row += 1
        self._add_row(bridge_card, row, "Listen", self.listen)
        row += 1
        self._add_row(bridge_card, row, "RPC URL", self.rpc_url)
        row += 1
        self._add_row(bridge_card, row, "Pay address", self.pay_address)
        row += 1
        self._add_row(bridge_card, row, "Extra data (hex)", self.extra_data_hex)
        row += 1
        self._add_row(bridge_card, row, "Refresh ms", self.refresh_ms)
        row += 1

        checkbox = ttk.Checkbutton(bridge_card, text="Allow non-DAA blocks", variable=self.allow_non_daa)
        checkbox.grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        bridge_card.columnconfigure(1, weight=1)

        miner_card = ttk.LabelFrame(form_col, text="XMRig (fork) settings", style="Card.TLabelframe", padding=10)
        miner_card.pack(fill=tk.X, pady=(0, 8))

        row = 0
        self._add_row(miner_card, row, "XMRig binary", self.xmrig_path, browse=True, browse_target="xmrig")
        row += 1
        self._add_row(miner_card, row, "XMRig URL", self.xmrig_url)
        row += 1
        self._add_row(miner_card, row, "XMRig extra args", self.xmrig_extra)
        row += 1
        miner_checkbox = ttk.Checkbutton(miner_card, text="Start miner with bridge", variable=self.start_miner_with_bridge)
        miner_checkbox.grid(row=row, column=0, columnspan=3, sticky="w", pady=(2, 8))
        miner_card.columnconfigure(1, weight=1)

        action_card = ttk.LabelFrame(form_col, text="Actions", style="Card.TLabelframe", padding=10)
        action_card.pack(fill=tk.X, pady=(0, 8))

        btn_frame = tk.Frame(action_card, bg=self.PANEL)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Start", style="Accent.TButton", command=self.start_bridge).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Stop", command=self.stop_bridge).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Save", command=self.save_settings).pack(side=tk.LEFT)

        note = ttk.Label(
            action_card,
            text="Tip: use a valid `lmt:` address to enable native LMT flow.",
            style="Muted.TLabel",
        )
        note.pack(fill=tk.X, pady=(8, 0))

        log_card = ttk.LabelFrame(log_col, text="Live Console", style="Card.TLabelframe", padding=10)
        log_card.pack(fill=tk.BOTH, expand=True)

        self.log = ScrolledText(
            log_card,
            height=20,
            state=tk.DISABLED,
            bg="#0d1017",
            fg="#d3d8e3",
            insertbackground="#d3d8e3",
            relief=tk.FLAT,
            borderwidth=0,
            font=("Consolas", 10),
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.tag_configure("bridge", foreground="#7aa2ff")
        self.log.tag_configure("miner", foreground="#6de29f")
        self.log.tag_configure("system", foreground="#f3c767")

        footer = tk.Frame(container, bg=self.BG)
        footer.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(footer, text="LMT native stratum mode", style="Muted.TLabel").pack(side=tk.LEFT)
        self.state_hint = ttk.Label(footer, text="Bridge stopped", style="Muted.TLabel")
        self.state_hint.pack(side=tk.RIGHT)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _add_row(self, frame, row, label, variable, browse=False, browse_target="bridge"):
        tk.Label(frame, text=label, bg=self.PANEL, fg=self.FG, font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", pady=3)
        entry = tk.Entry(
            frame,
            textvariable=variable,
            width=62,
            bg=self.PANEL_ALT,
            fg=self.FG,
            insertbackground=self.FG,
            relief=tk.FLAT,
            borderwidth=6,
        )
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        if browse:
            tk.Button(
                frame,
                text="Browse",
                command=lambda: self.browse_binary(browse_target),
                bg=self.PANEL_ALT,
                fg=self.FG,
                relief=tk.FLAT,
                padx=10,
                pady=5,
                activebackground="#2b3245",
                activeforeground=self.FG,
            ).grid(
                row=row, column=2, sticky="w", padx=(6, 0)
            )

    def browse_binary(self, target):
        path = filedialog.askopenfilename(title="Select bridge binary")
        if path:
            if target == "bridge":
                self.bridge_path.set(path)
            else:
                self.xmrig_path.set(path)

    def append_log(self, text):
        self.log.configure(state=tk.NORMAL)
        tag = "system"
        if text.startswith("[miner]"):
            tag = "miner"
        elif text.startswith("[bridge]"):
            tag = "bridge"
        self.log.insert(tk.END, text + "\n", tag)
        self.log.configure(state=tk.DISABLED)
        self.log.see(tk.END)

    def _start_log_pump(self):
        def pump():
            while True:
                try:
                    line = self.log_queue.get_nowait()
                except queue.Empty:
                    break
                self.append_log(line)
            self.root.after(100, pump)

        self.root.after(100, pump)

    def start_bridge(self):
        if self.process:
            messagebox.showinfo("Bridge", "Bridge is already running.")
            return

        bridge_path = self.bridge_path.get().strip()
        if not bridge_path:
            messagebox.showerror("Bridge", "Please select the bridge binary.")
            return

        cmd = [
            bridge_path,
            "--listen",
            self.listen.get().strip(),
            "--rpc-url",
            self.rpc_url.get().strip(),
            "--pay-address",
            self.pay_address.get().strip(),
            "--refresh-ms",
            self.refresh_ms.get().strip(),
        ]
        if self.extra_data_hex.get().strip():
            cmd += ["--extra-data-hex", self.extra_data_hex.get().strip()]
        if self.allow_non_daa.get():
            cmd += ["--allow-non-daa"]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            messagebox.showerror("Bridge", f"Failed to start: {exc}")
            return

        threading.Thread(target=self._read_logs, daemon=True).start()
        self.append_log("[bridge] Bridge started.")
        self._set_status("running")
        if self.start_miner_with_bridge.get():
            self.start_miner()

    def _read_logs(self):
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self.log_queue.put(f"[bridge] {line.rstrip()}")

    def stop_bridge(self):
        if not self.process:
            return
        self.process.terminate()
        self.process = None
        self.append_log("[bridge] Bridge stopped.")
        self._set_status("idle")
        if getattr(self, "miner_process", None):
            self.stop_miner()

    def start_miner(self):
        if getattr(self, "miner_process", None):
            self.append_log("[system] Miner already running.")
            return
        xmrig_path = self.xmrig_path.get().strip()
        if not xmrig_path:
            self.append_log("[system] XMRig path not set; skipping miner start.")
            return
        url = self.xmrig_url.get().strip()
        address = self.pay_address.get().strip()
        cmd = [xmrig_path, "-o", url, "-u", address, "-p", "x"]
        extra = self.xmrig_extra.get().strip()
        if extra:
            cmd += extra.split()
        try:
            self.miner_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            self.append_log(f"[system] Failed to start miner: {exc}")
            self.miner_process = None
            return
        threading.Thread(target=self._read_miner_logs, daemon=True).start()
        self.append_log("[miner] Miner started.")

    def _read_miner_logs(self):
        proc = getattr(self, "miner_process", None)
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self.log_queue.put(f"[miner] {line.rstrip()}")

    def stop_miner(self):
        proc = getattr(self, "miner_process", None)
        if not proc:
            return
        proc.terminate()
        self.miner_process = None
        self.append_log("[miner] Miner stopped.")

    def save_settings(self):
        data = {
            "bridge_path": self.bridge_path.get(),
            "listen": self.listen.get(),
            "rpc_url": self.rpc_url.get(),
            "pay_address": self.pay_address.get(),
            "extra_data_hex": self.extra_data_hex.get(),
            "allow_non_daa": self.allow_non_daa.get(),
            "refresh_ms": int(self.refresh_ms.get() or 5000),
            "xmrig_path": self.xmrig_path.get(),
            "xmrig_url": self.xmrig_url.get(),
            "xmrig_extra": self.xmrig_extra.get(),
            "start_miner_with_bridge": self.start_miner_with_bridge.get(),
        }
        save_config(data)
        self.append_log("[system] Settings saved.")

    def _set_status(self, status):
        if status == "running":
            self.status_label.configure(text="● RUNNING", fg=self.SUCCESS)
            self.state_hint.configure(text="Bridge running")
        else:
            self.status_label.configure(text="● IDLE", fg=self.MUTED)
            self.state_hint.configure(text="Bridge stopped")

    def _animate_status(self):
        # Lightweight UI pulse animation for status indicator.
        if self.process:
            self._status_tick = not self._status_tick
            color = self.SUCCESS if self._status_tick else "#6de6a0"
            self.status_label.configure(fg=color)
        self.root.after(600, self._animate_status)

    def on_close(self):
        if self.process:
            self.process.terminate()
        if getattr(self, "miner_process", None):
            self.miner_process.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    BridgeGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
